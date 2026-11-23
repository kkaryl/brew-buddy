import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BrewApiClient, BrewApiError } from "./api/client";
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

function createDeferred<T>() {
  let resolveFn: (value: T) => void = () => {};
  let rejectFn: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolve, reject) => {
    resolveFn = resolve;
    rejectFn = reject;
  });
  return { promise, resolve: resolveFn, reject: rejectFn };
}

const HEALTH_OK = {
  status: "ok",
  service: "brew",
  version: "0.1.0",
  environment: "local",
  model: "gemini-3.8-flash",
  timestamp_utc: "2026-11-23T07:00:00Z",
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
      "Thanks for carving out time—excited to learn how CloudScale runs failover drills.",
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
    created_at: "2026-11-23T07:05:00Z",
    updated_at: "2026-11-23T07:05:00Z",
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

describe("Brew Test Pyramid — Frontend Journeys, States, Memory Governance, and Revisions", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("1. User journey: multi-counterpart creation, advanced preferences brief, session switching, and sign-out", async () => {
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
          created_at: "2026-11-23T07:01:00Z",
          updated_at: "2026-11-23T07:01:00Z",
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
          created_at: "2026-11-23T07:05:00Z",
          updated_at: "2026-11-23T07:05:00Z",
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

    // Add first counterpart via empty-state CTA
    fireEvent.click(await screen.findByRole("button", { name: /New Counterpart/i }));
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
    await screen.findByRole("heading", { level: 1, name: "Maya Lin" });

    // Generate Brief #1 with advanced preferences expanded
    fireEvent.click(screen.getByRole("button", { name: /Mentorship/i }));
    fireEvent.click(screen.getByRole("button", { name: /Add session notes or preferences/i }));
    fireEvent.change(screen.getByLabelText(/Question count/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/Focus areas/i), {
      target: { value: "incident reviews, game days" },
    });
    fireEvent.change(screen.getByLabelText(/Personal coaching style notes/i), {
      target: { value: "Prefer concrete engineering stories." },
    });
    fireEvent.change(screen.getByLabelText(/Meeting objective/i), {
      target: { value: "Learn how Maya scales multi-region failover drills." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));

    expect(
      await screen.findByText(/How do you validate service dependency maps/i),
    ).toBeInTheDocument();
    expect(capturedGenerateBody).not.toBeNull();
    expect(capturedGenerateBody?.["preferences"]).toEqual({
      preferred_question_count: 4,
      communication_style_notes: "Prefer concrete engineering stories.",
      focus_areas: ["incident reviews", "game days"],
    });

    // Generate a second meeting brief for Maya and verify session switcher appears
    fireEvent.click(screen.getByRole("button", { name: /New Meeting Brief/i }));
    fireEvent.click(screen.getByRole("button", { name: /15m/i }));
    fireEvent.change(screen.getByLabelText(/Meeting objective/i), {
      target: { value: "Quick 15m follow-up on dependency graphs." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));
    await waitFor(() => {
      expect(screen.queryByLabelText(/Meeting objective/i)).not.toBeInTheDocument();
      expect(
        screen.getByText("Quick 15m follow-up on dependency graphs."),
      ).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Recent meetings")).toBeInTheDocument();

    // Add second counterpart and switch between them in the navigation rail
    fireEvent.click(screen.getByRole("button", { name: /^\+ Add$/i }));
    const dialog2 = await screen.findByRole("dialog", { name: /New Counterpart/i });
    fireEvent.change(within(dialog2).getByLabelText(/Full name/i), {
      target: { value: "Dr. Samir Patel" },
    });
    fireEvent.click(within(dialog2).getByRole("button", { name: /Save Counterpart/i }));
    await screen.findByRole("heading", { level: 1, name: "Dr. Samir Patel" });

    // Switch back to Maya Lin from rail
    fireEvent.click(screen.getByRole("button", { name: /Maya Lin/i }));
    await screen.findByRole("heading", { level: 1, name: "Maya Lin" });

    // Sign out cleanly and confirm session clearance
    const signOutButtons = screen.getAllByRole("button", { name: /Sign out/i });
    const primarySignOut = signOutButtons[0];
    expect(primarySignOut).toBeDefined();
    if (primarySignOut) {
      fireEvent.click(primarySignOut);
    }
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
              created_at: "2026-11-23T07:00:00Z",
              updated_at: "2026-11-23T07:00:00Z",
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
    await screen.findByRole("heading", { name: "Prepare a Conversation Brief" });

    fireEvent.change(screen.getByLabelText(/Meeting objective/i), {
      target: { value: "Explore regional failover drills with Maya." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));

    // Assert live in-flight loading state disables submit button
    const inFlightBtn = await screen.findByRole("button", { name: /Synthesizing Brief\.\.\./i });
    expect(inFlightBtn).toBeDisabled();

    // Resolve first attempt with a structured 504 MODEL_TIMEOUT error
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

    // Retry succeeds with degraded context fallback banner visible
    fireEvent.click(screen.getByRole("button", { name: /Generate Preparation Brief/i }));
    expect(
      await screen.findByText(/Generated with partial context fallback \(meeting_history\)/i),
    ).toBeInTheDocument();

    // Also verify BrewApiClient translates browser AbortError directly into REQUEST_TIMEOUT BrewApiError
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

  it("3. Memory approval & deletion: supersession approval, scope tabs, superseded history toggle, and cancel/confirm deletion", async () => {
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
    await screen.findByRole("heading", { level: 1, name: "Maya Lin" });

    // Open Notes & Review, validate edit guard (<3 chars), then approve superseding proposal
    fireEvent.click(screen.getByRole("button", { name: /^Notes & Review/i }));
    expect(
      await screen.findByText(/Supersedes earlier manual dependency mapping note/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Edit$/i }));
    const editArea = await screen.findByLabelText(/Edit memory text before saving/i);
    fireEvent.change(editArea, { target: { value: "No" } });
    fireEvent.click(screen.getByRole("button", { name: /Approve Edited Memory/i }));
    expect(
      await screen.findByText("Memory text must be at least 3 characters."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));
    expect(
      await screen.findByText(/marked the previous conflicting entry as superseded/i),
    ).toBeInTheDocument();

    // Navigate to Relationship Memory vault and verify scope tabs + superseded toggle + delete
    fireEvent.click(screen.getByRole("button", { name: /^Relationship Memory/i }));
    expect(
      await screen.findByText(
        "In Nov 23 notes, Maya Lin shifted focus from manual dependency maps to automated service-mesh discovery.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("In Nov 2 notes, Maya Lin mentioned manual dependency maps slowed Q3 drills."),
    ).not.toBeInTheDocument();

    // Filter to Personal Preferences tab
    fireEvent.click(screen.getByRole("tab", { name: /Personal Preferences/i }));
    expect(
      screen.getByText("User preference: Prefers informal engineering chats."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "In Nov 23 notes, Maya Lin shifted focus from manual dependency maps to automated service-mesh discovery.",
      ),
    ).not.toBeInTheDocument();

    // Return to All tab and enable Show superseded history
    fireEvent.click(screen.getByRole("tab", { name: /^All/i }));
    fireEvent.click(screen.getByLabelText(/Show superseded history/i));
    expect(
      await screen.findByText(
        "In Nov 2 notes, Maya Lin mentioned manual dependency maps slowed Q3 drills.",
      ),
    ).toBeInTheDocument();
    expect(sawIncludeSupersededQuery).toBe(true);

    // Cancel delete first, then Confirm Delete on preference memory
    const deleteButtons = screen.getAllByRole("button", { name: /^Delete$/i });
    const targetDeleteBtn = deleteButtons[deleteButtons.length - 1];
    expect(targetDeleteBtn).toBeDefined();
    if (targetDeleteBtn) {
      fireEvent.click(targetDeleteBtn);
    }
    fireEvent.click(await screen.findByRole("button", { name: /^Cancel$/i }));
    expect(
      screen.getByText("User preference: Prefers informal engineering chats."),
    ).toBeInTheDocument();

    const retryDeleteButtons = screen.getAllByRole("button", { name: /^Delete$/i });
    const confirmTargetBtn = retryDeleteButtons[retryDeleteButtons.length - 1];
    if (confirmTargetBtn) {
      fireEvent.click(confirmTargetBtn);
    }
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
    expect(
      await screen.findByText(/How do you validate service dependency maps/i),
    ).toBeInTheDocument();

    // 1. Validate empty/short revision instructions and invalid duration override
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    expect(
      await screen.findByText("Enter revision instructions (at least 3 characters)."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Less formal tone/i }));
    fireEvent.change(screen.getByLabelText(/Optional duration override/i), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    expect(
      await screen.findByText("Updated duration must be between 5 and 180 minutes."),
    ).toBeInTheDocument();

    // 2. Clear bad duration and create v2 (Warm & Casual)
    fireEvent.change(screen.getByLabelText(/Optional duration override/i), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    expect(await screen.findByText("Updated to revision v2")).toBeInTheDocument();

    // 3. Create v3 using 15-minute trim preset
    fireEvent.click(screen.getByRole("button", { name: /15-minute trim/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    expect(await screen.findByText("Updated to revision v3")).toBeInTheDocument();
    expect(screen.getByText("15 min")).toBeInTheDocument();

    // 4. Inspect v1 archived snapshot and confirm Refine Brief composer is hidden (immutable)
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByText(/Viewing archived snapshot v1/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Refine Brief" })).not.toBeInTheDocument();

    // Return to latest v3 -> composer reappears
    fireEvent.click(screen.getByRole("button", { name: /Return to latest \(v3\)/i }));
    expect(await screen.findByRole("heading", { name: "Refine Brief" })).toBeInTheDocument();

    // 5. Trigger 409 VERSION_CONFLICT and click Reload Latest Version -> syncs to v4
    forceConflictOnce = true;
    fireEvent.click(screen.getByRole("button", { name: /Customer discovery/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save New Revision/i }));
    const reloadBtn = await screen.findByRole("button", { name: /Reload Latest Version/i });
    fireEvent.click(reloadBtn);

    expect(await screen.findByText(/Synced external v4 revision/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v4" })).toBeInTheDocument();
  });
});
