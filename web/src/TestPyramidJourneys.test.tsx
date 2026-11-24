import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BrewApiClient, type BrewApiError } from "./api/client";
import type {
  AuthClientConfigResponse,
  ContactResponse,
  MeetingResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
} from "./api/types";

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (reason?: unknown) => void;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function jsonResponse(body: unknown, status: number = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const HEALTH_OK = {
  status: "ok",
  service: "brew",
  version: "0.1.0",
  environment: "local",
  model: "gemini-3.8-flash",
  timestamp_utc: "2026-11-24T06:00:00Z",
};

const LOCAL_AUTH_CONFIG: AuthClientConfigResponse = {
  auth_mode: "local_mock",
  environment: "local",
  local_mock_enabled: true,
  google_sign_in_enabled: false,
  firebase: null,
  google_oauth_client_id: null,
  mock_personas: [
    {
      persona_id: "alice",
      display_name: "Alice Chen",
      role_summary: "Product Lead · Isolated Local Workspace",
    },
  ],
};

function makeBrief(overrides?: Partial<PreparationBriefResponse>): PreparationBriefResponse {
  return {
    id: "brf_maya_1",
    meeting_id: "mtg_maya_1",
    contact_id: "cnt_maya",
    duration_minutes: 30,
    tone: "structured_executive",
    contact_context: "Maya Lin is a Principal SRE at CloudScale.",
    meeting_objective: "Understand multi-region failover game days.",
    conversation_openers: [
      "Thanks for carving out time, excited to learn how CloudScale runs failover drills.",
      "How has Q4 reliability planning been going across your regions?",
    ],
    time_boxed_agenda: [
      {
        title: "Context & Framing",
        duration_minutes: 5,
        description: "Align on failover scope.",
      },
      {
        title: "Game-Day Architecture",
        duration_minutes: 20,
        description: "Discuss dependency mapping and blast-radius controls.",
      },
      {
        title: "Next Steps",
        duration_minutes: 5,
        description: "Confirm follow-up notes.",
      },
    ],
    suggested_questions: [
      {
        id: "q_sre_1",
        question: "How do you validate service dependency maps before triggering regional drains?",
        rationale: "Directly addresses pre-game-day safety checks.",
        category: "Reliability",
      },
      {
        id: "q_sre_2",
        question: "Which post-incident metrics actually changed team behavior over two quarters?",
        rationale: "Surfaces durable operational lessons.",
        category: "Culture",
      },
    ],
    suggested_follow_up_topics: ["Share game-day checklist template after the chat."],
    referenced_memory_ids: ["mem_maya_1"],
    revision_summary: null,
    version: 1,
    created_at: "2026-11-24T06:05:00Z",
    updated_at: "2026-11-24T06:05:00Z",
    workflow: {
      request_id: "req_j_1",
      trace_id: "trc_j_1",
      operation: "generate",
      terminal_state: "completed",
      attempt_count: 1,
      regeneration_count: 0,
      model_invocations: 1,
      tool_invocations: 1,
      replayed: false,
      quality_passed: true,
      degraded_sources: [],
      previous_version: null,
    },
    ...overrides,
  };
}

describe("Brew Test Pyramid: v2 Frontend Journeys, States, Memory Governance, and Revisions", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("1. User journey: Quick Spark sentence, multi-counterpart folios, fine-tuned preferences, and sign-out", async () => {
    const contacts: ContactResponse[] = [];
    const meetings: MeetingResponse[] = [];
    const briefs = new Map<string, PreparationBriefResponse>();
    let capturedGenerateBody: Record<string, unknown> | null = null;
    let logoutCalled = false;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const parsed = new URL(rawUrl, "http://localhost");
      const path = parsed.pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") return jsonResponse(LOCAL_AUTH_CONFIG);
      if (path === "/api/auth/mock-session" && method === "POST") {
        return jsonResponse(
          {
            access_token: "mses_journey_tok",
            token_type: "Bearer",
            expires_at: new Date(Date.now() + 3600_000).toISOString(),
            principal: {
              user_id: "usr_mock_alice",
              display_name: "Alice Chen",
              auth_provider: "local_mock",
            },
          },
          201,
        );
      }
      if (path === "/api/auth/logout" && method === "POST") {
        logoutCalled = true;
        return new Response(null, { status: 204 });
      }
      if (path === "/api/v1/auth/me") {
        return jsonResponse({
          user_id: "usr_mock_alice",
          display_name: "Alice Chen",
          auth_provider: "local_mock",
        });
      }
      if (path === "/api/v1/contacts" && method === "GET") {
        return jsonResponse({ items: contacts, total: contacts.length });
      }
      if (path === "/api/v1/contacts" && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        const id = `cnt_${String(contacts.length + 1)}`;
        const created: ContactResponse = {
          id,
          name: String(body["name"] ?? ""),
          title: typeof body["title"] === "string" ? body["title"] : null,
          role: typeof body["role"] === "string" ? body["role"] : null,
          organization: typeof body["organization"] === "string" ? body["organization"] : null,
          context_notes: typeof body["context_notes"] === "string" ? body["context_notes"] : null,
          version: 1,
          created_at: "2026-11-24T06:01:00Z",
          updated_at: "2026-11-24T06:01:00Z",
        };
        contacts.push(created);
        return jsonResponse(created, 201);
      }
      if (path === "/api/v1/meetings" && method === "GET") {
        const cid = parsed.searchParams.get("contact_id");
        const filtered = cid ? meetings.filter((m) => m.contact_id === cid) : meetings;
        return jsonResponse({ items: filtered, total: filtered.length });
      }
      if (path === "/api/v1/briefs/generate" && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        capturedGenerateBody = body;
        const idx = briefs.size + 1;
        const briefId = `brf_${String(idx)}`;
        const mtgId = `mtg_${String(idx)}`;
        const brief = makeBrief({
          id: briefId,
          meeting_id: mtgId,
          contact_id: String(body["contact_id"]),
          duration_minutes: Number(body["duration_minutes"] ?? 30),
          meeting_objective: String(body["meeting_objective"]),
        });
        briefs.set(briefId, brief);
        meetings.unshift({
          id: mtgId,
          contact_id: brief.contact_id,
          purpose: (body["purpose"] as MeetingResponse["purpose"]) ?? "coffee_chat",
          tone: brief.tone,
          objective: brief.meeting_objective,
          duration_minutes: brief.duration_minutes,
          scheduled_at: null,
          notes: null,
          status: "preparing",
          latest_brief_id: briefId,
          version: 1,
          created_at: "2026-11-24T06:05:00Z",
          updated_at: "2026-11-24T06:05:00Z",
        });
        return jsonResponse(brief, 201);
      }
      if (path.startsWith("/api/v1/briefs/") && path.endsWith("/revisions")) {
        const bid = path.split("/")[4] ?? "";
        const found = briefs.get(bid);
        return jsonResponse({ items: found ? [found] : [], total: found ? 1 : 0 });
      }
      if (path.startsWith("/api/v1/briefs/")) {
        const bid = path.split("/")[4] ?? "";
        const found = briefs.get(bid);
        return found ? jsonResponse(found) : jsonResponse({}, 404);
      }
      if (path === "/api/v1/memories/proposals") {
        return jsonResponse({
          proposals: [],
          total: 0,
          skipped_duplicates: 0,
          filtered_sensitive_count: 0,
        });
      }
      if (path === "/api/v1/memories") {
        return jsonResponse({ items: [], total: 0 });
      }
      return jsonResponse({}, 404);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    // Save personal coaching style note first in Relationship Journal -> My Coaching Style
    fireEvent.click(
      await screen.findByRole("button", { name: /Account and coaching style for Alice Chen/i }),
    );
    fireEvent.change(await screen.findByLabelText(/Personal communication style note/i), {
      target: { value: "Prefer concrete engineering stories." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save Defaults/i }));

    // Add first counterpart via "+ Person" modal in Relationship Journal
    fireEvent.click(screen.getByRole("button", { name: /^Person$/i }));
    const dialog1 = await screen.findByRole("dialog", { name: /New Counterpart/i });
    fireEvent.change(within(dialog1).getByLabelText(/Full name/i), {
      target: { value: "Maya Lin" },
    });
    fireEvent.change(within(dialog1).getByLabelText(/Title/i), {
      target: { value: "Principal SRE" },
    });
    fireEvent.change(within(dialog1).getByLabelText(/Organization/i), {
      target: { value: "CloudScale" },
    });
    fireEvent.click(within(dialog1).getByRole("button", { name: /Save Counterpart/i }));
    await screen.findByRole("heading", { level: 2, name: "Maya Lin" });

    // Start setup for Maya Lin via "Prep Chat" button
    fireEvent.click(screen.getByRole("button", { name: /Prep Chat/i }));
    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });

    // Select Mentorship in Mad-Libs + expand optional fine-tuning
    fireEvent.change(screen.getByLabelText(/Conversation purpose/i), {
      target: { value: "mentorship" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: /Fine-tune question count, custom length, or pre-chat notes/i,
      }),
    );
    fireEvent.change(screen.getByLabelText(/Question count/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/Focus areas/i), {
      target: { value: "incident reviews, game days" },
    });
    fireEvent.change(
      screen.getByLabelText(/What would make this 30-minute chat feel worthwhile/i),
      {
        target: { value: "Learn how Maya scales multi-region failover drills." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));

    expect(
      await screen.findByText(/How do you validate service dependency maps/i),
    ).toBeInTheDocument();
    expect(capturedGenerateBody).not.toBeNull();
    expect(capturedGenerateBody?.["preferences"]).toEqual({
      preferred_question_count: 4,
      communication_style_notes: "Prefer concrete engineering stories.",
      focus_areas: ["incident reviews", "game days"],
    });

    // Use Quick Spark natural-language sentence from Clubhouse to create a second counterpart + brief
    const navBar = screen.getByRole("navigation", { name: /^Primary navigation$/i });
    fireEvent.click(within(navBar).getByRole("button", { name: /^Clubhouse$/i }));
    const sparkArea = await screen.findByLabelText(/Describe an off-calendar conversation/i);
    fireEvent.change(sparkArea, {
      target: {
        value: "20m casual coffee chat with Jordan Kim at Figma about design token governance",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Spark Brief/i }));

    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });
    expect(screen.getByLabelText(/Who are you meeting/i)).toHaveValue("Jordan Kim");
    expect(screen.getByLabelText(/Meeting duration/i)).toHaveValue("20");
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Jordan Kim" }),
    ).toBeInTheDocument();

    // Switch back to Maya Lin via Studio counterpart switcher
    fireEvent.change(screen.getByLabelText(/Switch counterpart deck/i), {
      target: { value: "cnt_1" },
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Maya Lin" }),
    ).toBeInTheDocument();

    // Sign out via Coaching Style folio
    fireEvent.click(
      screen.getByRole("button", { name: /Account and coaching style for Alice Chen/i }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Sign out/i }));

    await waitFor(() => {
      expect(screen.getByText(/Sign in to your workspace/i)).toBeInTheDocument();
    });
    expect(logoutCalled).toBe(true);
    expect(window.sessionStorage.getItem("brew.auth.session.v1")).toBeNull();
  });

  it("2. Loading & error states: deferred in-flight synthesis, 504 model timeout, degraded fallback, and AbortError timeout", async () => {
    const generateGate = createDeferred<Response>();
    let attempt = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") return jsonResponse(LOCAL_AUTH_CONFIG);
      if (path === "/api/auth/mock-session") {
        return jsonResponse(
          {
            access_token: "mses_loading_tok",
            token_type: "Bearer",
            expires_at: new Date(Date.now() + 3600_000).toISOString(),
            principal: {
              user_id: "usr_mock_alice",
              display_name: "Alice Chen",
              auth_provider: "local_mock",
            },
          },
          201,
        );
      }
      if (path === "/api/v1/auth/me") {
        return jsonResponse({
          user_id: "usr_mock_alice",
          display_name: "Alice Chen",
          auth_provider: "local_mock",
        });
      }
      if (path === "/api/v1/contacts") {
        return jsonResponse({
          items: [
            {
              id: "cnt_maya",
              name: "Maya Lin",
              title: "Principal SRE",
              role: null,
              organization: "CloudScale",
              context_notes: null,
              version: 1,
              created_at: "2026-11-24T06:00:00Z",
              updated_at: "2026-11-24T06:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/v1/meetings") return jsonResponse({ items: [], total: 0 });
      if (path === "/api/v1/memories/proposals") {
        return jsonResponse({
          proposals: [],
          total: 0,
          skipped_duplicates: 0,
          filtered_sensitive_count: 0,
        });
      }
      if (path === "/api/v1/memories") return jsonResponse({ items: [], total: 0 });
      if (path === "/api/v1/briefs/generate" && method === "POST") {
        attempt += 1;
        if (attempt === 1) {
          return generateGate.promise;
        }
        const degradedBrief = makeBrief({
          workflow: {
            request_id: "req_deg_2",
            trace_id: "trc_deg_2",
            operation: "generate",
            terminal_state: "completed",
            attempt_count: 1,
            regeneration_count: 0,
            model_invocations: 1,
            tool_invocations: 1,
            replayed: false,
            quality_passed: true,
            degraded_sources: ["meeting_history"],
            previous_version: null,
          },
        });
        return jsonResponse(degradedBrief, 201);
      }
      if (path.startsWith("/api/v1/briefs/") && path.endsWith("/revisions")) {
        return jsonResponse({ items: [makeBrief()], total: 1 });
      }
      return jsonResponse({}, 404);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Quick Spark/i }));
    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });

    fireEvent.change(screen.getByLabelText(/Or saved person/i), {
      target: { value: "cnt_maya" },
    });
    fireEvent.change(
      screen.getByLabelText(/What would make this 30-minute chat feel worthwhile/i),
      {
        target: { value: "Explore regional failover drills with Maya." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));

    const inFlightBtn = await screen.findByRole("button", {
      name: /Synthesizing Cue Deck\.\.\./i,
    });
    expect(inFlightBtn).toBeDisabled();

    generateGate.resolve(
      jsonResponse(
        {
          error: {
            code: "MODEL_TIMEOUT",
            message: "The coaching model timed out before completing the preparation brief.",
            trace_id: "trace_timeout_504",
            details: [],
          },
        },
        504,
      ),
    );

    expect(
      await screen.findByText(
        /The coaching model timed out before completing the preparation brief/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Trace: trace_timeout_504/i)).toBeInTheDocument();

    // Retry succeeds -> enters Cue Studio with degraded fallback banner
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));
    expect(
      await screen.findByText(/Generated with partial context fallback \(meeting_history\)/i),
    ).toBeInTheDocument();

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new DOMException("The operation was aborted.", "AbortError"),
    );
    const client = new BrewApiClient({ getSession: () => null });
    await expect(client.fetchAuthConfig()).rejects.toMatchObject({
      name: "BrewApiError",
      code: "REQUEST_TIMEOUT",
      status: 504,
    } satisfies Partial<BrewApiError>);
  });

  it("3. Memory approval & deletion: supersession stamp, Coaching Style folio, earlier-notes toggle, and cancel/confirm delete", async () => {
    const proposals: MemoryProposalResponse[] = [
      {
        id: "prop_supersede_1",
        scope: "contact",
        contact_id: "cnt_maya",
        memory_type: "counterpart_background",
        text: "In Nov 23 notes, Maya Lin shifted focus from manual dependency maps to automated service-mesh discovery.",
        rationale: "Updates prior dependency mapping note.",
        source: {
          source_type: "meeting_notes",
          meeting_id: "mtg_maya_1",
          brief_id: "brf_maya_1",
          proposal_id: "prop_supersede_1",
          excerpt: "Maya shifted focus to automated service-mesh discovery.",
          recorded_at: "2026-11-23T07:10:00Z",
        },
        status: "pending",
        lifecycle_state: "proposed",
        epistemic_status: "user_reported_observation",
        supersedes_memory_id: "mem_maya_old",
        conflict_summary: "Supersedes earlier manual dependency mapping note.",
        rejection_reason: null,
        approved_memory_id: null,
        created_at: "2026-11-23T07:10:00Z",
        updated_at: "2026-11-23T07:10:00Z",
        reviewed_at: null,
        version: 1,
      },
    ];
    let memories: MemoryResponse[] = [
      {
        id: "mem_maya_old",
        owner_user_id: "usr_mock_alice",
        scope: "contact",
        contact_id: "cnt_maya",
        memory_type: "counterpart_background",
        text: "In Nov 2 notes, Maya Lin mentioned manual dependency maps slowed Q3 drills.",
        source: {
          source_type: "meeting_notes",
          meeting_id: "mtg_maya_0",
          brief_id: null,
          proposal_id: null,
          excerpt: "Manual dependency maps slowed Q3 drills.",
          recorded_at: "2026-11-02T10:00:00Z",
        },
        consent_status: "approved",
        lifecycle_state: "approved",
        epistemic_status: "user_reported_observation",
        supersedes_memory_id: null,
        superseded_by_memory_id: null,
        superseded_at: null,
        created_at: "2026-11-02T10:00:00Z",
        updated_at: "2026-11-02T10:00:00Z",
        version: 1,
      },
      {
        id: "mem_user_pref_1",
        owner_user_id: "usr_mock_alice",
        scope: "user_preference",
        contact_id: null,
        memory_type: "communication_preference",
        text: "User preference: Prefers informal engineering chats.",
        source: {
          source_type: "direct_user_input",
          meeting_id: null,
          brief_id: null,
          proposal_id: null,
          excerpt: "I prefer informal engineering chats.",
          recorded_at: "2026-11-10T10:00:00Z",
        },
        consent_status: "approved",
        lifecycle_state: "approved",
        epistemic_status: "user_stated_preference",
        supersedes_memory_id: null,
        superseded_by_memory_id: null,
        superseded_at: null,
        created_at: "2026-11-10T10:00:00Z",
        updated_at: "2026-11-10T10:00:00Z",
        version: 1,
      },
    ];
    let sawIncludeSupersededQuery = false;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const parsed = new URL(rawUrl, "http://localhost");
      const path = parsed.pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") return jsonResponse(LOCAL_AUTH_CONFIG);
      if (path === "/api/auth/mock-session") {
        return jsonResponse(
          {
            access_token: "mses_mem_tok",
            token_type: "Bearer",
            expires_at: new Date(Date.now() + 3600_000).toISOString(),
            principal: {
              user_id: "usr_mock_alice",
              display_name: "Alice Chen",
              auth_provider: "local_mock",
            },
          },
          201,
        );
      }
      if (path === "/api/v1/auth/me") {
        return jsonResponse({
          user_id: "usr_mock_alice",
          display_name: "Alice Chen",
          auth_provider: "local_mock",
        });
      }
      if (path === "/api/v1/contacts") {
        return jsonResponse({
          items: [
            {
              id: "cnt_maya",
              name: "Maya Lin",
              title: "Principal SRE",
              role: "Engineering Peer",
              organization: "CloudScale",
              context_notes: null,
              version: 1,
              created_at: "2026-11-23T07:00:00Z",
              updated_at: "2026-11-23T07:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/v1/meetings") return jsonResponse({ items: [], total: 0 });
      if (path === "/api/v1/memories/proposals" && method === "GET") {
        const activePending = proposals.filter((p) => p.status === "pending");
        return jsonResponse({
          proposals: activePending,
          total: activePending.length,
          skipped_duplicates: 0,
          filtered_sensitive_count: 0,
        });
      }
      if (path === "/api/v1/memories/prop_supersede_1/approve" && method === "POST") {
        const currentProposal = proposals[0];
        if (!currentProposal) {
          return jsonResponse({}, 404);
        }
        proposals[0] = {
          ...currentProposal,
          status: "approved",
          lifecycle_state: "approved",
          version: 2,
        };
        const newMem: MemoryResponse = {
          id: "mem_maya_new",
          owner_user_id: "usr_mock_alice",
          scope: "contact",
          contact_id: "cnt_maya",
          memory_type: "counterpart_background",
          text: "In Nov 23 notes, Maya Lin shifted focus from manual dependency maps to automated service-mesh discovery.",
          source: currentProposal.source,
          consent_status: "approved",
          lifecycle_state: "approved",
          epistemic_status: "user_reported_observation",
          supersedes_memory_id: "mem_maya_old",
          superseded_by_memory_id: null,
          superseded_at: null,
          created_at: "2026-11-23T07:12:00Z",
          updated_at: "2026-11-23T07:12:00Z",
          version: 1,
        };
        memories = memories.map((m) =>
          m.id === "mem_maya_old"
            ? {
                ...m,
                lifecycle_state: "superseded",
                superseded_by_memory_id: "mem_maya_new",
                superseded_at: "2026-11-23T07:12:00Z",
                version: 2,
              }
            : m,
        );
        memories.unshift(newMem);
        return jsonResponse(newMem);
      }
      if (path === "/api/v1/memories" && method === "GET") {
        const incSup = parsed.searchParams.get("include_superseded") === "true";
        if (incSup) sawIncludeSupersededQuery = true;
        const visible = incSup
          ? memories
          : memories.filter((m) => m.lifecycle_state === "approved");
        return jsonResponse({ items: visible, total: visible.length });
      }
      if (path.startsWith("/api/v1/memories/") && method === "DELETE") {
        const mid = path.split("/")[4] ?? "";
        memories = memories.filter((m) => m.id !== mid);
        return new Response(null, { status: 204 });
      }
      return jsonResponse({}, 404);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    // Open Debrief via Clubhouse's "Edit" on Recent Keepsakes card
    fireEvent.click(await screen.findByRole("button", { name: /^Edit$/i }));
    await screen.findByRole("heading", { level: 2, name: /Stamp what belongs in memory/i });

    // Verify supersession strikethrough text from old memory is displayed!
    expect(
      screen.getByText(/Maya Lin mentioned manual dependency maps slowed Q3 drills/i),
    ).toBeInTheDocument();

    // Validate <3 char edit guard, cancel, then Stamp Keep
    fireEvent.click(screen.getByRole("button", { name: /^Edit$/i }));
    const editArea = await screen.findByLabelText(/Edit keepsake/i);
    fireEvent.change(editArea, { target: { value: "No" } });
    fireEvent.click(screen.getByRole("button", { name: /Save & Stamp Keep/i }));
    expect(
      await screen.findByText("Keepsake text must be at least 3 characters."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));
    fireEvent.click(screen.getByRole("button", { name: /Stamp Keep/i }));
    expect(
      await screen.findByText(/archived the earlier note/i),
    ).toBeInTheDocument();

    // Navigate to Relationship Journal -> Maya Lin folio
    fireEvent.click(screen.getByRole("button", { name: /Back to Clubhouse/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Relationship Journal/i }));

    expect(
      await screen.findByText(
        "In Nov 23 notes, Maya Lin shifted focus from manual dependency maps to automated service-mesh discovery.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "In Nov 2 notes, Maya Lin mentioned manual dependency maps slowed Q3 drills.",
      ),
    ).not.toBeInTheDocument();

    // Enable "Show earlier notes" -> superseded note appears with "Archived" badge
    fireEvent.click(screen.getByLabelText(/Show earlier notes/i));
    expect(
      await screen.findByText(
        "In Nov 2 notes, Maya Lin mentioned manual dependency maps slowed Q3 drills.",
      ),
    ).toBeInTheDocument();
    expect(sawIncludeSupersededQuery).toBe(true);

    // Switch to My Coaching Style folio -> cancel delete first, then Confirm Delete on preference memory
    fireEvent.click(screen.getByRole("button", { name: /My Coaching Style \(Alice\)/i }));
    expect(
      await screen.findByText("User preference: Prefers informal engineering chats."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Delete$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Cancel$/i }));
    expect(
      screen.getByText("User preference: Prefers informal engineering chats."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Delete$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Confirm Delete/i }));
    await waitFor(() => {
      expect(
        screen.queryByText("User preference: Prefers informal engineering chats."),
      ).not.toBeInTheDocument();
    });
  });

  it("4. Revision interactions: field validation, preset chips, v1->v2->v3 archived snapshot lock, and 409 Reload Latest Version", async () => {
    const v1 = makeBrief({ version: 1, duration_minutes: 30, tone: "structured_executive" });
    let serverLatest = v1;
    let serverRevisions: PreparationBriefResponse[] = [v1];
    let forceConflictOnce = false;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") return jsonResponse(LOCAL_AUTH_CONFIG);
      if (path === "/api/auth/mock-session") {
        return jsonResponse(
          {
            access_token: "mses_rev_tok",
            token_type: "Bearer",
            expires_at: new Date(Date.now() + 3600_000).toISOString(),
            principal: {
              user_id: "usr_mock_alice",
              display_name: "Alice Chen",
              auth_provider: "local_mock",
            },
          },
          201,
        );
      }
      if (path === "/api/v1/auth/me") {
        return jsonResponse({
          user_id: "usr_mock_alice",
          display_name: "Alice Chen",
          auth_provider: "local_mock",
        });
      }
      if (path === "/api/v1/contacts") {
        return jsonResponse({
          items: [
            {
              id: "cnt_maya",
              name: "Maya Lin",
              title: "Principal SRE",
              role: null,
              organization: "CloudScale",
              context_notes: null,
              version: 1,
              created_at: "2026-11-23T07:00:00Z",
              updated_at: "2026-11-23T07:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/v1/meetings") {
        return jsonResponse({
          items: [
            {
              id: "mtg_maya_1",
              contact_id: "cnt_maya",
              purpose: "coffee_chat",
              tone: serverLatest.tone,
              objective: serverLatest.meeting_objective,
              duration_minutes: serverLatest.duration_minutes,
              scheduled_at: null,
              notes: null,
              status: "preparing",
              latest_brief_id: "brf_maya_1",
              version: serverLatest.version,
              created_at: "2026-11-23T07:05:00Z",
              updated_at: "2026-11-23T07:05:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/v1/briefs/brf_maya_1/revisions" && method === "GET") {
        return jsonResponse({ items: serverRevisions, total: serverRevisions.length });
      }
      if (path === "/api/v1/briefs/brf_maya_1/revise" && method === "POST") {
        if (forceConflictOnce) {
          forceConflictOnce = false;
          const v4External = makeBrief({
            version: 4,
            duration_minutes: 20,
            tone: "candid_coaching",
            revision_summary: "Synced external v4 revision.",
          });
          serverLatest = v4External;
          serverRevisions = [...serverRevisions, v4External];
          return jsonResponse(
            {
              error: {
                code: "VERSION_CONFLICT",
                message: "Expected version 3, found 4.",
                trace_id: "trc_v4_conflict",
                details: [],
              },
            },
            409,
          );
        }
        const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        const nextVer = serverLatest.version + 1;
        const nextDur =
          typeof body["duration_minutes"] === "number"
            ? body["duration_minutes"]
            : serverLatest.duration_minutes;
        const nextTone =
          typeof body["tone"] === "string"
            ? (body["tone"] as PreparationBriefResponse["tone"])
            : serverLatest.tone;
        const nextBrief = makeBrief({
          version: nextVer,
          duration_minutes: nextDur,
          tone: nextTone,
          revision_summary: `Revision v${String(nextVer)}: ${String(body["instructions"])}`,
        });
        serverLatest = nextBrief;
        serverRevisions = [...serverRevisions, nextBrief];
        return jsonResponse(nextBrief);
      }
      if (path === "/api/v1/briefs/brf_maya_1" && method === "GET") {
        return jsonResponse(serverLatest);
      }
      if (path === "/api/v1/memories/proposals") {
        return jsonResponse({
          proposals: [],
          total: 0,
          skipped_duplicates: 0,
          filtered_sensitive_count: 0,
        });
      }
      if (path === "/api/v1/memories") return jsonResponse({ items: [], total: 0 });
      return jsonResponse({}, 404);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Cue Studio$/i }));
    expect(
      await screen.findByText(/How do you validate service dependency maps/i),
    ).toBeInTheDocument();

    // 1. Validate empty/short revision instructions and invalid duration override
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    expect(
      await screen.findByText("Enter revision instructions (at least 3 characters)."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Less formal/i }));
    fireEvent.click(screen.getByRole("button", { name: /Duration or tone override/i }));
    fireEvent.change(screen.getByLabelText(/^Minutes$/i), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    expect(
      await screen.findByText("Updated duration must be between 5 and 180 minutes."),
    ).toBeInTheDocument();

    // 2. Clear bad duration and create v2
    fireEvent.change(screen.getByLabelText(/^Minutes$/i), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    expect(await screen.findByText(/Updated to deck v2/i)).toBeInTheDocument();

    // 3. Create v3 using Trim to 15m preset
    fireEvent.click(screen.getByRole("button", { name: /Trim to 15m/i }));
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    expect(await screen.findByText(/Updated to deck v3/i)).toBeInTheDocument();
    expect(screen.getByText(/15-MINUTE RUN OF SHOW/i)).toBeInTheDocument();

    // 4. Inspect v1 archived snapshot and confirm Refine Deck form is locked/hidden
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByText(/Viewing archived snapshot v1/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refine Deck/i })).not.toBeInTheDocument();

    // Return to latest v3 -> Refine Deck reappears
    fireEvent.click(screen.getByRole("button", { name: /Return to latest \(v3\)/i }));
    expect(await screen.findByRole("button", { name: /Refine Deck/i })).toBeInTheDocument();

    // 5. Trigger 409 VERSION_CONFLICT and click Reload Latest Version -> syncs to v4
    forceConflictOnce = true;
    fireEvent.click(screen.getByRole("button", { name: /Career focus/i }));
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    const reloadBtn = await screen.findByRole("button", { name: /Reload Latest Version/i });
    fireEvent.click(reloadBtn);

    expect(await screen.findByRole("button", { name: "v4" })).toBeInTheDocument();
    expect(screen.getByText(/20-MINUTE RUN OF SHOW/i)).toBeInTheDocument();
  });
});
