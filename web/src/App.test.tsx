import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type {
  AuthClientConfigResponse,
  ContactResponse,
  MeetingResponse,
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
  timestamp_utc: "2026-11-23T02:00:00Z",
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
      role_summary: "Product Lead — Isolated Local Workspace",
    },
  ],
};

function buildBriefFixture(overrides?: Partial<PreparationBriefResponse>): PreparationBriefResponse {
  return {
    id: "brf_001",
    meeting_id: "mtg_001",
    contact_id: "cnt_alex",
    duration_minutes: 30,
    tone: "warm_casual",
    contact_context: "Alex Morgan is a Staff ML Engineer at Northstar Systems.",
    meeting_objective: "Learn how Alex's team evaluates LLM pipelines in production.",
    conversation_openers: [
      "Thanks for making time—excited to hear what your team has learned scaling evaluation.",
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
        question: "Which offline evaluation signals caught real regressions earliest for your team?",
        rationale: "Directly uncovers high-leverage evaluation practices tied to your objective.",
        category: "Evaluation",
      },
      {
        id: "q_2",
        question: "Where did engineers push back most when adopting automated quality gates?",
        rationale: "Surfaces realistic organizational adoption trade-offs.",
        category: "Adoption",
      },
    ],
    suggested_follow_up_topics: [
      "Share summary notes on evaluation dataset design within 48 hours.",
    ],
    referenced_memory_ids: ["mem_001"],
    revision_summary: null,
    version: 1,
    created_at: "2026-11-23T02:05:00Z",
    updated_at: "2026-11-23T02:05:00Z",
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
  nextCreateContactError?: Response | null;
  nextReviseError?: Response | null;
  forceUnauthorizedOnNextContacts?: boolean;
}

function createStatefulFetchMock(state: MockBackendState) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
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
        id: "cnt_alex",
        name: String(payload["name"] ?? ""),
        title: typeof payload["title"] === "string" ? payload["title"] : null,
        role: typeof payload["role"] === "string" ? payload["role"] : null,
        organization:
          typeof payload["organization"] === "string" ? payload["organization"] : null,
        context_notes:
          typeof payload["context_notes"] === "string" ? payload["context_notes"] : null,
        version: 1,
        created_at: "2026-11-23T02:01:00Z",
        updated_at: "2026-11-23T02:01:00Z",
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
        scheduled_at: null,
        notes: null,
        status: "preparing",
        latest_brief_id: brief.id,
        version: 1,
        created_at: "2026-11-23T02:05:00Z",
        updated_at: "2026-11-23T02:05:00Z",
      };
      state.meetings = [meeting];
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
      return brief ? jsonResponse(brief) : jsonResponse({ error: { code: "NOT_FOUND", message: "Not found", trace_id: "t1", details: [] } }, 404);
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

    if (path === "/api/v1/memories/propose" && method === "POST") {
      const p1: MemoryProposalResponse = {
        id: "prop_ai",
        scope: "contact",
        contact_id: "cnt_alex",
        memory_type: "counterpart_background",
        text: "Alex Morgan discussed his team's challenges adopting AI.",
        rationale: "Useful context for future follow-ups with Alex.",
        source: {
          source_type: "meeting_notes",
          meeting_id: "mtg_001",
          brief_id: "brf_001",
          proposal_id: "prop_ai",
          excerpt: "We discussed his team's challenges adopting AI.",
          recorded_at: "2026-11-23T02:10:00Z",
        },
        status: "pending",
        lifecycle_state: "proposed",
        epistemic_status: "user_reported_observation",
        supersedes_memory_id: "mem_old_pref",
        conflict_summary: "Updates earlier AI adoption note.",
        rejection_reason: null,
        approved_memory_id: null,
        created_at: "2026-11-23T02:10:00Z",
        updated_at: "2026-11-23T02:10:00Z",
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
          recorded_at: "2026-11-23T02:10:00Z",
        },
        status: "pending",
        lifecycle_state: "proposed",
        epistemic_status: "user_stated_preference",
        supersedes_memory_id: null,
        conflict_summary: null,
        rejection_reason: null,
        approved_memory_id: null,
        created_at: "2026-11-23T02:10:00Z",
        updated_at: "2026-11-23T02:10:00Z",
        reviewed_at: null,
        version: 1,
      };
      state.proposals = [p1, p2];
      return jsonResponse(
        {
          proposals: state.proposals,
          total: 2,
          skipped_duplicates: 1,
          filtered_sensitive_count: 0,
        },
        201,
      );
    }

    if (path.startsWith("/api/v1/memories/") && path.endsWith("/approve") && method === "POST") {
      const proposalId = path.split("/")[4] ?? "";
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const target = state.proposals.find((p) => p.id === proposalId);
      if (!target) {
        return jsonResponse({ error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } }, 404);
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
        created_at: "2026-11-23T02:12:00Z",
        updated_at: "2026-11-23T02:12:00Z",
        version: 1,
      };
      state.proposals = state.proposals.map((p) =>
        p.id === proposalId ? { ...p, status: "approved", lifecycle_state: "approved", version: 2 } : p,
      );
      state.memories = [createdMem, ...state.memories];
      return jsonResponse(createdMem);
    }

    if (path.startsWith("/api/v1/memories/") && path.endsWith("/reject") && method === "POST") {
      const proposalId = path.split("/")[4] ?? "";
      const target = state.proposals.find((p) => p.id === proposalId);
      if (!target) {
        return jsonResponse({ error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } }, 404);
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
        return jsonResponse({ error: { code: "NOT_FOUND", message: "Missing", trace_id: "t", details: [] } }, 404);
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
      { error: { code: "NOT_FOUND", message: `Unhandled ${method} ${path}`, trace_id: "trc_404", details: [] } },
      404,
    );
  });
}

describe("Brew complete user experience", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("renders sign-in gate with runtime readiness and hides local mock personas in production config", async () => {
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

    await waitFor(() => {
      expect(screen.getByText("Backend OK")).toBeInTheDocument();
    });
    expect(screen.getByText(/gemini-3\.8-flash/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue with Google/i })).toBeInTheDocument();
    expect(screen.queryByText(/Local Isolated Test Mode/i)).not.toBeInTheDocument();
  });

  it("renders graceful offline alert when backend health check fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Connection refused"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Backend connection unavailable");
    });
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("covers empty states, contact form validation, and structured API error details", async () => {
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

    const enterAliceBtn = await screen.findByRole("button", { name: /Continue as Alice Chen/i });
    fireEvent.click(enterAliceBtn);

    // Empty counterpart state
    await waitFor(() => {
      expect(screen.getByText("Add a counterpart to begin")).toBeInTheDocument();
    });

    // Empty review queue & empty memory vault states
    fireEvent.click(screen.getByRole("button", { name: /^Notes & Review$/i }));
    expect(await screen.findByText("No pending memory proposals")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Relationship Memory$/i }));
    expect(await screen.findByText("No approved memories yet")).toBeInTheDocument();

    // Open New Counterpart modal and test client-side validation
    fireEvent.click(screen.getByRole("button", { name: /^\+ Add$/i }));
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
      await within(dialog).findByText("Context notes must be at least 3 characters when provided."),
    ).toBeInTheDocument();

    // Inject structured backend 422 error with trace ID and field details
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

    expect(await within(dialog).findByText(/Organization name rejected by policy/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Trace: trace_contact_422/i)).toBeInTheDocument();

    // Retry succeeds and transitions to Prepare workspace for Alex Morgan
    fireEvent.click(within(dialog).getByRole("button", { name: /Save Counterpart/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "Alex Morgan" })).toBeInTheDocument();
    });
  });

  it("validates brief generation, synthesizes v1, refines to v2, inspects historical v1, and handles version conflicts", async () => {
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
          created_at: "2026-11-23T02:00:00Z",
          updated_at: "2026-11-23T02:00:00Z",
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

    await screen.findByRole("heading", { name: "Prepare a Conversation Brief" });

    // Objective validation check
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));
    expect(
      await screen.findByText("Enter a meeting objective (at least 3 characters)."),
    ).toBeInTheDocument();

    // Fill objective and generate brief v1
    fireEvent.change(screen.getByLabelText(/Meeting objective/i), {
      target: { value: "Learn how Alex's team evaluates production LLM pipelines." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));

    expect(
      await screen.findByText(/Which offline evaluation signals caught real regressions/i),
    ).toBeInTheDocument();
    expect(screen.getByText("30 min")).toBeInTheDocument();

    // Trigger 409 VERSION_CONFLICT on first refinement attempt
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
    fireEvent.click(screen.getByRole("button", { name: /15-minute trim/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));

    expect(await screen.findByRole("button", { name: /Reload Latest Version/i })).toBeInTheDocument();

    // Submit refinement cleanly -> creates v2 (15 min) while preserving v1
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    expect(await screen.findByText("Updated to revision v2")).toBeInTheDocument();
    expect(screen.getByText("15 min")).toBeInTheDocument();

    // Switch back to historical revision v1 and verify read-only snapshot banner
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByText(/Viewing archived snapshot/i)).toBeInTheDocument();
    expect(screen.getByText("30 min")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Return to latest \(v2\)/i }));
    expect(await screen.findByText("15 min")).toBeInTheDocument();
  });

  it("proposes memories from notes, edits & approves, rejects, and manages durable memories", async () => {
    const state: MockBackendState = {
      contacts: [
        {
          id: "cnt_alex",
          name: "Alex Morgan",
          title: "Staff ML Engineer",
          role: null,
          organization: "Northstar Systems",
          context_notes: null,
          version: 1,
          created_at: "2026-11-23T02:00:00Z",
          updated_at: "2026-11-23T02:00:00Z",
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
    await screen.findByRole("heading", { level: 1, name: "Alex Morgan" });

    fireEvent.click(screen.getByRole("button", { name: /Log Post-Meeting Notes/i }));
    await screen.findByRole("heading", { level: 1, name: /Post-Meeting Notes & Review/i });

    // Short notes validation error
    fireEvent.change(screen.getByLabelText(/Meeting reflections/i), {
      target: { value: "Too" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Propose Memory Candidates/i }));
    expect(
      await screen.findByText("Enter at least 5 characters of meeting notes."),
    ).toBeInTheDocument();

    // Submit realistic post-meeting notes
    fireEvent.change(screen.getByLabelText(/Meeting reflections/i), {
      target: {
        value:
          "We discussed his team's challenges adopting AI. I prefer having informal conversations with engineers.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Propose Memory Candidates/i }));

    expect(
      await screen.findByText(/2 memory proposals staged for review/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Updates earlier AI adoption note/i)).toBeInTheDocument();

    // Edit & approve first proposal
    const editButtons = screen.getAllByRole("button", { name: /^Edit$/i });
    const firstEditBtn = editButtons[0];
    expect(firstEditBtn).toBeDefined();
    if (firstEditBtn) {
      fireEvent.click(firstEditBtn);
    }
    const editBox = await screen.findByLabelText(/Edit memory text before saving/i);
    fireEvent.change(editBox, {
      target: { value: "Alex highlighted dataset curation as their top AI adoption hurdle." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Approve Edited Memory/i }));

    expect(await screen.findByText("Memory approved")).toBeInTheDocument();

    // Reject second proposal with reason
    fireEvent.click(screen.getByRole("button", { name: /^Reject$/i }));
    fireEvent.change(await screen.findByLabelText(/Optional rejection note/i), {
      target: { value: "Already captured in profile." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Confirm Reject/i }));

    expect(await screen.findByText("Proposal rejected")).toBeInTheDocument();
    expect(screen.getByText("No pending memory proposals")).toBeInTheDocument();

    // Verify approved memory in Relationship Memory vault, edit it, then delete it
    fireEvent.click(screen.getByRole("button", { name: /^Relationship Memory/i }));
    expect(
      await screen.findByText(
        "Alex highlighted dataset curation as their top AI adoption hurdle.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Edit$/i }));
    fireEvent.change(await screen.findByLabelText(/Memory statement/i), {
      target: { value: "Alex highlighted golden eval sets as their top AI adoption hurdle." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => {
      expect(screen.queryByLabelText(/Memory statement/i)).not.toBeInTheDocument();
      expect(
        screen.getByText(
          "Alex highlighted golden eval sets as their top AI adoption hurdle.",
        ),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Delete$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Confirm Delete/i }));
    expect(await screen.findByText("No approved memories yet")).toBeInTheDocument();
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

    try {
      render(<App />);
      await waitFor(() => {
        expect(screen.getByText("Backend OK")).toBeInTheDocument();
      });
      await waitFor(() => {
        expect(document.getElementById("btn-google-sign-in")).toBeNull();
      });
      const googleButtons = screen.getAllByRole("button", { name: /Continue with Google/i });
      expect(googleButtons).toHaveLength(1);
    } finally {
      delete window.google;
    }
  });
});
