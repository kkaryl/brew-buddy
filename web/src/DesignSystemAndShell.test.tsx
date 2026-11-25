import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type {
  AuthClientConfigResponse,
  ContactResponse,
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

function makeSampleBrief(contactId: string): PreparationBriefResponse {
  return {
    id: "brf_design_1",
    meeting_id: "mtg_design_1",
    contact_id: contactId,
    duration_minutes: 30,
    tone: "warm_casual",
    contact_context: "Maya Lin leads reliability engineering at CloudScale.",
    meeting_objective: "Understand multi-region failover game days.",
    conversation_openers: [
      "Last time we chatted you were moving off manual dependency maps. How has the rollout felt?",
      "Thanks for carving out half an hour between Q4 game days.",
    ],
    time_boxed_agenda: [
      { title: "Warm Rapport", duration_minutes: 5, description: "Reconnect warmly." },
      { title: "Game-Day Architecture", duration_minutes: 20, description: "Explore blast-radius checks." },
      { title: "Close", duration_minutes: 5, description: "Offer checklist swap." },
    ],
    suggested_questions: [
      {
        id: "q_1",
        question: "How do you validate live service dependency graphs before a regional drain?",
        rationale: "Surfaces concrete pre-flight safety checks.",
        category: "Architecture",
      },
      {
        id: "q_2",
        question: "Which post-game-day ritual changed how product teams build fallbacks?",
        rationale: "Connects drills to durable behavior.",
        category: "Team Culture",
      },
      {
        id: "q_3",
        question: "What is the smallest abort signal that halts a failover drill immediately?",
        rationale: "Clarifies operational guardrails.",
        category: "Blast Radius",
      },
    ],
    suggested_follow_up_topics: ["Offer evaluation dataset rubric swap within 48h."],
    referenced_memory_ids: [],
    revision_summary: null,
    version: 1,
    created_at: "2026-11-24T06:05:00Z",
    updated_at: "2026-11-24T06:05:00Z",
    workflow: null,
  };
}

function setupMockWorkspace(
  contacts: readonly ContactResponse[],
  withBrief: boolean = false,
) {
  const sampleBrief = contacts[0] ? makeSampleBrief(contacts[0].id) : null;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
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
          access_token: "mses_design_tok",
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
    if (path === "/api/v1/contacts" && method === "GET") {
      return jsonResponse({ items: contacts, total: contacts.length });
    }
    if (path === "/api/v1/meetings") {
      if (withBrief && sampleBrief && contacts[0]) {
        return jsonResponse({
          items: [
            {
              id: sampleBrief.meeting_id,
              contact_id: contacts[0].id,
              purpose: "coffee_chat",
              tone: "warm_casual",
              objective: sampleBrief.meeting_objective,
              duration_minutes: 30,
              scheduled_at: null,
              notes: null,
              status: "preparing",
              latest_brief_id: sampleBrief.id,
              version: 1,
              created_at: "2026-11-24T06:05:00Z",
              updated_at: "2026-11-24T06:05:00Z",
            },
          ],
          total: 1,
        });
      }
      return jsonResponse({ items: [], total: 0 });
    }
    if (path === "/api/v1/briefs/brf_design_1/revisions" && sampleBrief) {
      return jsonResponse({ items: [sampleBrief], total: 1 });
    }
    if (path === "/api/v1/briefs/brf_design_1" && sampleBrief) {
      return jsonResponse(sampleBrief);
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
}

async function assertNoSeriousAxeViolations(container: HTMLElement): Promise<void> {
  const results = await axe.run(container, {
    rules: {
      // jsdom does not compute layout pixel color backgrounds on CSS gradients
      "color-contrast": { enabled: false },
    },
  });
  const blocking = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  expect(blocking).toEqual([]);
}

describe("Brew v2 Design System, 3-Space Shell, Illustrations, Accessibility, and Focused Rituals", () => {
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

  it("renders brew. wordmark, 3-space navigation, mobile dock, and passes automated axe checks across all v2 screens", async () => {
    setupMockWorkspace(
      [
        {
          id: "cnt_maya",
          name: "Maya Lin",
          title: "Principal SRE",
          role: "Engineering Peer",
          organization: "CloudScale",
          context_notes: "Connected at SREcon workshop",
          version: 1,
          created_at: "2026-11-23T12:00:00Z",
          updated_at: "2026-11-23T12:00:00Z",
        },
      ],
      true,
    );

    const { container } = render(<App />);

    // 1. Sign-In Gate check + axe audit
    const signInHeroImg = await screen.findByAltText(
      /Two friendly professionals chatting warmly across an open pale ivory laptop/i,
    );
    expect(signInHeroImg).toHaveAttribute("src", expect.stringContaining("chat-setup-hero"));
    await assertNoSeriousAxeViolations(container);

    // Sign in as Alice Chen -> enters Clubhouse
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));
    await screen.findByRole("heading", { level: 1, name: /Maya Lin/i });

    // Verify 3-space navigation (Clubhouse, Cue Studio, Relationship Journal) & zero noisy status badges
    const primaryNav = screen.getByRole("navigation", { name: /^Primary navigation$/i });
    expect(primaryNav).toBeInTheDocument();
    expect(within(primaryNav).getByRole("button", { name: /^Clubhouse$/i })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(primaryNav).getByRole("button", { name: /^Cue Studio$/i })).toBeInTheDocument();
    expect(
      within(primaryNav).getByRole("button", { name: /Relationship Journal/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /^Mobile dock$/i })).toBeInTheDocument();
    expect(screen.queryByText(/GCal Sync/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Coaching DNA/i)).not.toBeInTheDocument();
    await assertNoSeriousAxeViolations(container);

    // 2. Cue Studio screen + cue-studio-copilot illustration + Pocket Glance starring
    fireEvent.click(within(primaryNav).getByRole("button", { name: /^Cue Studio$/i }));
    await screen.findByRole("heading", { level: 1, name: "Maya Lin" });
    expect(
      screen.getByAltText(/Friendly conversation co-pilot holding starred pale ivory cue cards/i),
    ).toBeInTheDocument();
    await assertNoSeriousAxeViolations(container);

    // 3. Focused Pocket Cue Cards hides primary 3-space nav and renders starred cards
    fireEvent.click(screen.getByRole("button", { name: /Pocket Glance/i }));
    await screen.findByText("POCKET CUE CARDS");
    expect(screen.queryByRole("navigation", { name: /Primary navigation/i })).not.toBeInTheDocument();
    expect(screen.getByText(/STARRED Q1 · 1 OF 2/i)).toBeInTheDocument();
    await assertNoSeriousAxeViolations(container);

    // Return to Full Studio, then open Wrap & Debrief
    fireEvent.click(screen.getByRole("button", { name: /Full Studio/i }));
    await screen.findByRole("heading", { level: 1, name: "Maya Lin" });

    // 4. Focused Debrief screen + debrief-keepsake-journal illustration
    fireEvent.click(screen.getByRole("button", { name: /Wrap & Debrief/i }));
    await screen.findByRole("heading", { level: 1, name: /How did it go with Maya/i });
    expect(screen.queryByRole("navigation", { name: /Primary navigation/i })).not.toBeInTheDocument();
    expect(
      screen.getAllByAltText(/Smiling woman writing reflections into an open pastel journal/i)
        .length,
    ).toBeGreaterThan(0);
    await assertNoSeriousAxeViolations(container);

    // Return via Back to Clubhouse, then open Relationship Journal
    fireEvent.click(screen.getByRole("button", { name: /Back to Clubhouse/i }));
    fireEvent.click(await screen.findByRole("button", { name: /Relationship Journal/i }));
    await screen.findByRole("heading", { level: 1, name: /Folios & Memory/i });
    await assertNoSeriousAxeViolations(container);
  });

  it("omits primary navigation during Conversation Setup, uses 'Synthesize Cue Deck', and omits removed v1 setup boxes", async () => {
    setupMockWorkspace([
      {
        id: "cnt_alex",
        name: "Alex Morgan",
        title: "Staff ML Engineer",
        role: "Peer",
        organization: "Northstar Systems",
        context_notes: "Introduced at conference",
        version: 1,
        created_at: "2026-11-23T12:00:00Z",
        updated_at: "2026-11-23T12:00:00Z",
      },
    ]);

    const { container } = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));
    await screen.findByRole("button", { name: /Quick Spark/i });

    fireEvent.click(screen.getByRole("button", { name: /Quick Spark/i }));
    await screen.findByRole("heading", { level: 1, name: /Shape your conversation/i });

    // Primary nav and mobile dock must be omitted in focused setup
    expect(
      screen.queryByRole("navigation", { name: /^Primary navigation$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /^Mobile dock$/i }),
    ).not.toBeInTheDocument();

    // Approved v2 refinements: "Synthesize Cue Deck" CTA, zero "How you connected" or "Your coaching style" boxes
    expect(screen.getByRole("button", { name: /Synthesize Cue Deck/i })).toBeInTheDocument();
    expect(screen.queryByText(/HOW YOU CONNECTED/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/YOUR COACHING STYLE/i)).not.toBeInTheDocument();
    await assertNoSeriousAxeViolations(container);

    // Back to Clubhouse restores primary navigation
    fireEvent.click(screen.getByRole("button", { name: /Back to Clubhouse/i }));
    expect(
      await screen.findByRole("navigation", { name: /Primary navigation/i }),
    ).toBeInTheDocument();
  });

  it("persists personal coaching style defaults in Relationship Journal and pre-fills new conversation setup", async () => {
    setupMockWorkspace([
      {
        id: "cnt_alex",
        name: "Alex Morgan",
        title: "Staff ML Engineer",
        role: "Peer",
        organization: "Northstar Systems",
        context_notes: null,
        version: 1,
        created_at: "2026-11-23T12:00:00Z",
        updated_at: "2026-11-23T12:00:00Z",
      },
    ]);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));

    // Open Coaching Style folio via header lavender avatar
    fireEvent.click(
      await screen.findByRole("button", { name: /Account and coaching style for Alice Chen/i }),
    );
    await screen.findByRole("heading", { name: /My Coaching Style \(Alice Chen\)/i });

    fireEvent.click(screen.getByRole("button", { name: "45m" }));
    fireEvent.change(screen.getByLabelText(/Default conversation tone/i), {
      target: { value: "candid_coaching" },
    });
    fireEvent.change(screen.getByLabelText(/Personal communication style note/i), {
      target: { value: "Prefer candid stories over generic advice." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save Defaults/i }));

    expect(await screen.findByText(/Defaults saved for future chats/i)).toBeInTheDocument();

    // Start ad-hoc Quick Spark for saved person -> verify 45m & Candid Coaching pre-selected
    fireEvent.click(screen.getByRole("button", { name: /Quick Spark/i }));
    fireEvent.change(await screen.findByLabelText(/Or saved person/i), {
      target: { value: "cnt_alex" },
    });
    expect(screen.getByLabelText(/Conversation tone/i)).toHaveValue("candid_coaching");
  });

  it("opens interactive Google OAuth 2.0 popup on click and surfaces origin_mismatch guidance when misconfigured", async () => {
    let nextOAuthResponse: { access_token?: string; expires_in?: number; error?: string } = {
      error: "origin_mismatch",
    };

    window.google = {
      accounts: {
        oauth2: {
          initTokenClient: (cfg) => ({
            requestAccessToken: () => {
              cfg.callback(nextOAuthResponse);
            },
          }),
        },
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") {
        return jsonResponse({
          ...LOCAL_AUTH_CONFIG,
          google_sign_in_enabled: true,
          google_oauth_client_id: "987654321-web.apps.googleusercontent.com",
        } satisfies AuthClientConfigResponse);
      }
      if (path === "/api/v1/auth/me") {
        return jsonResponse({
          user_id: "google:112233445566",
          display_name: "Kary Long",
          auth_provider: "verified",
        });
      }
      if (path === "/api/v1/contacts") return jsonResponse({ items: [], total: 0 });
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
    const googleBtn = await screen.findByRole("button", { name: /Continue with Google/i });
    await waitFor(() => {
      expect(googleBtn).not.toBeDisabled();
    });

    // First attempt triggers origin_mismatch -> surfaces Authorized JavaScript origins guidance
    fireEvent.click(googleBtn);
    expect(await screen.findByText(/Authorized JavaScript origins/i)).toBeInTheDocument();

    // Second attempt succeeds -> enters Clubhouse (synthetic test-only token, not a real credential)
    nextOAuthResponse = { access_token: "oauth_test.valid_popup_oauth_token", expires_in: 3600 };
    fireEvent.click(screen.getByRole("button", { name: /Continue with Google/i }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /Walk into every coffee chat warm and prepared/i,
      }),
    ).toBeInTheDocument();
  });

  it("enforces zero em-dashes across web portal HTML, styles, and UI components", () => {
    const portalSources = import.meta.glob<string>(["../index.html", "./**/*.{ts,tsx,css}"], {
      query: "?raw",
      import: "default",
      eager: true,
    });
    const emDashChar = String.fromCharCode(0x2014);
    const htmlEntityVariants = [`&${"mdash"};`, `&#${"8212"};`, `&#x${"2014"};`];

    const filesChecked = Object.entries(portalSources);
    expect(filesChecked.length).toBeGreaterThan(20);

    for (const [filePath, sourceText] of filesChecked) {
      expect(sourceText, `${filePath} must not contain Unicode em-dash`).not.toContain(emDashChar);
      for (const entity of htmlEntityVariants) {
        expect(
          sourceText.toLowerCase(),
          `${filePath} must not contain HTML em-dash entity ${entity}`,
        ).not.toContain(entity);
      }
    }
  });

  it("bounds 4-segment long-title timeline bars with minmax(0, ...fr) and preserves total minutes", async () => {
    const ashmitaContact: ContactResponse = {
      id: "cnt_ashmita",
      name: "Ashmita Kapoor",
      title: "FDE Manager",
      role: "Manager",
      organization: "Google Cloud",
      context_notes: null,
      version: 1,
      created_at: "2026-11-25T01:00:00Z",
      updated_at: "2026-11-25T01:00:00Z",
    };
    const fourSegmentBrief: PreparationBriefResponse = {
      ...makeSampleBrief(ashmitaContact.id),
      id: "brf_ashmita_4seg",
      meeting_id: "mtg_ashmita_1",
      contact_id: ashmitaContact.id,
      duration_minutes: 30,
      meeting_objective: "First one-on-one after joining Google for one week.",
      time_boxed_agenda: [
        {
          title: "Casual Welcome and Week One Reflections",
          duration_minutes: 5,
          description: "Check in on first week highlights.",
        },
        {
          title: "Onboarding Progress and Immediate Support",
          duration_minutes: 10,
          description: "Unblock access and tooling.",
        },
        {
          title: "Expectations and 30-Day Focus",
          duration_minutes: 10,
          description: "Align on initial 30-day outcomes.",
        },
        {
          title: "Next Steps and Cadence",
          duration_minutes: 5,
          description: "Confirm recurring 1:1 rhythm.",
        },
      ],
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") return jsonResponse(LOCAL_AUTH_CONFIG);
      if (path === "/api/auth/mock-session") {
        return jsonResponse(
          {
            access_token: "mses_ashmita",
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
      if (path === "/api/v1/contacts") return jsonResponse({ items: [ashmitaContact], total: 1 });
      if (path === "/api/v1/meetings") {
        return jsonResponse({
          items: [
            {
              id: fourSegmentBrief.meeting_id,
              contact_id: ashmitaContact.id,
              purpose: "coffee_chat",
              tone: "warm_casual",
              objective: fourSegmentBrief.meeting_objective,
              duration_minutes: 30,
              scheduled_at: null,
              notes: null,
              status: "preparing",
              latest_brief_id: fourSegmentBrief.id,
              version: 1,
              created_at: "2026-11-25T01:05:00Z",
              updated_at: "2026-11-25T01:05:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === `/api/v1/briefs/${fourSegmentBrief.id}/revisions`) {
        return jsonResponse({ items: [fourSegmentBrief], total: 1 });
      }
      if (path === `/api/v1/briefs/${fourSegmentBrief.id}`) {
        return jsonResponse(fourSegmentBrief);
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

    window.localStorage.setItem("brew.v2.calendar.demo_disabled:usr_mock_alice", "1");

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue as Alice Chen/i }));
    await screen.findByRole("heading", { level: 1, name: /Ashmita Kapoor/i });

    const openerPill = screen.getByTitle("5m · Casual Welcome and Week One Reflections");
    const corePill = screen.getByTitle(
      "10m Onboarding Progress and Immediate Support + 10m Expectations and 30-Day Focus",
    );
    const closePill = screen.getByTitle("5m · Next Steps and Cadence");

    expect(openerPill).toHaveTextContent("5m Casual Welcome and Week One Reflections");
    expect(corePill).toHaveTextContent("20m Onboarding Progress and Immediate Support");
    expect(closePill).toHaveTextContent("5m Next Steps and Cadence");
    expect(openerPill.parentElement?.style.gridTemplateColumns).toContain("minmax(0,");
  });

  it("allows a Google-authenticated user to set a custom display name and revert to their Google account name", async () => {
    let storedCustomName: string | null = null;
    const mayaContact: ContactResponse = {
      id: "cnt_maya",
      name: "Maya Lin",
      title: "Principal SRE",
      role: "Peer",
      organization: "CloudScale",
      context_notes: null,
      version: 1,
      created_at: "2026-11-25T01:00:00Z",
      updated_at: "2026-11-25T01:00:00Z",
    };

    window.google = {
      accounts: {
        oauth2: {
          initTokenClient: (cfg) => ({
            requestAccessToken: () => {
              cfg.callback({ access_token: "oauth_test.valid_google_token", expires_in: 3600 });
            },
          }),
        },
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const rawUrl =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const path = new URL(rawUrl, "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/health") return jsonResponse(HEALTH_OK);
      if (path === "/api/auth/config") {
        return jsonResponse({
          ...LOCAL_AUTH_CONFIG,
          auth_mode: "verified",
          local_mock_enabled: false,
          google_sign_in_enabled: true,
          google_oauth_client_id: "987654321-web.apps.googleusercontent.com",
          mock_personas: [],
        } satisfies AuthClientConfigResponse);
      }
      if (path === "/api/v1/auth/me" && method === "GET") {
        return jsonResponse({
          user_id: "google:112233445566",
          display_name: storedCustomName ?? "Kary Long",
          custom_display_name: storedCustomName,
          account_display_name: "Kary Long",
          auth_provider: "verified",
        });
      }
      if (path === "/api/v1/auth/me" && method === "PATCH") {
        const body = JSON.parse(String(init?.body ?? "{}")) as { display_name: string | null };
        storedCustomName = body.display_name;
        return jsonResponse({
          user_id: "google:112233445566",
          display_name: storedCustomName ?? "Kary Long",
          custom_display_name: storedCustomName,
          account_display_name: "Kary Long",
          auth_provider: "verified",
        });
      }
      if (path === "/api/v1/contacts") return jsonResponse({ items: [mayaContact], total: 1 });
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
      return jsonResponse({}, 404);
    });

    render(<App />);
    const googleBtn = await screen.findByRole("button", { name: /Continue with Google/i });
    await waitFor(() => {
      expect(googleBtn).not.toBeDisabled();
    });
    fireEvent.click(googleBtn);

    // Initially uses default Google account name "Kary Long"
    expect(
      await screen.findByRole("heading", { level: 1, name: /Coffee Chat: Kary <> Maya Lin/i }),
    ).toBeInTheDocument();

    // Open Account & Coaching Style folio via the top-right user avatar
    fireEvent.click(
      screen.getByRole("button", { name: /Account and coaching style for Kary Long/i }),
    );
    await screen.findByRole("heading", { name: /My Coaching Style \(Kary Long\)/i });

    const nameInput = screen.getByLabelText(/Preferred name in Brew/i);
    expect(nameInput).toHaveValue("Kary Long");

    // Client-side validation rejects blank whitespace name
    fireEvent.change(nameInput, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /^Save Name$/i }));
    expect(
      await screen.findByText("Enter a display name between 1 and 120 characters."),
    ).toBeInTheDocument();

    // Save custom name "Karina" -> updates header avatar, account folio, and Clubhouse hero
    fireEvent.change(nameInput, { target: { value: "Karina" } });
    fireEvent.click(screen.getByRole("button", { name: /^Save Name$/i }));

    expect(await screen.findByText("Display name updated")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /My Coaching Style \(Karina\)/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Account and coaching style for Karina/i }),
    ).toBeInTheDocument();

    const primaryNav = screen.getByRole("navigation", { name: /^Primary navigation$/i });
    fireEvent.click(within(primaryNav).getByRole("button", { name: /^Clubhouse$/i }));
    expect(
      await screen.findByRole("heading", { level: 1, name: /Coffee Chat: Karina <> Maya Lin/i }),
    ).toBeInTheDocument();

    // Revert back to default Google account name
    fireEvent.click(
      screen.getByRole("button", { name: /Account and coaching style for Karina/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Use Google name \(Kary Long\)/i }),
    );
    expect(await screen.findByText("Reverted to Google account name")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /My Coaching Style \(Kary Long\)/i }),
    ).toBeInTheDocument();
  });
});
