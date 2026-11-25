import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type {
  AuthClientConfigResponse,
  ContactResponse,
  MeetingResponse,
  MemoryExtractionJobResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
} from "./api/types";

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

function buildBriefFixture(
  overrides?: Partial<PreparationBriefResponse>,
): PreparationBriefResponse {
  return {
    id: "brf_001",
    meeting_id: "mtg_001",
    contact_id: "cnt_alex",
    duration_minutes: 30,
    tone: "warm_casual",
    contact_context: "Alex Morgan is a Staff ML Engineer at Northstar Systems.",
    meeting_objective: "Learn how Alex's team evaluates LLM pipelines in production.",
    conversation_openers: [
      "Thanks for making time, excited to hear what your team has learned scaling evaluation.",
      "How has your quarter at Northstar Systems been shaping up so far?",
    ],
    time_boxed_agenda: [
      {
        title: "Rapport & Context",
        duration_minutes: 5,
        description: "Set a relaxed tone and share why evaluation caught your attention.",
      },
      {
        title: "Evaluation Architecture Deep Dive",
        duration_minutes: 20,
        description: "Explore practical lessons on offline datasets and failure triage.",
      },
      {
        title: "Wrap-Up & Follow-Through",
        duration_minutes: 5,
        description: "Confirm one concrete resource or follow-up takeaway.",
      },
    ],
    suggested_questions: [
      {
        id: "q_1",
        question:
          "Which offline evaluation signals caught real regressions earliest for your team?",
        rationale: "Directly uncovers high-leverage evaluation practices tied to your objective.",
        category: "Evaluation",
      },
      {
        id: "q_2",
        question:
          "Where did engineers push back most when adopting automated quality gates?",
        rationale: "Surfaces realistic organizational adoption trade-offs.",
        category: "Adoption",
      },
      {
        id: "q_3",
        question: "How do you curate golden sets with non-ML domain reviewers?",
        rationale: "Explores practical human-in-the-loop dataset hygiene.",
        category: "Process",
      },
    ],
    suggested_follow_up_topics: [
      "Share summary notes on evaluation dataset design within 48 hours.",
    ],
    referenced_memory_ids: ["mem_001"],
    revision_summary: null,
    version: 1,
    created_at: "2026-11-24T06:05:00Z",
    updated_at: "2026-11-24T06:05:00Z",
    workflow: {
      request_id: "req_1",
      trace_id: "trc_1",
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

interface MockBackendState {
  contacts: ContactResponse[];
  meetings: MeetingResponse[];
  briefsById: Map<string, PreparationBriefResponse>;
  revisionsById: Map<string, PreparationBriefResponse[]>;
  proposals: MemoryProposalResponse[];
  memories: MemoryResponse[];
  extractionJob?: MemoryExtractionJobResponse | null;
  nextCreateContactError?: Response | null;
  nextReviseError?: Response | null;
  forceUnauthorizedOnNextContacts?: boolean;
}

function createStatefulFetchMock(state: MockBackendState) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const rawUrl =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const parsed = new URL(rawUrl, "http://localhost");
    const path = parsed.pathname;
    const method = (init?.method ?? "GET").toUpperCase();

    if (path === "/api/health" && method === "GET") {
      return jsonResponse(HEALTH_OK);
    }
    if (path === "/api/auth/config" && method === "GET") {
      return jsonResponse(LOCAL_AUTH_CONFIG);
    }
    if (path === "/api/auth/mock-session" && method === "POST") {
      return jsonResponse(
        {
          access_token: "mses_test_session_token",
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
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/auth/me" && method === "GET") {
      return jsonResponse({
        user_id: "usr_mock_alice",
        display_name: "Alice Chen",
        auth_provider: "local_mock",
      });
    }

    if (path === "/api/v1/contacts" && method === "GET") {
      if (state.forceUnauthorizedOnNextContacts) {
        state.forceUnauthorizedOnNextContacts = false;
        return jsonResponse(
          {
            error: {
              code: "TOKEN_EXPIRED",
              message: "Authentication token has expired. Please sign in again.",
              trace_id: "trc_expired_01",
              details: [],
            },
          },
          401,
        );
      }
      return jsonResponse({ items: state.contacts, total: state.contacts.length });
    }

    if (path === "/api/v1/contacts" && method === "POST") {
      if (state.nextCreateContactError) {
        const errResp = state.nextCreateContactError;
        state.nextCreateContactError = null;
        return errResp;
      }
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const created: ContactResponse = {
        id: `cnt_${String(state.contacts.length + 1)}`,
        name: String(payload["name"] ?? ""),
        title: typeof payload["title"] === "string" ? payload["title"] : null,
        role: typeof payload["role"] === "string" ? payload["role"] : null,
        organization:
          typeof payload["organization"] === "string" ? payload["organization"] : null,
        context_notes:
          typeof payload["context_notes"] === "string" ? payload["context_notes"] : null,
        version: 1,
        created_at: "2026-11-24T06:01:00Z",
        updated_at: "2026-11-24T06:01:00Z",
      };
      state.contacts = [created, ...state.contacts];
      return jsonResponse(created, 201);
    }

    if (path === "/api/v1/meetings" && method === "GET") {
      const contactId = parsed.searchParams.get("contact_id");
      const items = contactId
        ? state.meetings.filter((m) => m.contact_id === contactId)
        : state.meetings;
      return jsonResponse({ items, total: items.length });
    }

    if (path === "/api/v1/briefs/generate" && method === "POST") {
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const brief = buildBriefFixture({
        contact_id: String(payload["contact_id"]),
        duration_minutes: Number(payload["duration_minutes"] ?? 30),
        meeting_objective: String(payload["meeting_objective"]),
      });
      const meeting: MeetingResponse = {
        id: brief.meeting_id,
        contact_id: brief.contact_id,
        purpose: (payload["purpose"] as MeetingResponse["purpose"]) ?? "coffee_chat",
        tone: brief.tone,
        objective: brief.meeting_objective,
        duration_minutes: brief.duration_minutes,
        scheduled_at:
          typeof payload["scheduled_at"] === "string" ? payload["scheduled_at"] : null,
        notes: null,
        status: "preparing",
        latest_brief_id: brief.id,
        version: 1,
        created_at: "2026-11-24T06:05:00Z",
        updated_at: "2026-11-24T06:05:00Z",
      };
      state.meetings = [meeting, ...state.meetings];
      state.briefsById.set(brief.id, brief);
      state.revisionsById.set(brief.id, [brief]);
      return jsonResponse(brief, 201);
    }

    if (path.startsWith("/api/v1/briefs/") && path.endsWith("/revisions") && method === "GET") {
      const briefId = path.split("/")[4] ?? "";
      const items = state.revisionsById.get(briefId) ?? [];
      return jsonResponse({ items, total: items.length });
    }

    if (path.startsWith("/api/v1/briefs/") && path.endsWith("/revise") && method === "POST") {
      if (state.nextReviseError) {
        const errResp = state.nextReviseError;
        state.nextReviseError = null;
        return errResp;
      }
      const briefId = path.split("/")[4] ?? "";
      const existing = state.briefsById.get(briefId) ?? buildBriefFixture();
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const nextDuration =
        typeof payload["duration_minutes"] === "number"
          ? payload["duration_minutes"]
          : existing.duration_minutes;
      const v2 = buildBriefFixture({
        ...existing,
        duration_minutes: nextDuration,
        time_boxed_agenda: [
          {
            title: "Quick Rapport",
            duration_minutes: 3,
            description: "Warm greeting.",
          },
          {
            title: "Focused Evaluation Questions",
            duration_minutes: nextDuration - 3,
            description: "High-priority discussion.",
          },
        ],
        revision_summary: "Trimmed agenda to 15 minutes.",
        version: existing.version + 1,
      });
      state.briefsById.set(briefId, v2);
      const history = state.revisionsById.get(briefId) ?? [existing];
      state.revisionsById.set(briefId, [...history, v2]);
      return jsonResponse(v2, 200);
    }

    if (path.startsWith("/api/v1/briefs/") && method === "GET") {
      const briefId = path.split("/")[4] ?? "";
      const brief = state.briefsById.get(briefId);
      return brief
        ? jsonResponse(brief)
        : jsonResponse(
            { error: { code: "NOT_FOUND", message: "Not found", trace_id: "t1", details: [] } },
            404,
          );
    }

    if (path === "/api/v1/memories/proposals" && method === "GET") {
      const pending = state.proposals.filter((p) => p.status === "pending");
      return jsonResponse({
        proposals: pending,
        total: pending.length,
        skipped_duplicates: 0,
        filtered_sensitive_count: 0,
      });
    }

    if (path === "/api/v1/memories/extraction-jobs" && method === "POST") {
      const reqBody = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const queuedJob: MemoryExtractionJobResponse = {
        id: "job_extract_1",
        status: "queued",
        contact_id: typeof reqBody["contact_id"] === "string" ? reqBody["contact_id"] : null,
        meeting_id: typeof reqBody["meeting_id"] === "string" ? reqBody["meeting_id"] : null,
        brief_id: typeof reqBody["brief_id"] === "string" ? reqBody["brief_id"] : null,
        result: null,
        error: null,
        created_at: "2026-11-24T06:10:00Z",
        updated_at: "2026-11-24T06:10:00Z",
        completed_at: null,
      };
      state.extractionJob = queuedJob;
      return jsonResponse(queuedJob, 202);
    }

    if (path.startsWith("/api/v1/memories/extraction-jobs/") && method === "GET") {
      const job = state.extractionJob;
      if (!job || path.split("/")[5] !== job.id) {
        return jsonResponse(
          { error: { code: "NOT_FOUND", message: "Not found", trace_id: "t1", details: [] } },
          404,
        );
      }
      const cid = job.contact_id ?? "cnt_alex";
      const p1: MemoryProposalResponse = {
        id: "prop_ai",
        scope: "contact",
        contact_id: cid,
        memory_type: "counterpart_background",
        text: "Alex Morgan discussed his team's challenges adopting AI.",
        rationale: "Useful context for future follow-ups with Alex.",
        source: {
          source_type: "meeting_notes",
          meeting_id: "mtg_001",
          brief_id: "brf_001",
          proposal_id: "prop_ai",
          excerpt: "We discussed his team's challenges adopting AI.",
          recorded_at: "2026-11-24T06:10:00Z",
        },
        status: "pending",
        lifecycle_state: "proposed",
        epistemic_status: "user_reported_observation",
        supersedes_memory_id: "mem_old_pref",
        conflict_summary: "Updates earlier AI adoption note.",
        rejection_reason: null,
        approved_memory_id: null,
        created_at: "2026-11-24T06:10:00Z",
        updated_at: "2026-11-24T06:10:00Z",
        reviewed_at: null,
        version: 1,
      };
      const p2: MemoryProposalResponse = {
        id: "prop_pref",
        scope: "user_preference",
        contact_id: null,
        memory_type: "communication_preference",
        text: "Prefers having informal conversations with engineers.",
        rationale: "Shapes tone of future engineering briefs.",
        source: {
          source_type: "meeting_notes",
          meeting_id: "mtg_001",
          brief_id: "brf_001",
          proposal_id: "prop_pref",
          excerpt: "I prefer having informal conversations with engineers.",
          recorded_at: "2026-11-24T06:10:00Z",
        },
        status: "pending",
        lifecycle_state: "proposed",
        epistemic_status: "user_stated_preference",
        supersedes_memory_id: null,
        conflict_summary: null,
        rejection_reason: null,
        approved_memory_id: null,
        created_at: "2026-11-24T06:10:00Z",
        updated_at: "2026-11-24T06:10:00Z",
        reviewed_at: null,
        version: 1,
      };
      state.proposals = [p1, p2];
      const succeededJob: MemoryExtractionJobResponse = {
        ...job,
        status: "succeeded",
        result: {
          proposals: state.proposals,
          total: 2,
          skipped_duplicates: 1,
          filtered_sensitive_count: 0,
        },
        updated_at: "2026-11-24T06:10:01Z",
        completed_at: "2026-11-24T06:10:01Z",
      };
      state.extractionJob = succeededJob;
      return jsonResponse(succeededJob);
    }

    if (path.startsWith("/api/v1/memories/") && path.endsWith("/approve") && method === "POST") {
      const proposalId = path.split("/")[4] ?? "";
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const target = state.proposals.find((p) => p.id === proposalId);
      if (!target) {
        return jsonResponse(
          { error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } },
          404,
        );
      }
      const finalText =
        typeof payload["edited_text"] === "string" && payload["edited_text"]
          ? payload["edited_text"]
          : target.text;
      const createdMem: MemoryResponse = {
        id: `mem_from_${proposalId}`,
        owner_user_id: "usr_mock_alice",
        scope: target.scope,
        contact_id: target.contact_id,
        memory_type: target.memory_type,
        text: finalText,
        source: target.source,
        consent_status: "approved",
        lifecycle_state: "approved",
        epistemic_status: target.epistemic_status,
        supersedes_memory_id: target.supersedes_memory_id,
        superseded_by_memory_id: null,
        superseded_at: null,
        created_at: "2026-11-24T06:12:00Z",
        updated_at: "2026-11-24T06:12:00Z",
        version: 1,
      };
      state.proposals = state.proposals.map((p) =>
        p.id === proposalId
          ? { ...p, status: "approved", lifecycle_state: "approved", version: 2 }
          : p,
      );
      state.memories = [createdMem, ...state.memories];
      return jsonResponse(createdMem);
    }

    if (path.startsWith("/api/v1/memories/") && path.endsWith("/reject") && method === "POST") {
      const proposalId = path.split("/")[4] ?? "";
      const target = state.proposals.find((p) => p.id === proposalId);
      if (!target) {
        return jsonResponse(
          { error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } },
          404,
        );
      }
      const rejected: MemoryProposalResponse = {
        ...target,
        status: "rejected",
        lifecycle_state: "rejected",
        version: 2,
      };
      state.proposals = state.proposals.map((p) => (p.id === proposalId ? rejected : p));
      return jsonResponse(rejected);
    }

    if (path === "/api/v1/memories" && method === "GET") {
      return jsonResponse({ items: state.memories, total: state.memories.length });
    }

    if (path.startsWith("/api/v1/memories/") && method === "PATCH") {
      const memoryId = path.split("/")[4] ?? "";
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const existing = state.memories.find((m) => m.id === memoryId);
      if (!existing) {
        return jsonResponse(
          { error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } },
          404,
        );
      }
      const updated: MemoryResponse = {
        ...existing,
        text: typeof payload["text"] === "string" ? payload["text"] : existing.text,
        version: existing.version + 1,
      };
      state.memories = state.memories.map((m) => (m.id === memoryId ? updated : m));
      return jsonResponse(updated);
    }

    if (path.startsWith("/api/v1/memories/") && method === "DELETE") {
      const memoryId = path.split("/")[4] ?? "";
      state.memories = state.memories.filter((m) => m.id !== memoryId);
      return new Response(null, { status: 204 });
    }

    return jsonResponse(
      {
        error: {
          code: "NOT_FOUND",
          message: `Unhandled ${method} ${path}`,
          trace_id: "trc_404",
          details: [],
        },
      },
      404,
    );
  });
}

describe("Brew v2 Integration & Feature-Parity Regression Suite", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete window.google;
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("renders sign-in gate cleanly and hides local mock personas in production config", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/health")) {
        return jsonResponse({ ...HEALTH_OK, environment: "production" });
      }
      return jsonResponse({
        auth_mode: "verified",
        environment: "production",
        local_mock_enabled: false,
        google_sign_in_enabled: true,
        firebase: null,
        google_oauth_client_id: "prod-client.apps.googleusercontent.com",
        mock_personas: [],
      } satisfies AuthClientConfigResponse);
    });

    render(<App />);

    const googleBtn = await screen.findByRole("button", { name: /Continue with Google/i });
    await waitFor(() => {
      expect(googleBtn).not.toBeDisabled();
    });
    expect(screen.queryByText(/Local Workspace Personas/i)).not.toBeInTheDocument();
  });

  it("renders graceful offline alert when backend health check fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Connection refused"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
        "Backend connection unavailable",
      );
    });
  });

  it("covers empty states, contact form validation, structured 422 API errors, and 1-click GCal slot prep", async () => {
    const state: MockBackendState = {
      contacts: [],
      meetings: [],
      briefsById: new Map(),
      revisionsById: new Map(),
      proposals: [],
      memories: [],
    };
    createStatefulFetchMock(state);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    // Clubhouse shows local demo GCal slots ("from GCal") right away
    expect((await screen.findAllByText("from GCal")).length).toBeGreaterThan(0);

    // Cue Studio shows empty state before a brief is synthesized
    fireEvent.click(screen.getByRole("button", { name: /^Cue Studio$/i }));
    expect(await screen.findByText(/Synthesize your first cue deck/i)).toBeInTheDocument();

    // Relationship Journal opens New Counterpart modal and validates inputs + 422 API error
    fireEvent.click(screen.getByRole("button", { name: /Relationship Journal/i }));
    await screen.findByRole("heading", { level: 1, name: /Folios & Memory/i });
    fireEvent.click(screen.getByRole("button", { name: /^Person$/i }));

    const dialog = await screen.findByRole("dialog", { name: /New Counterpart/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /Save Counterpart/i }));
    expect(await within(dialog).findByText("Counterpart name is required.")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText(/Full name/i), {
      target: { value: "Alex Morgan" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Background context/i), {
      target: { value: "Hi" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /Save Counterpart/i }));
    expect(
      await within(dialog).findByText(
        "Context notes must be at least 3 characters when provided.",
      ),
    ).toBeInTheDocument();

    state.nextCreateContactError = jsonResponse(
      {
        error: {
          code: "VALIDATION_ERROR",
          message: "Request validation failed.",
          trace_id: "trace_contact_422",
          details: [
            {
              field: "body.organization",
              message: "Organization name rejected by policy.",
              error_type: "value_error",
            },
          ],
        },
      },
      422,
    );

    fireEvent.change(within(dialog).getByLabelText(/Background context/i), {
      target: { value: "Met at the AI systems workshop." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /Save Counterpart/i }));

    expect(
      await within(dialog).findByText(/Organization name rejected by policy/i),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Trace: trace_contact_422/i)).toBeInTheDocument();

    // Retry succeeds and adds Alex Morgan to Relationship Journal folios
    fireEvent.click(within(dialog).getByRole("button", { name: /Save Counterpart/i }));
    expect(
      await screen.findByRole("heading", { level: 2, name: "Alex Morgan" }),
    ).toBeInTheDocument();

    // Also test 1-click Calendar Slot Prep for an uncreated GCal invite ("Priya Nair") -> auto-creates contact + generates deck!
    const nav = screen.getByRole("navigation", { name: /^Primary navigation$/i });
    fireEvent.click(within(nav).getByRole("button", { name: /^Clubhouse$/i }));
    const setup15mBtn = await screen.findByRole("button", { name: /Setup 15m Chat/i });
    fireEvent.click(setup15mBtn);

    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });
    expect(screen.getByLabelText(/Meeting duration/i)).toHaveValue("15");

    fireEvent.change(
      screen.getByLabelText(/What would make this 15-minute chat feel worthwhile/i),
      {
        target: { value: "Learn how Priya bridges Figma tokens with engineering PR checks." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));

    // Enters Cue Studio for newly created Priya Nair with 15-minute Run of Show
    expect(
      await screen.findByRole("heading", { level: 1, name: "Priya Nair" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/15-MINUTE RUN OF SHOW/i)).toBeInTheDocument();
  });

  it("validates brief setup, synthesizes v1, stars Pocket cards, refines to v2, inspects archived v1, and handles 409 conflicts", async () => {
    const state: MockBackendState = {
      contacts: [
        {
          id: "cnt_alex",
          name: "Alex Morgan",
          title: "Staff ML Engineer",
          role: "Peer",
          organization: "Northstar Systems",
          context_notes: "Met at evaluation meetup.",
          version: 1,
          created_at: "2026-11-24T06:00:00Z",
          updated_at: "2026-11-24T06:00:00Z",
        },
      ],
      meetings: [],
      briefsById: new Map(),
      revisionsById: new Map(),
      proposals: [],
      memories: [],
    };
    createStatefulFetchMock(state);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    fireEvent.click(await screen.findByRole("button", { name: /Quick Spark/i }));
    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });

    // Select saved contact Alex Morgan
    fireEvent.change(screen.getByLabelText(/Or saved person/i), {
      target: { value: "cnt_alex" },
    });

    // Objective validation check
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));
    expect(
      await screen.findByText("Enter a meeting objective (at least 3 characters)."),
    ).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText(/What would make this 30-minute chat feel worthwhile/i),
      {
        target: { value: "Learn how Alex's team evaluates production LLM pipelines." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Synthesize Cue Deck/i }));

    expect(
      await screen.findByText(
        /Which offline evaluation signals caught real regressions earliest/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/30-MINUTE RUN OF SHOW/i)).toBeInTheDocument();

    // Star Q3 and open Pocket Glance -> confirm 3 starred cards appear
    fireEvent.click(await screen.findByRole("button", { name: /Tap to star/i }));
    fireEvent.click(screen.getByRole("button", { name: /Pocket Glance/i }));
    expect(await screen.findByText(/STARRED Q1 · 1 OF 3/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Full Studio/i }));

    // Trigger 409 VERSION_CONFLICT on first refinement attempt in Brief Co-Pilot
    state.nextReviseError = jsonResponse(
      {
        error: {
          code: "VERSION_CONFLICT",
          message: "Expected brief version 1, found 2.",
          trace_id: "trace_conflict_409",
          details: [],
        },
      },
      409,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Trim to 15m/i }));
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));

    expect(
      await screen.findByRole("button", { name: /Reload Latest Version/i }),
    ).toBeInTheDocument();

    // Submit refinement cleanly -> creates v2 (15-MINUTE RUN OF SHOW) while preserving v1
    fireEvent.click(screen.getByRole("button", { name: /Refine Deck/i }));
    expect(await screen.findByText(/Updated to deck v2/i)).toBeInTheDocument();
    expect(screen.getByText(/15-MINUTE RUN OF SHOW/i)).toBeInTheDocument();

    // Switch back to historical revision v1 and verify read-only snapshot banner
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByText(/Viewing archived snapshot v1/i)).toBeInTheDocument();
    expect(screen.getByText(/30-MINUTE RUN OF SHOW/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Return to latest \(v2\)/i }));
    expect(await screen.findByText(/15-MINUTE RUN OF SHOW/i)).toBeInTheDocument();
  });

  it("captures post-chat debrief reflections, edits & stamps keepsakes, tosses, and manages folios in Relationship Journal", async () => {
    const state: MockBackendState = {
      contacts: [
        {
          id: "cnt_alex",
          name: "Alex Morgan",
          title: "Staff ML Engineer",
          role: "Engineering Peer",
          organization: "Northstar Systems",
          context_notes: null,
          version: 1,
          created_at: "2026-11-24T06:00:00Z",
          updated_at: "2026-11-24T06:00:00Z",
        },
      ],
      meetings: [],
      briefsById: new Map(),
      revisionsById: new Map(),
      proposals: [],
      memories: [],
    };
    createStatefulFetchMock(state);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    // Open Debrief via Clubhouse wrapped event CTA
    fireEvent.click(await screen.findByRole("button", { name: /Capture Debrief/i }));
    await screen.findByRole("heading", { level: 1, name: /How did it go with Alex/i });

    // Short notes validation error
    fireEvent.change(screen.getByLabelText(/Session reflections/i), {
      target: { value: "Too" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Suggest Keepsakes/i }));
    expect(
      await screen.findByText("Enter at least 5 characters of meeting notes."),
    ).toBeInTheDocument();

    // Submit realistic post-meeting notes
    fireEvent.change(screen.getByLabelText(/Session reflections/i), {
      target: {
        value:
          "We discussed his team's challenges adopting AI. I prefer having informal conversations with engineers.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Suggest Keepsakes/i }));

    // The extraction job runs in the background: the submit button shows progress while polling
    expect(
      await screen.findByRole("button", { name: /Suggesting Keepsakes/i }),
    ).toBeDisabled();

    // Allow for the client's default 1000 ms job poll interval before the batch arrives
    expect(
      await screen.findByText(/2 suggested keepsakes staged/i, undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Updates earlier AI adoption note/i)).toBeInTheDocument();

    // Edit & Stamp Keep on first proposal
    const editButtons = screen.getAllByRole("button", { name: /^Edit$/i });
    const firstProposalEdit = editButtons[0];
    expect(firstProposalEdit).toBeDefined();
    if (firstProposalEdit) {
      fireEvent.click(firstProposalEdit);
    }
    const editBox = await screen.findByLabelText(/Edit keepsake/i);
    fireEvent.change(editBox, {
      target: { value: "Alex highlighted dataset curation as their top AI adoption hurdle." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save & Stamp Keep/i }));
    expect(await screen.findByText(/Keepsake stamped to journal/i)).toBeInTheDocument();

    // Toss second proposal with optional reason
    fireEvent.click(screen.getByRole("button", { name: /^Toss$/i }));
    fireEvent.change(await screen.findByLabelText(/Optional reason to toss/i), {
      target: { value: "Already captured in profile." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Confirm Toss/i }));

    expect(await screen.findByText(/Keepsake tossed/i)).toBeInTheDocument();
    expect(screen.getByText(/No keepsakes awaiting your stamp/i)).toBeInTheDocument();

    // Return to Clubhouse and open Relationship Journal -> verify keepsake, edit, and delete
    fireEvent.click(screen.getByRole("button", { name: /Back to Clubhouse/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Relationship Journal/i }));

    expect(
      await screen.findByText(
        "Alex highlighted dataset curation as their top AI adoption hurdle.",
      ),
    ).toBeInTheDocument();

    const journalEditButtons = screen.getAllByRole("button", { name: /^Edit$/i });
    const cardEditBtn = journalEditButtons.find((b) => b.id.startsWith("btn-edit-memory-"));
    expect(cardEditBtn).toBeDefined();
    if (cardEditBtn) {
      fireEvent.click(cardEditBtn);
    }

    fireEvent.change(await screen.findByLabelText(/Keepsake statement/i), {
      target: { value: "Alex highlighted golden eval sets as their top AI adoption hurdle." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => {
      expect(
        screen.getByText(
          "Alex highlighted golden eval sets as their top AI adoption hurdle.",
        ),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Delete$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Confirm Delete/i }));
    expect(
      await screen.findByText(/No keepsakes stamped for/i),
    ).toBeInTheDocument();
  });

  it("clears expired session and returns to sign-in gate with alert on 401 TOKEN_EXPIRED", async () => {
    const state: MockBackendState = {
      contacts: [],
      meetings: [],
      briefsById: new Map(),
      revisionsById: new Map(),
      proposals: [],
      memories: [],
      forceUnauthorizedOnNextContacts: true,
    };
    createStatefulFetchMock(state);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    await waitFor(() => {
      expect(screen.getByText("Session expired")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Authentication token has expired\. Please sign in again\./i),
    ).toBeInTheDocument();
    expect(window.sessionStorage.getItem("brew.auth.session.v1")).toBeNull();
  });

  it("hides the fallback button once Google Identity Services renders its official button", async () => {
    window.google = {
      accounts: {
        id: {
          initialize: vi.fn(),
          prompt: vi.fn(),
          renderButton: (parent: HTMLElement) => {
            const gisBtn = document.createElement("button");
            gisBtn.type = "button";
            gisBtn.textContent = "Continue with Google";
            parent.appendChild(gisBtn);
          },
        },
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/health")) {
        return jsonResponse(HEALTH_OK);
      }
      return jsonResponse({
        ...LOCAL_AUTH_CONFIG,
        google_sign_in_enabled: true,
        google_oauth_client_id: "local-client.apps.googleusercontent.com",
      } satisfies AuthClientConfigResponse);
    });

    render(<App />);
    await waitFor(() => {
      expect(document.getElementById("btn-google-sign-in")).toBeNull();
    });
    const googleButtons = screen.getAllByRole("button", { name: /Continue with Google/i });
    expect(googleButtons).toHaveLength(1);
  });
});
