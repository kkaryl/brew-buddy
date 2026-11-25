import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearStoredSession,
  loadStoredSession,
  saveStoredSession,
  type StoredAuthSession,
} from "../auth/session";
import { errorToFeedbackNotice } from "../components/formatters";
import { BrewApiClient, BrewApiError } from "./client";
import type {
  MemoryExtractionJobResponse,
  MemoryProposalBatchResponse,
  ProposeMemoriesRequest,
} from "./types";

const JOBS_PATH = "/api/v1/memories/extraction-jobs";
const JOB_ID = "job_extract_1";
const JOB_PATH = `${JOBS_PATH}/${JOB_ID}`;
const OVERALL_TIMEOUT_MESSAGE = "Request timed out after 90s. Please try again.";

const SESSION: StoredAuthSession = {
  accessToken: "token_alice",
  refreshToken: null,
  expiresAtMs: null,
  principal: { user_id: "usr_alice", display_name: "Alice Chen", auth_provider: "local_mock" },
};

const PAYLOAD: ProposeMemoriesRequest = {
  notes: "Alex is rolling out an evaluation harness next quarter.",
  source_type: "meeting_notes",
  contact_id: "cnt_alex",
  meeting_id: "mtg_001",
  brief_id: null,
};

const BATCH: MemoryProposalBatchResponse = {
  proposals: [
    {
      id: "prop_harness",
      scope: "contact",
      contact_id: "cnt_alex",
      memory_type: "counterpart_background",
      text: "Alex is rolling out an evaluation harness next quarter.",
      rationale: "Useful context for the next catch-up.",
      source: {
        source_type: "meeting_notes",
        meeting_id: "mtg_001",
        brief_id: null,
        proposal_id: "prop_harness",
        excerpt: "Alex is rolling out an evaluation harness next quarter.",
        recorded_at: "2026-11-24T06:10:00Z",
      },
      status: "pending",
      lifecycle_state: "proposed",
      epistemic_status: "user_reported_observation",
      supersedes_memory_id: null,
      conflict_summary: null,
      rejection_reason: null,
      approved_memory_id: null,
      created_at: "2026-11-24T06:10:00Z",
      updated_at: "2026-11-24T06:10:00Z",
      reviewed_at: null,
      version: 1,
    },
  ],
  total: 1,
  skipped_duplicates: 0,
  filtered_sensitive_count: 0,
};

function buildJob(overrides: Partial<MemoryExtractionJobResponse> = {}): MemoryExtractionJobResponse {
  return {
    id: JOB_ID,
    status: "queued",
    contact_id: "cnt_alex",
    meeting_id: "mtg_001",
    brief_id: null,
    result: null,
    error: null,
    created_at: "2026-11-24T06:10:00Z",
    updated_at: "2026-11-24T06:10:00Z",
    completed_at: null,
    ...overrides,
  };
}

const QUEUED = buildJob();
const RUNNING = buildJob({ status: "running", updated_at: "2026-11-24T06:10:01Z" });
const SUCCEEDED = buildJob({
  status: "succeeded",
  result: BATCH,
  updated_at: "2026-11-24T06:10:02Z",
  completed_at: "2026-11-24T06:10:02Z",
});

function jsonResponse(body: unknown, status: number = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface RecordedCall {
  readonly method: string;
  readonly path: string;
  readonly body: string | null;
  readonly authorization: string | null;
}

type PollReply = () => Response | Promise<Response>;

/** Answers a request that never completes until the client's own timeout aborts it. */
function hangUntilAborted(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    signal?.addEventListener("abort", () => {
      reject(new DOMException("The operation was aborted.", "AbortError"));
    });
  });
}

/**
 * Fake job backend: the POST answers with `startReply`, and each GET consumes the next poll
 * reply, repeating the last one once the script is exhausted.
 */
function installJobBackend(
  startReply: () => Response,
  pollReplies: readonly (PollReply | "hang")[],
): RecordedCall[] {
  const calls: RecordedCall[] = [];
  let pollCount = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const rawUrl =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const path = new URL(rawUrl, "http://localhost").pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    calls.push({
      method,
      path,
      body: typeof init?.body === "string" ? init.body : null,
      authorization: headers.get("Authorization"),
    });

    if (path === JOBS_PATH && method === "POST") {
      return startReply();
    }
    if (path === JOB_PATH && method === "GET") {
      const reply = pollReplies[Math.min(pollCount, pollReplies.length - 1)];
      pollCount += 1;
      if (reply === "hang") {
        return hangUntilAborted(init?.signal);
      }
      if (reply) {
        return reply();
      }
    }
    return jsonResponse(
      {
        error: {
          code: "NOT_FOUND",
          message: `Unhandled ${method} ${path}`,
          trace_id: "trc_unhandled",
          details: [],
        },
      },
      404,
    );
  });
  return calls;
}

function createClient(
  overrides: { readonly pollIntervalMs?: number; readonly onUnauthorized?: (reason: string) => void } = {},
): BrewApiClient {
  return new BrewApiClient({
    getSession: () => SESSION,
    ...(overrides.pollIntervalMs !== undefined
      ? { memoryExtractionPollIntervalMs: overrides.pollIntervalMs }
      : {}),
    ...(overrides.onUnauthorized ? { onUnauthorized: overrides.onUnauthorized } : {}),
  });
}

function pollCalls(calls: readonly RecordedCall[]): readonly RecordedCall[] {
  return calls.filter((call) => call.method === "GET" && call.path === JOB_PATH);
}

describe("BrewApiClient memory extraction jobs", () => {
  beforeEach(() => {
    clearStoredSession();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    clearStoredSession();
  });

  it("starts a job, polls until it succeeded, and returns the proposal batch", async () => {
    const calls = installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(SUCCEEDED)],
    );

    const batch = await createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD);

    expect(batch).toEqual(BATCH);
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      `POST ${JOBS_PATH}`,
      `GET ${JOB_PATH}`,
    ]);
    expect(JSON.parse(calls[0]?.body ?? "null")).toEqual(PAYLOAD);
    expect(calls.every((call) => call.authorization === "Bearer token_alice")).toBe(true);
    expect(calls.some((call) => call.path === "/api/v1/memories/propose")).toBe(false);
  });

  it("keeps polling through queued and running until the job succeeded", async () => {
    const calls = installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [
        () => jsonResponse(QUEUED),
        () => jsonResponse(RUNNING),
        () => jsonResponse(RUNNING),
        () => jsonResponse(SUCCEEDED),
      ],
    );

    const batch = await createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD);

    expect(batch).toEqual(BATCH);
    expect(pollCalls(calls)).toHaveLength(4);
  });

  it("returns without polling when the start response is already terminal", async () => {
    const calls = installJobBackend(() => jsonResponse(SUCCEEDED, 202), [() => jsonResponse(SUCCEEDED)]);

    const batch = await createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD);

    expect(batch).toEqual(BATCH);
    expect(pollCalls(calls)).toHaveLength(0);
  });

  it("waits the default 1000 ms between polls when no interval is injected", async () => {
    vi.useFakeTimers();
    const calls = installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(RUNNING), () => jsonResponse(SUCCEEDED)],
    );

    const pending = createClient().proposeMemories(PAYLOAD);

    await vi.advanceTimersByTimeAsync(999);
    expect(pollCalls(calls)).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(pollCalls(calls)).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(pollCalls(calls)).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(pollCalls(calls)).toHaveLength(2);

    await expect(pending).resolves.toEqual(BATCH);
  });

  it("surfaces a failed job as a BrewApiError carrying the job error code and message", async () => {
    const failed = buildJob({
      status: "failed",
      error: {
        code: "VALIDATION_ERROR",
        message: "No candidate memories could be extracted from notes.",
      },
      completed_at: "2026-11-24T06:10:02Z",
    });
    installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(RUNNING), () => jsonResponse(failed)],
    );

    const caught: unknown = await createClient({ pollIntervalMs: 1 })
      .proposeMemories(PAYLOAD)
      .catch((err: unknown) => err);

    expect(caught).toBeInstanceOf(BrewApiError);
    expect(caught).toMatchObject({
      name: "BrewApiError",
      code: "VALIDATION_ERROR",
      message: "No candidate memories could be extracted from notes.",
      isUnauthorized: false,
    } satisfies Partial<BrewApiError>);
    // The debrief screen renders failures through this formatter.
    expect(errorToFeedbackNotice(caught, "Could not suggest keepsakes")).toEqual({
      kind: "error",
      title: "Could not suggest keepsakes",
      message: "No candidate memories could be extracted from notes.",
      details: [],
      traceId: null,
    });
  });

  it("reports a clear error when a failed job carries no error object", async () => {
    installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(buildJob({ status: "failed" }))],
    );

    await expect(
      createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD),
    ).rejects.toMatchObject({
      name: "BrewApiError",
      code: "MEMORY_EXTRACTION_FAILED",
      message: "Brew could not finish suggesting keepsakes from these notes. Please try again.",
    } satisfies Partial<BrewApiError>);
  });

  it("treats a succeeded job without a result as a failure instead of returning nothing", async () => {
    installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(buildJob({ status: "succeeded", result: null }))],
    );

    await expect(
      createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD),
    ).rejects.toMatchObject({
      name: "BrewApiError",
      code: "MEMORY_EXTRACTION_RESULT_MISSING",
      message: "Brew finished reading your notes but returned no suggestions. Please try again.",
    } satisfies Partial<BrewApiError>);
  });

  it("raises the standard request timeout once the overall 90s deadline is exhausted", async () => {
    vi.useFakeTimers();
    const calls = installJobBackend(() => jsonResponse(QUEUED, 202), [() => jsonResponse(RUNNING)]);

    const pending = createClient().proposeMemories(PAYLOAD);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "BrewApiError",
      code: "REQUEST_TIMEOUT",
      status: 504,
      message: OVERALL_TIMEOUT_MESSAGE,
    } satisfies Partial<BrewApiError>);

    await vi.advanceTimersByTimeAsync(88_000);
    const pollsBeforeDeadline = pollCalls(calls).length;
    expect(pollsBeforeDeadline).toBe(88);

    await vi.advanceTimersByTimeAsync(2_000);
    await assertion;

    // Polling stops for good once the deadline has passed.
    const pollsAtDeadline = pollCalls(calls).length;
    expect(pollsAtDeadline).toBeLessThanOrEqual(90);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(pollCalls(calls)).toHaveLength(pollsAtDeadline);
  });

  it("cuts off a poll that hangs near the deadline at the overall deadline", async () => {
    vi.useFakeTimers();
    const startedAtMs = Date.now();
    const runningReplies: PollReply[] = Array.from({ length: 85 }, () => () => jsonResponse(RUNNING));
    installJobBackend(() => jsonResponse(QUEUED, 202), [...runningReplies, "hang"]);

    let settledAtMs: number | null = null;
    const pending = createClient()
      .proposeMemories(PAYLOAD)
      .finally(() => {
        settledAtMs = Date.now();
      });
    const assertion = expect(pending).rejects.toMatchObject({
      name: "BrewApiError",
      code: "REQUEST_TIMEOUT",
      status: 504,
      message: OVERALL_TIMEOUT_MESSAGE,
    } satisfies Partial<BrewApiError>);

    await vi.advanceTimersByTimeAsync(120_000);
    await assertion;

    expect(settledAtMs).not.toBeNull();
    expect((settledAtMs ?? Number.POSITIVE_INFINITY) - startedAtMs).toBeLessThanOrEqual(90_000);
  });

  it("clears the session and notifies the app when a poll returns 401", async () => {
    saveStoredSession(SESSION);
    const onUnauthorized = vi.fn<(reason: string) => void>();
    const calls = installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [
        () => jsonResponse(RUNNING),
        () =>
          jsonResponse(
            {
              error: {
                code: "TOKEN_EXPIRED",
                message: "Session token expired. Please sign in again.",
                trace_id: "trc_401_poll",
                details: [],
              },
            },
            401,
          ),
      ],
    );

    await expect(
      createClient({ pollIntervalMs: 1, onUnauthorized }).proposeMemories(PAYLOAD),
    ).rejects.toMatchObject({
      name: "BrewApiError",
      status: 401,
      code: "TOKEN_EXPIRED",
      isUnauthorized: true,
    } satisfies Partial<BrewApiError>);

    expect(loadStoredSession()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledWith("Session token expired. Please sign in again.");
    // No further polls after the session was rejected.
    expect(pollCalls(calls)).toHaveLength(2);
  });

  it("returns reference errors from the start call immediately without polling", async () => {
    const calls = installJobBackend(
      () =>
        jsonResponse(
          {
            error: {
              code: "NOT_FOUND",
              message: "Contact not found.",
              trace_id: "trc_404_start",
              details: [],
            },
          },
          404,
        ),
      [() => jsonResponse(SUCCEEDED)],
    );

    await expect(
      createClient({ pollIntervalMs: 1 }).proposeMemories(PAYLOAD),
    ).rejects.toMatchObject({
      name: "BrewApiError",
      status: 404,
      code: "NOT_FOUND",
      message: "Contact not found.",
      traceId: "trc_404_start",
    } satisfies Partial<BrewApiError>);
    expect(pollCalls(calls)).toHaveLength(0);
  });

  it("exposes the low-level start and get job calls", async () => {
    const calls = installJobBackend(
      () => jsonResponse(QUEUED, 202),
      [() => jsonResponse(RUNNING)],
    );
    const client = createClient();

    await expect(client.startMemoryExtraction(PAYLOAD)).resolves.toEqual(QUEUED);
    await expect(client.getMemoryExtractionJob(JOB_ID)).resolves.toEqual(RUNNING);
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      `POST ${JOBS_PATH}`,
      `GET ${JOB_PATH}`,
    ]);
  });

  it("updates and persists custom principal display name via PATCH /api/v1/auth/me and session storage", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      expect(path).toBe("/api/v1/auth/me");
      expect(method).toBe("PATCH");
      const body = JSON.parse(String(init?.body ?? "{}")) as { display_name: string | null };
      return jsonResponse({
        user_id: "usr_alice",
        display_name: body.display_name ?? "Alice Chen",
        custom_display_name: body.display_name,
        account_display_name: "Alice Chen",
        auth_provider: "verified",
      });
    });

    const client = createClient();
    const updated = await client.updateCurrentPrincipal({ display_name: "Ally" });
    expect(updated).toEqual({
      user_id: "usr_alice",
      display_name: "Ally",
      custom_display_name: "Ally",
      account_display_name: "Alice Chen",
      auth_provider: "verified",
    });

    saveStoredSession({ ...SESSION, principal: updated });
    expect(loadStoredSession()?.principal).toEqual(updated);
  });
});
