import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildDemoCalendarIcsFixture,
  formatCalendarCountdown,
  loadStoredCalendarEvents,
  matchCalendarEventContact,
  saveStoredCalendarEvents,
} from "./calendar/calendarStore";
import {
  GOOGLE_CALENDAR_READONLY_SCOPE,
  fetchReadOnlyGoogleCalendarEvents,
  requestGoogleCalendarReadOnlyToken,
} from "./calendar/googleCalendarClient";
import {
  classifyTemporalStatus,
  extractCounterpartDetails,
  isExplicitCoffeeChatEvent,
  parseIcsCalendarEvents,
} from "./calendar/icsParser";
import {
  validateBriefGenerationForm,
  validateContactForm,
} from "./components/formatters";
import {
  loadCoachingDefaults,
  saveCoachingDefaults,
} from "./state/coachingDefaultsStore";
import {
  loadStarredQuestionIds,
  saveStarredQuestionIds,
  toggleQuestionStar,
} from "./state/starredQuestionsStore";
import { computeBlueprintSplit } from "./utils/pacingBlueprint";
import { parseQuickSparkPrompt } from "./utils/quickSparkParser";

describe("Brew v2 Unit Suite: Parsers, Calendar Sync, Stores, and Blueprint Math", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete window.google;
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("parses natural-language Quick Spark prompts into counterpart, org, duration, tone, purpose, and objective", () => {
    const parsed = parseQuickSparkPrompt(
      "20m casual coffee chat with Jordan Kim at Figma about design token governance.",
    );
    expect(parsed).toEqual({
      counterpartName: "Jordan Kim",
      organization: "Figma",
      durationMinutes: 20,
      purpose: "coffee_chat",
      tone: "warm_casual",
      objective: "Design token governance",
    });

    const mentorship = parseQuickSparkPrompt(
      "half hour candid mentorship with Dr. Samir Patel regarding principal engineer scope",
    );
    expect(mentorship.durationMinutes).toBe(30);
    expect(mentorship.purpose).toBe("mentorship");
    expect(mentorship.tone).toBe("candid_coaching");
    expect(mentorship.counterpartName).toBe("Dr. Samir Patel");
    expect(mentorship.objective).toBe("Principal engineer scope");

    const parenthetical = parseQuickSparkPrompt(
      "15m warm intro with Jordan Rivera (Platform Lead at Stripe) about API ergonomics",
    );
    expect(parenthetical).toEqual({
      counterpartName: "Jordan Rivera",
      organization: "Stripe",
      durationMinutes: 15,
      purpose: "networking",
      tone: "warm_casual",
      objective: "API ergonomics",
    });

    expect(parseQuickSparkPrompt("   ")).toEqual({
      counterpartName: null,
      organization: null,
      durationMinutes: null,
      purpose: null,
      tone: null,
      objective: null,
    });
  });

  it("parses RFC 5545 .ics coffee chat events while filtering cancelled, non-chat, and >180m blocks", () => {
    const anchorMs = Date.UTC(2026, 10, 24, 14, 0, 0);
    const demoIcs = buildDemoCalendarIcsFixture(anchorMs, "Alice");
    const extraNoise = [
      "BEGIN:VEVENT",
      "UID:noise-standup",
      "DTSTART:20261124T160000Z",
      "DTEND:20261124T163000Z",
      "SUMMARY:Weekly Sprint Standup",
      "END:VEVENT",
      "BEGIN:VEVENT",
      "UID:cancelled-chat",
      "STATUS:CANCELLED",
      "DTSTART:20261124T170000Z",
      "DTEND:20261124T173000Z",
      "SUMMARY:Coffee Chat: Cancelled Guest",
      "END:VEVENT",
      "BEGIN:VEVENT",
      "UID:group-chat-3-people",
      "DTSTART:20261128T180000Z",
      "DTEND:20261128T183000Z",
      "SUMMARY:Coffee Chat: Alice, Maya & Samir",
      "ATTENDEE;CN=Alice Chen:mailto:alice@example.com",
      "ATTENDEE;CN=Maya Lin:mailto:maya@example.com",
      "ATTENDEE;CN=Samir Patel:mailto:samir@example.com",
      "END:VEVENT",
      "BEGIN:VEVENT",
      "UID:group-chat-with-brew-tag",
      "DTSTART:20261128T190000Z",
      "DTEND:20261128T193000Z",
      "SUMMARY:Founder Fireside Chat: Priya & Jordan",
      "DESCRIPTION:Explicitly tracked small group session #brew",
      "ATTENDEE;CN=Alice Chen:mailto:alice@example.com",
      "ATTENDEE;CN=Priya Nair:mailto:priya@example.com",
      "ATTENDEE;CN=Jordan Kim:mailto:jordan@example.com",
      "END:VEVENT",
      "BEGIN:VEVENT",
      "UID:two-humans-plus-room",
      "DTSTART:20261128T200000Z",
      "DTEND:20261128T203000Z",
      "SUMMARY:1:1: Nina Alvarez ( Datadog )",
      "ATTENDEE;CN=Alice Chen:mailto:alice@example.com",
      "ATTENDEE;CN=Nina Alvarez:mailto:nina@example.com",
      "ATTENDEE;CUTYPE=ROOM;CN=Bldg 43 Espresso Room:mailto:room@example.com",
      "END:VEVENT",
    ].join("\r\n");

    const injected = demoIcs.replace("END:VCALENDAR", `${extraNoise}\r\nEND:VCALENDAR`);
    const events = parseIcsCalendarEvents(injected, {
      nowMs: anchorMs,
      selfDisplayName: "Alice Chen",
      source: "gcal",
    });

    expect(events).toHaveLength(6);
    expect(events.map((e) => e.id)).not.toContain("group-chat-3-people");
    expect(events.map((e) => e.id)).toContain("group-chat-with-brew-tag");
    expect(events.map((e) => e.id)).toContain("two-humans-plus-room");
    expect(events[0]?.temporalStatus).toBe("wrapped");
    expect(events[0]?.counterpartName).toBe("Alex Morgan");
    expect(events[1]?.temporalStatus).toBe("up_next");
    expect(events[1]?.counterpartName).toBe("Maya Lin");
    expect(events[1]?.counterpartOrganization).toBe("CloudScale");
    expect(events[2]?.durationMinutes).toBe(45);
    expect(events[2]?.purpose).toBe("mentorship");
    expect(events[3]?.durationMinutes).toBe(15);

    expect(isExplicitCoffeeChatEvent("1:1 Design Sync", "")).toBe(true);
    expect(isExplicitCoffeeChatEvent("Quarterly All Hands", "")).toBe(false);
    expect(isExplicitCoffeeChatEvent("Weekly Team Catch-Up", "")).toBe(false);
    expect(
      isExplicitCoffeeChatEvent("Project Review", "Target date 2026-01-15 on Zoom 981-142-33"),
    ).toBe(false);
    expect(
      isExplicitCoffeeChatEvent("Coffee Chat: Panel", "", { attendeeCount: 3 }),
    ).toBe(false);
    expect(
      isExplicitCoffeeChatEvent("Coffee Chat: Panel", "Track with #brew", { attendeeCount: 4 }),
    ).toBe(true);
    expect(extractCounterpartDetails("Coffee Chat: Alice <> Maya Lin (CloudScale)", "Alice Chen")).toEqual({
      counterpartName: "Maya Lin",
      counterpartOrganization: "CloudScale",
      counterpartRole: null,
    });
    expect(classifyTemporalStatus(anchorMs - 3600_000, anchorMs - 1800_000, anchorMs)).toBe("wrapped");
  });

  it("requests read-only Google Calendar OAuth scope and fetches primary calendar events with timeout protection", async () => {
    // Synthetic OAuth token string for unit testing only (never a real credential).
    const syntheticCalendarToken = "oauth_test.readonly_cal_tok";
    let requestedScope = "";
    window.google = {
      accounts: {
        oauth2: {
          initTokenClient: (cfg) => {
            requestedScope = cfg.scope;
            return {
              requestAccessToken: () => {
                cfg.callback({ access_token: syntheticCalendarToken, expires_in: 3600 });
              },
            };
          },
        },
      },
    };

    const token = await requestGoogleCalendarReadOnlyToken("client-123.apps.googleusercontent.com");
    expect(token).toBe(syntheticCalendarToken);
    expect(requestedScope).toBe(GOOGLE_CALENDAR_READONLY_SCOPE);

    const nowMs = Date.UTC(2026, 10, 24, 13, 0, 0);
    const rawGcalSummaryWithEmDash = `Coffee Chat ${String.fromCharCode(0x2014)} Elena Rostova (Linear)`;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            {
              id: "gcal_evt_1",
              status: "confirmed",
              summary: rawGcalSummaryWithEmDash,
              description: "Swap evaluation rubric notes",
              start: { dateTime: "2026-11-24T13:30:00Z" },
              end: { dateTime: "2026-11-24T14:00:00Z" },
              attendees: [
                { email: "alice@example.com", displayName: "Alice Chen", self: true },
                { email: "elena@example.com", displayName: "Elena Rostova" },
                { email: "room@example.com", displayName: "Conf Room B", resource: true },
              ],
            },
            {
              id: "gcal_evt_group_excluded",
              status: "confirmed",
              summary: "Coffee Chat: Team Trio",
              start: { dateTime: "2026-11-24T14:15:00Z" },
              end: { dateTime: "2026-11-24T14:45:00Z" },
              attendees: [
                { email: "alice@example.com", self: true },
                { email: "b@example.com" },
                { email: "c@example.com" },
              ],
            },
            {
              id: "gcal_evt_ignored",
              status: "confirmed",
              summary: "Dentist Appointment",
              start: { dateTime: "2026-11-24T15:00:00Z" },
              end: { dateTime: "2026-11-24T16:00:00Z" },
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const synced = await fetchReadOnlyGoogleCalendarEvents(token, {
      nowMs,
      selfDisplayName: "Alice Chen",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(synced).toHaveLength(1);
    expect(synced[0]?.counterpartName).toBe("Elena Rostova");
    expect(synced[0]?.title).not.toContain(String.fromCharCode(0x2014));
    expect(synced[0]?.durationMinutes).toBe(30);
    expect(synced[0]?.source).toBe("gcal");
  });

  it("persists starred Pocket Cue Cards per brief and defaults to top 2 questions", () => {
    const qIds = ["q_1", "q_2", "q_3", "q_4"];
    const initial = loadStarredQuestionIds("usr_alice", "brf_10", qIds);
    expect(Array.from(initial)).toEqual(["q_1", "q_2"]);

    const afterToggle = toggleQuestionStar(toggleQuestionStar(initial, "q_2"), "q_4");
    saveStarredQuestionIds("usr_alice", "brf_10", afterToggle);

    const reloaded = loadStarredQuestionIds("usr_alice", "brf_10", qIds);
    expect(Array.from(reloaded)).toEqual(["q_1", "q_4"]);
  });

  it("maintains exact sum invariants on pacing blueprints and persists coaching defaults & calendar slots", () => {
    for (const mins of [15, 20, 30, 45, 60, 90]) {
      const split = computeBlueprintSplit(mins);
      expect(split.hookMinutes + split.coreMinutes + split.wrapMinutes).toBe(mins);
    }

    saveCoachingDefaults("usr_alice", {
      defaultDurationMinutes: 45,
      defaultTone: "candid_coaching",
      defaultStyleNotes: "Direct engineering stories.",
    });
    expect(loadCoachingDefaults("usr_alice")).toEqual({
      defaultDurationMinutes: 45,
      defaultTone: "candid_coaching",
      defaultStyleNotes: "Direct engineering stories.",
    });

    const demoSlots = loadStoredCalendarEvents("usr_alice", {
      isLocalMock: true,
      userDisplayName: "Alice Chen",
      nowMs: Date.UTC(2026, 10, 24, 14, 0, 0),
    });
    expect(demoSlots).toHaveLength(4);
    const secondDemoSlot = demoSlots[1];
    expect(secondDemoSlot).toBeDefined();
    if (secondDemoSlot) {
      expect(
        matchCalendarEventContact(secondDemoSlot, [
          {
            id: "cnt_m",
            name: "Maya Lin",
            title: "Principal SRE",
            role: null,
            organization: "CloudScale",
            context_notes: null,
            version: 1,
            created_at: "2026-11-23T00:00:00Z",
            updated_at: "2026-11-23T00:00:00Z",
          },
        ])?.id,
      ).toBe("cnt_m");
    }

    saveStoredCalendarEvents("usr_alice", []);
    expect(
      loadStoredCalendarEvents("usr_alice", {
        isLocalMock: true,
        userDisplayName: "Alice Chen",
      }),
    ).toEqual([]);

    expect(formatCalendarCountdown("2026-11-24T14:42:00Z", Date.UTC(2026, 10, 24, 14, 0, 0))).toBe(
      "Starts in 42 min",
    );

    expect(
      validateContactForm({
        name: "",
        title: "",
        role: "",
        organization: "",
        contextNotes: "ab",
      }),
    ).toMatchObject({
      name: "Counterpart name is required.",
      context_notes: "Context notes must be at least 3 characters when provided.",
    });

    expect(
      validateBriefGenerationForm({
        meetingObjective: "Hi",
        durationMinutes: 3,
        preferredQuestionCount: "99",
        communicationStyleNotes: "",
      }),
    ).toMatchObject({
      meeting_objective: "Enter a meeting objective (at least 3 characters).",
      duration_minutes: "Duration must be between 5 and 180 minutes.",
      preferred_question_count: "Question count must be between 1 and 15.",
    });

    // Recognizes both custom Brew display name and default Google account name as self on calendar invites
    expect(
      extractCounterpartDetails("Coffee Chat: Kary Long <> Maya Lin (CloudScale)", [
        "Karina",
        "Kary Long",
      ]),
    ).toEqual({
      counterpartName: "Maya Lin",
      counterpartOrganization: "CloudScale",
      counterpartRole: null,
    });
    expect(
      extractCounterpartDetails("Coffee Chat: Karina <> Maya Lin (CloudScale)", [
        "Karina",
        "Kary Long",
      ]),
    ).toEqual({
      counterpartName: "Maya Lin",
      counterpartOrganization: "CloudScale",
      counterpartRole: null,
    });
  });
});
