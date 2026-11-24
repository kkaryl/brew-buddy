import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import type { HealthPayload } from "../src/api/health";
import type {
  AuthClientConfigResponse,
  BriefRevisionListResponse,
  ContactListResponse,
  ContactResponse,
  MeetingListResponse,
  MeetingResponse,
  MemoryListResponse,
  MemoryProposalBatchResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
} from "../src/api/types";
import type { StoredAuthSession } from "../src/auth/session";
import type { CalendarCoffeeChatEvent } from "../src/calendar/calendarTypes";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "../..");
const mockupsDir = path.join(repoRoot, "mockups/v2");
const visualRootDir = path.join(repoRoot, "tests/visual");
const actualDir = path.join(visualRootDir, "actual");
const comparisonsDir = path.join(visualRootDir, "comparisons");

const SCREEN_SPECS = [
  { id: "01-desktop-clubhouse-calendar", label: "01 · Desktop Clubhouse & Calendar", width: 1440, height: 980 },
  { id: "02-desktop-quick-spark-setup", label: "02 · Focused Conversation Setup", width: 1440, height: 960 },
  { id: "03-desktop-cue-card-studio", label: "03 · Desktop Cue Studio", width: 1440, height: 980 },
  { id: "04-desktop-debrief-keepsakes", label: "04 · Desktop Debrief & Keepsakes", width: 1440, height: 960 },
  { id: "05-desktop-journal-people-dna", label: "05 · Desktop Relationship Journal", width: 1440, height: 980 },
  { id: "06-mobile-clubhouse-calendar", label: "06 · Mobile Clubhouse & Calendar", width: 430, height: 932 },
  { id: "07-mobile-pocket-cue-cards", label: "07 · Mobile Pocket Cue Cards", width: 430, height: 932 },
  { id: "08-mobile-debrief-keepsakes", label: "08 · Mobile Debrief & Keepsakes", width: 430, height: 932 },
] as const;

const FIXED_NOW_ISO = "2026-10-28T17:18:00.000Z";
const FIXED_NOW_MS = Date.parse(FIXED_NOW_ISO);

const HEALTH_FIXTURE: HealthPayload = {
  status: "ok",
  service: "brew",
  version: "0.2.0",
  environment: "local",
  model: "gemini-2.5-pro",
  timestamp_utc: FIXED_NOW_ISO,
};

const AUTH_CONFIG_FIXTURE: AuthClientConfigResponse = {
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
      role_summary: "Product Lead preparing for weekly coffee chats",
    },
  ],
};

const CONTACTS_FIXTURE: readonly ContactResponse[] = [
  {
    id: "contact-maya",
    name: "Maya Lin",
    title: "Staff Distributed Systems Engineer",
    role: "Infrastructure & Mentorship Peer",
    organization: "CloudScale",
    context_notes: "Met in KubeCon distributed storage hallway track.",
    version: 1,
    created_at: "2026-08-12T15:00:00Z",
    updated_at: "2026-10-28T14:00:00Z",
  },
  {
    id: "contact-alex",
    name: "Alex Morgan",
    title: "VP of Product",
    role: "Product Discovery Counterpart",
    organization: "Northstar AI",
    context_notes: "Introduced by Samir after AI Product Summit.",
    version: 1,
    created_at: "2026-07-04T15:00:00Z",
    updated_at: "2026-10-28T15:15:00Z",
  },
  {
    id: "contact-samir",
    name: "Dr. Samir Patel",
    title: "Principal Research Scientist",
    role: "Quarterly Engineering Mentor",
    organization: "DeepField Labs",
    context_notes: "Quarterly engineering mentorship circle.",
    version: 1,
    created_at: "2026-05-10T15:00:00Z",
    updated_at: "2026-10-14T15:00:00Z",
  },
  {
    id: "contact-elena",
    name: "Elena Rostova",
    title: "Head of Design Systems",
    role: "Design Engineering Peer",
    organization: "Looma Studio",
    context_notes: "Met at design tokens workshop in SF.",
    version: 1,
    created_at: "2026-04-02T15:00:00Z",
    updated_at: "2026-08-16T15:00:00Z",
  },
];

const MAYA_MEETING: MeetingResponse = {
  id: "mtg-maya-oct28",
  contact_id: "contact-maya",
  purpose: "networking",
  tone: "warm_casual",
  objective:
    "Compare multi-region failover drills, zero-downtime shard migrations, and how Maya scopes staff-level technical charters.",
  duration_minutes: 30,
  scheduled_at: new Date(FIXED_NOW_MS + 42 * 60_000).toISOString(),
  notes: "Maya led CloudScale's regional cell isolation in Q3.",
  status: "preparing",
  latest_brief_id: "brief-maya-v2",
  version: 2,
  created_at: "2026-10-28T13:00:00Z",
  updated_at: "2026-10-28T14:10:00Z",
};

const ALEX_MEETING: MeetingResponse = {
  id: "mtg-alex-oct28",
  contact_id: "contact-alex",
  purpose: "customer_discovery",
  tone: "curious_exploratory",
  objective: "Learn how Northstar AI structures golden evaluation datasets before enterprise launches.",
  duration_minutes: 30,
  scheduled_at: new Date(FIXED_NOW_MS - 150 * 60_000).toISOString(),
  notes: "Follow-up chat after AI Product Summit.",
  status: "completed",
  latest_brief_id: "brief-alex-v1",
  version: 1,
  created_at: "2026-10-28T12:00:00Z",
  updated_at: "2026-10-28T15:10:00Z",
};

const MAYA_BRIEF_V1: PreparationBriefResponse = {
  id: "brief-maya-v1",
  meeting_id: "mtg-maya-oct28",
  contact_id: "contact-maya",
  duration_minutes: 30,
  tone: "warm_casual",
  contact_context:
    "Maya Lin is a Staff Distributed Systems Engineer at CloudScale leading cell-based multi-region reliability.",
  meeting_objective:
    "Compare multi-region failover drills and how Maya scopes staff-level technical charters.",
  conversation_openers: [
    "Ask how her team's first cross-region chaos game day went last Thursday before diving into cell boundaries.",
  ],
  time_boxed_agenda: [
    {
      title: "Warm Hook",
      duration_minutes: 5,
      description: "Reconnect around KubeCon and her Q3 regional cell rollout.",
    },
    {
      title: "Core Exploration",
      duration_minutes: 18,
      description: "Compare failover drills and staff-scope charter framing.",
    },
    {
      title: "Reciprocity & Close",
      duration_minutes: 7,
      description: "Offer latency benchmarks and confirm next touchpoint.",
    },
  ],
  suggested_questions: [
    {
      id: "q-maya-1",
      question:
        "When you ran last week's regional failover drill, which dependency surprised the team most under real traffic?",
      rationale: "Builds directly on her Q3 cell migration story with concrete operational curiosity.",
      category: "Warm Opener",
    },
    {
      id: "q-maya-2",
      question:
        "How do you decide when an infrastructure bet deserves a multi-quarter staff charter versus a quick tiger team?",
      rationale: "Surfaces her staff-scope decision framework without sounding transactional.",
      category: "Staff Scope",
    },
  ],
  suggested_follow_up_topics: ["Send summary of our service-mesh latency benchmarks by Friday."],
  referenced_memory_ids: ["mem-maya-1", "mem-maya-2"],
  revision_summary: null,
  version: 1,
  created_at: "2026-10-28T13:05:00Z",
  updated_at: "2026-10-28T13:05:00Z",
  workflow: null,
};

const MAYA_BRIEF_V2: PreparationBriefResponse = {
  id: "brief-maya-v2",
  meeting_id: "mtg-maya-oct28",
  contact_id: "contact-maya",
  duration_minutes: 30,
  tone: "warm_casual",
  contact_context:
    "Maya Lin leads CloudScale's cell-based multi-region storage reliability and mentors senior infrastructure engineers. You bonded at KubeCon over pragmatic incident retrospectives.",
  meeting_objective:
    "Multi-region failover drills & Staff technical charters",
  conversation_openers: [
    "Congratulate her on shipping Q3 regional cell isolation and ask what felt unexpectedly calm during last week's failover rehearsal.",
    "Thanks for carving out half an hour between Q4 game days; excited to swap practical cell-routing notes.",
  ],
  time_boxed_agenda: [
    {
      title: "Warm-up",
      duration_minutes: 5,
      description: "Celebrate Q3 regional cell isolation and Portland pour-over studio check-in.",
    },
    {
      title: "Failover Drills & Staff Scope",
      duration_minutes: 18,
      description: "Explore stateful shard routing and cross-org reliability alignment.",
    },
    {
      title: "Next Steps",
      duration_minutes: 7,
      description: "Share shadow-read verification write-up and ask for winter peer intros.",
    },
  ],
  suggested_questions: [
    {
      id: "q-maya-v2-1",
      question:
        "During last week's live regional evacuation drill, what signal told you the cell boundary was genuinely holding?",
      rationale: "Directly honors her Q3 milestone and invites a vivid, energizing opening story.",
      category: "Warm Opener",
    },
    {
      id: "q-maya-v2-2",
      question:
        "Where did stateful shard routing push back hardest when you decoupled the control plane from regional cells?",
      rationale: "Targets your shared technical objective around zero-downtime shard migrations.",
      category: "Architecture Deep-Dive",
    },
    {
      id: "q-maya-v2-3",
      question:
        "When you sponsor a cross-org reliability charter at Staff scope, how do you keep partner teams aligned after month two?",
      rationale: "Starred mentorship angle on technical leadership and durable influence.",
      category: "Staff Mentorship",
    },
    {
      id: "q-maya-v2-4",
      question:
        "Who else thinking deeply about deterministic simulation testing would be fun for us to swap notes with this winter?",
      rationale: "Warm, generous close that opens future community introductions naturally.",
      category: "Reciprocity & Close",
    },
  ],
  suggested_follow_up_topics: [
    "Share our write-up on shadow-read verification within 48 hours",
    "Follow up on her ceramic pour-over studio recommendation in Portland",
  ],
  referenced_memory_ids: ["mem-maya-1", "mem-maya-2", "mem-maya-3"],
  revision_summary: "Added Staff charter mentorship angle and tightened 30m pacing split.",
  version: 2,
  created_at: "2026-10-28T13:05:00Z",
  updated_at: "2026-10-28T14:10:00Z",
  workflow: null,
};

const ALEX_PROPOSALS: readonly MemoryProposalResponse[] = [
  {
    id: "prop-alex-1",
    scope: "contact",
    contact_id: "contact-alex",
    memory_type: "follow_up_commitment",
    text: "Send Alex our 30-case tool-trajectory evaluation rubric before next Tuesday's product review.",
    rationale: "Explicit follow-up commitment mentioned near the close of the chat.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-alex-oct28",
      brief_id: "brief-alex-v1",
      proposal_id: "prop-alex-1",
      excerpt: "Committed to sending our 30-case tool-trajectory rubric before Tuesday.",
      recorded_at: "2026-10-28T15:12:00Z",
    },
    status: "pending",
    lifecycle_state: "proposed",
    epistemic_status: "user_reported_observation",
    supersedes_memory_id: null,
    conflict_summary: null,
    rejection_reason: null,
    approved_memory_id: null,
    created_at: "2026-10-28T15:12:00Z",
    updated_at: "2026-10-28T15:12:00Z",
    reviewed_at: null,
    version: 1,
  },
  {
    id: "prop-alex-2",
    scope: "contact",
    contact_id: "contact-alex",
    memory_type: "counterpart_background",
    text: "Shifted Northstar AI's Q4 release gate from synthetic benchmarks to curated customer replay traces.",
    rationale: "Updates prior Oct 18 note when Northstar relied primarily on synthetic prompts.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-alex-oct28",
      brief_id: "brief-alex-v1",
      proposal_id: "prop-alex-2",
      excerpt: "Replaced synthetic benchmarks with curated production replay traces.",
      recorded_at: "2026-10-28T15:12:05Z",
    },
    status: "pending",
    lifecycle_state: "proposed",
    epistemic_status: "user_reported_observation",
    supersedes_memory_id: "mem-alex-oct18",
    conflict_summary: "Replaces Oct 18 note: Northstar gates launches on synthetic prompt suites.",
    rejection_reason: null,
    approved_memory_id: null,
    created_at: "2026-10-28T15:12:05Z",
    updated_at: "2026-10-28T15:12:05Z",
    reviewed_at: null,
    version: 1,
  },
  {
    id: "prop-alex-3",
    scope: "contact",
    contact_id: "contact-alex",
    memory_type: "shared_interest",
    text: "Training for the Marin Headlands 50K trail run in December; prefers morning coffee chats before 10am.",
    rationale: "Warm personal rapport detail and scheduling preference for future check-ins.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-alex-oct28",
      brief_id: "brief-alex-v1",
      proposal_id: "prop-alex-3",
      excerpt: "Training for Marin Headlands 50K in December and prefers pre-10am slots.",
      recorded_at: "2026-10-28T15:12:10Z",
    },
    status: "pending",
    lifecycle_state: "proposed",
    epistemic_status: "user_reported_observation",
    supersedes_memory_id: null,
    conflict_summary: null,
    rejection_reason: null,
    approved_memory_id: null,
    created_at: "2026-10-28T15:12:10Z",
    updated_at: "2026-10-28T15:12:10Z",
    reviewed_at: null,
    version: 1,
  },
];

const MAYA_MEMORIES: readonly MemoryResponse[] = [
  {
    id: "mem-maya-1",
    owner_user_id: "alice-user",
    scope: "contact",
    contact_id: "contact-maya",
    memory_type: "counterpart_background",
    text: "Led CloudScale's Q3 cell-based multi-region storage isolation across US-West, US-East, and Frankfurt.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-maya-oct28",
      brief_id: "brief-maya-v1",
      proposal_id: "prop-maya-01",
      excerpt: "Led Q3 cell-based multi-region storage isolation.",
      recorded_at: "2026-09-19T16:00:00Z",
    },
    consent_status: "approved",
    lifecycle_state: "approved",
    epistemic_status: "user_reported_observation",
    supersedes_memory_id: null,
    superseded_by_memory_id: null,
    superseded_at: null,
    created_at: "2026-09-19T16:00:00Z",
    updated_at: "2026-09-19T16:00:00Z",
    version: 1,
  },
  {
    id: "mem-maya-2",
    owner_user_id: "alice-user",
    scope: "contact",
    contact_id: "contact-maya",
    memory_type: "communication_preference",
    text: "Appreciates crisp architecture diagrams sent 24 hours ahead rather than long slide decks during 1:1s.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-maya-oct28",
      brief_id: "brief-maya-v1",
      proposal_id: "prop-maya-02",
      excerpt: "Prefers crisp diagrams sent 24h ahead.",
      recorded_at: "2026-09-19T16:02:00Z",
    },
    consent_status: "approved",
    lifecycle_state: "approved",
    epistemic_status: "user_stated_preference",
    supersedes_memory_id: null,
    superseded_by_memory_id: null,
    superseded_at: null,
    created_at: "2026-09-19T16:02:00Z",
    updated_at: "2026-09-19T16:02:00Z",
    version: 1,
  },
  {
    id: "mem-maya-3",
    owner_user_id: "alice-user",
    scope: "contact",
    contact_id: "contact-maya",
    memory_type: "shared_interest",
    text: "Collects small-batch ceramic pour-over drippers from independent studios in Portland and Kyoto.",
    source: {
      source_type: "meeting_notes",
      meeting_id: "mtg-maya-oct28",
      brief_id: null,
      proposal_id: "prop-maya-03",
      excerpt: "Collects ceramic pour-over drippers from Portland and Kyoto.",
      recorded_at: "2026-08-14T16:00:00Z",
    },
    consent_status: "approved",
    lifecycle_state: "approved",
    epistemic_status: "user_reported_observation",
    supersedes_memory_id: null,
    superseded_by_memory_id: null,
    superseded_at: null,
    created_at: "2026-08-14T16:00:00Z",
    updated_at: "2026-08-14T16:00:00Z",
    version: 1,
  },
];

const CALENDAR_EVENTS_FIXTURE: readonly CalendarCoffeeChatEvent[] = [
  {
    id: "gcal-wrapped-alex",
    title: "Coffee Chat: Alex Morgan (Northstar AI)",
    counterpartName: "Alex Morgan",
    counterpartTitle: "VP of Product",
    counterpartOrganization: "Northstar AI",
    counterpartRole: "VP of Product at Northstar AI",
    purpose: "customer_discovery",
    scheduledStartIso: new Date(FIXED_NOW_MS - 150 * 60_000).toISOString(),
    scheduledEndIso: new Date(FIXED_NOW_MS - 120 * 60_000).toISOString(),
    durationMinutes: 30,
    notesExcerpt: "Catch up on golden evaluation datasets and AI adoption lessons.",
    source: "gcal",
    temporalStatus: "wrapped",
  },
  {
    id: "gcal-upnext-maya",
    title: "Coffee Chat: Alice <> Maya Lin (CloudScale)",
    counterpartName: "Maya Lin",
    counterpartTitle: "Staff Distributed Systems Engineer",
    counterpartOrganization: "CloudScale",
    counterpartRole: "Staff Distributed Systems Engineer at CloudScale",
    purpose: "networking",
    scheduledStartIso: new Date(FIXED_NOW_MS + 42 * 60_000).toISOString(),
    scheduledEndIso: new Date(FIXED_NOW_MS + 72 * 60_000).toISOString(),
    durationMinutes: 30,
    notesExcerpt: "Discuss multi-region failover drills and staff charters.",
    source: "gcal",
    temporalStatus: "up_next",
  },
  {
    id: "gcal-thu-samir",
    title: "Mentorship Coffee: Dr. Samir Patel",
    counterpartName: "Dr. Samir Patel",
    counterpartTitle: "Principal Research Scientist",
    counterpartOrganization: "DeepField Labs",
    counterpartRole: "Principal Research Scientist at DeepField Labs",
    purpose: "mentorship",
    scheduledStartIso: new Date(FIXED_NOW_MS + 44 * 3600_000).toISOString(),
    scheduledEndIso: new Date(FIXED_NOW_MS + 44 * 3600_000 + 45 * 60_000).toISOString(),
    durationMinutes: 45,
    notesExcerpt: "45m quarterly engineering mentorship catch-up.",
    source: "gcal",
    temporalStatus: "upcoming",
  },
  {
    id: "gcal-fri-priya",
    title: "Coffee Chat: Priya Nair (Design Systems)",
    counterpartName: "Priya Nair",
    counterpartTitle: "Staff Design Technologist",
    counterpartOrganization: "Design Systems",
    counterpartRole: "Staff Design Technologist · Design Systems",
    purpose: "coffee_chat",
    scheduledStartIso: new Date(FIXED_NOW_MS + 72 * 3600_000).toISOString(),
    scheduledEndIso: new Date(FIXED_NOW_MS + 72 * 3600_000 + 15 * 60_000).toISOString(),
    durationMinutes: 15,
    notesExcerpt: "Explore Figma token automation pipelines and component governance.",
    source: "gcal",
    temporalStatus: "upcoming",
  },
];

const SESSION_FIXTURE: StoredAuthSession = {
  accessToken: "mock:alice-user:Alice Chen",
  refreshToken: null,
  expiresAtMs: FIXED_NOW_MS + 86_400_000,
  principal: {
    user_id: "alice-user",
    display_name: "Alice Chen",
    auth_provider: "local_mock",
  },
};

async function mountDeterministicVisualMocks(page: Page): Promise<void> {
  await page.clock.install({ time: new Date(FIXED_NOW_ISO) });

  await page.addInitScript(
    ({ sessionPayload, calendarEvents }) => {
      window.sessionStorage.setItem("brew.auth.session.v1", JSON.stringify(sessionPayload));
      window.localStorage.setItem(
        "brew.v2.calendar.events:alice-user",
        JSON.stringify(calendarEvents),
      );
      window.localStorage.setItem(
        "brew.v2.starred_questions:alice-user:brief-maya-v2",
        JSON.stringify(["q-maya-v2-1", "q-maya-v2-3"]),
      );
    },
    { sessionPayload: SESSION_FIXTURE, calendarEvents: CALENDAR_EVENTS_FIXTURE },
  );

  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(HEALTH_FIXTURE),
    });
  });

  await page.route("**/api/auth/config", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(AUTH_CONFIG_FIXTURE),
    });
  });

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;

    if (pathname.endsWith("/auth/config")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(AUTH_CONFIG_FIXTURE),
      });
      return;
    }

    if (pathname.endsWith("/auth/me")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SESSION_FIXTURE.principal),
      });
      return;
    }

    if (pathname.endsWith("/contacts")) {
      const payload: ContactListResponse = {
        items: CONTACTS_FIXTURE,
        total: CONTACTS_FIXTURE.length,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }

    if (pathname.endsWith("/meetings")) {
      const cid = url.searchParams.get("contact_id");
      const items =
        cid === "contact-maya"
          ? [MAYA_MEETING]
          : cid === "contact-alex"
            ? [ALEX_MEETING]
            : [MAYA_MEETING, ALEX_MEETING];
      const payload: MeetingListResponse = { items, total: items.length };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }

    if (pathname.endsWith("/briefs/brief-maya-v2/revisions")) {
      const payload: BriefRevisionListResponse = {
        items: [MAYA_BRIEF_V1, MAYA_BRIEF_V2],
        total: 2,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }

    if (pathname.endsWith("/briefs/brief-maya-v2")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MAYA_BRIEF_V2),
      });
      return;
    }

    if (
      pathname.endsWith("/briefs/brief-alex-v1/revisions") ||
      pathname.endsWith("/briefs/brief-alex-v1")
    ) {
      const alexBrief: PreparationBriefResponse = {
        ...MAYA_BRIEF_V1,
        id: "brief-alex-v1",
        meeting_id: "mtg-alex-oct28",
        contact_id: "contact-alex",
      };
      if (pathname.endsWith("/revisions")) {
        const listPayload: BriefRevisionListResponse = { items: [alexBrief], total: 1 };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(listPayload),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(alexBrief),
        });
      }
      return;
    }

    if (pathname.endsWith("/memories/proposals")) {
      const cid = url.searchParams.get("contact_id");
      const proposals = !cid || cid === "contact-alex" ? ALEX_PROPOSALS : [];
      const payload: MemoryProposalBatchResponse = {
        proposals,
        total: proposals.length,
        skipped_duplicates: 0,
        filtered_sensitive_count: 0,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }

    if (pathname.endsWith("/memories")) {
      const cid = url.searchParams.get("contact_id");
      const items = !cid || cid === "contact-maya" ? MAYA_MEMORIES : [];
      const payload: MemoryListResponse = { items, total: items.length };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });
}

async function settleFontsAndIllustrations(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    const images = Array.from(document.querySelectorAll("img"));
    await Promise.all(
      images.map(
        (img) =>
          new Promise<void>((resolve) => {
            if (img.complete && img.naturalWidth > 0) {
              resolve();
              return;
            }
            img.addEventListener("load", () => resolve(), { once: true });
            img.addEventListener("error", () => resolve(), { once: true });
          }),
      ),
    );
  });
  const brokenImages = await page.evaluate(() =>
    Array.from(document.querySelectorAll("img"))
      .filter((img) => img.naturalWidth === 0)
      .map((img) => img.getAttribute("src") ?? "unknown"),
  );
  expect(brokenImages, "All screen illustrations must decode cleanly").toEqual([]);
}

test.describe("Brew V2 Visual Fidelity Screenshot Capture (01..08)", () => {
  test.beforeAll(() => {
    fs.mkdirSync(actualDir, { recursive: true });
    fs.mkdirSync(comparisonsDir, { recursive: true });
  });

  test("Captures all 8 v2 screens at exact approved mockup viewports and builds side-by-side comparison artifacts", async ({
    page,
  }) => {
    await mountDeterministicVisualMocks(page);

    // 01: Desktop Clubhouse Calendar (1440x980)
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.goto("/");
    await expect(page.locator("#nav-space-clubhouse")).toBeVisible();
    await expect(page.locator("#clubhouse-hero-heading")).toContainText("Maya Lin");
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "01-desktop-clubhouse-calendar.png"),
      fullPage: false,
    });

    // 02: Desktop Quick Spark Setup (1440x960) seeded from Priya Nair's 15m GCal slot
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator("#btn-prep-calendar-gcal-fri-priya").click();
    await expect(page.locator("#btn-submit-generate-brief")).toBeVisible();
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "02-desktop-quick-spark-setup.png"),
      fullPage: false,
    });

    // Return to Clubhouse, then 03: Desktop Cue Card Studio (1440x980)
    await page.locator("#btn-setup-back").click();
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.locator("#nav-space-studio").click();
    await expect(page.locator("#btn-brief-revision-v2")).toBeVisible();
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "03-desktop-cue-card-studio.png"),
      fullPage: false,
    });

    // 04: Desktop Debrief & Keepsakes (1440x960) for Alex Morgan's wrapped coffee chat
    await page.locator("#nav-space-clubhouse").click();
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator("#btn-desktop-wrapped-debrief").click();
    await expect(page.locator("#post-meeting-notes-input")).toBeVisible();
    await page
      .locator("#post-meeting-notes-input")
      .fill(
        "Alex shared how Northstar AI replaced synthetic benchmarks with curated production replay traces before enterprise launches. Committed to sending our 30-case tool-trajectory rubric before Tuesday. Also training for Marin Headlands 50K in December and prefers pre-10am slots.",
      );
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "04-desktop-debrief-keepsakes.png"),
      fullPage: false,
    });

    // 05: Desktop Relationship Journal & Coaching DNA (1440x980)
    await page.locator("#btn-debrief-back").click();
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.locator("#nav-space-journal").click();
    await page.locator("#btn-folio-contact-contact-maya").click();
    await expect(page.getByRole("heading", { name: "Maya Lin" })).toBeVisible();
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "05-desktop-journal-people-dna.png"),
      fullPage: false,
    });

    // 06: Mobile Clubhouse Calendar (430x932)
    await page.setViewportSize({ width: 430, height: 932 });
    await page.locator("#mobile-dock-clubhouse").click();
    await expect(page.locator("#btn-mobile-hero-open-pocket")).toBeVisible();
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "06-mobile-clubhouse-calendar.png"),
      fullPage: false,
    });

    // 07: Mobile Pocket Cue Cards (430x932)
    await page.locator("#btn-mobile-hero-open-pocket").click();
    await expect(page.locator("#btn-pocket-back")).toBeVisible();
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "07-mobile-pocket-cue-cards.png"),
      fullPage: false,
    });

    // 08: Mobile Debrief & Keepsakes (430x932)
    await page.locator("#btn-pocket-back").click();
    await page.locator("#mobile-dock-clubhouse").click();
    await page.locator("#btn-mobile-wrapped-debrief").click();
    await expect(page.locator("#post-meeting-notes-input")).toBeVisible();
    await page
      .locator("#post-meeting-notes-input")
      .fill(
        "Shifted Q4 release gate to customer replay traces; send 30-case rubric before Tuesday.",
      );
    await settleFontsAndIllustrations(page);
    await page.screenshot({
      path: path.join(actualDir, "08-mobile-debrief-keepsakes.png"),
      fullPage: false,
    });

    // Build side-by-side comparison PNGs + pixel similarity metrics using Chrome Canvas 2D
    const metricsSummary: Array<{
      readonly id: string;
      readonly label: string;
      readonly viewport: string;
      readonly meanChannelDeltaPct: number;
      readonly pixelSimilarityPct: number;
    }> = [];

    for (const spec of SCREEN_SPECS) {
      const mockupB64 = fs
        .readFileSync(path.join(mockupsDir, `${spec.id}.png`))
        .toString("base64");
      const actualB64 = fs
        .readFileSync(path.join(actualDir, `${spec.id}.png`))
        .toString("base64");

      const result = await page.evaluate(
        async ({ mockupDataUrl, actualDataUrl, title, w, h }) => {
          const loadImg = (src: string): Promise<HTMLImageElement> =>
            new Promise((resolve, reject) => {
              const img = new Image();
              img.onload = () => resolve(img);
              img.onerror = () => reject(new Error("Failed to decode comparison image"));
              img.src = src;
            });

          const [mockupImg, actualImg] = await Promise.all([
            loadImg(mockupDataUrl),
            loadImg(actualDataUrl),
          ]);

          // Compute normalized pixel similarity at target viewport resolution
          const sampleCanvasA = document.createElement("canvas");
          sampleCanvasA.width = w;
          sampleCanvasA.height = h;
          const ctxA = sampleCanvasA.getContext("2d");
          const sampleCanvasB = document.createElement("canvas");
          sampleCanvasB.width = w;
          sampleCanvasB.height = h;
          const ctxB = sampleCanvasB.getContext("2d");

          if (!ctxA || !ctxB) {
            throw new Error("2D canvas unavailable");
          }
          ctxA.drawImage(mockupImg, 0, 0, w, h);
          ctxB.drawImage(actualImg, 0, 0, w, h);

          const dataA = ctxA.getImageData(0, 0, w, h).data;
          const dataB = ctxB.getImageData(0, 0, w, h).data;
          let totalAbsDiff = 0;
          const pixelCount = w * h;
          for (let i = 0; i < dataA.length; i += 4) {
            totalAbsDiff +=
              Math.abs((dataA[i] ?? 0) - (dataB[i] ?? 0)) +
              Math.abs((dataA[i + 1] ?? 0) - (dataB[i + 1] ?? 0)) +
              Math.abs((dataA[i + 2] ?? 0) - (dataB[i + 2] ?? 0));
          }
          const meanChannelDeltaPct = Number(
            ((totalAbsDiff / (pixelCount * 3 * 255)) * 100).toFixed(2),
          );
          const pixelSimilarityPct = Number((100 - meanChannelDeltaPct).toFixed(2));

          // Compose crisp side-by-side comparison board
          const scale = w > 900 ? 0.65 : 1.0;
          const panelW = Math.round(w * scale);
          const panelH = Math.round(h * scale);
          const pad = 28;
          const headerH = 74;
          const boardW = pad * 3 + panelW * 2;
          const boardH = headerH + panelH + pad;

          const board = document.createElement("canvas");
          board.width = boardW;
          board.height = boardH;
          const bctx = board.getContext("2d");
          if (!bctx) {
            throw new Error("Board canvas unavailable");
          }

          bctx.fillStyle = "#F6EFEF";
          bctx.fillRect(0, 0, boardW, boardH);

          bctx.fillStyle = "#302731";
          bctx.font = "700 20px 'DM Sans', sans-serif";
          bctx.fillText(
            `${title} (${String(w)}x${String(h)}) · Similarity ${String(pixelSimilarityPct)}%`,
            pad,
            34,
          );

          bctx.fillStyle = "#6F5E6A";
          bctx.font = "700 13px 'DM Sans', sans-serif";
          bctx.fillText("APPROVED V2 MOCKUP (mockups/v2)", pad, 60);
          bctx.fillText("LIVE CHROME IMPLEMENTATION (tests/visual/actual)", pad * 2 + panelW, 60);

          bctx.strokeStyle = "#DFD2D6";
          bctx.lineWidth = 2;
          bctx.drawImage(mockupImg, pad, headerH, panelW, panelH);
          bctx.strokeRect(pad, headerH, panelW, panelH);

          bctx.drawImage(actualImg, pad * 2 + panelW, headerH, panelW, panelH);
          bctx.strokeRect(pad * 2 + panelW, headerH, panelW, panelH);

          return {
            comparisonPngB64: board.toDataURL("image/png").replace(/^data:image\/png;base64,/, ""),
            meanChannelDeltaPct,
            pixelSimilarityPct,
          };
        },
        {
          mockupDataUrl: `data:image/png;base64,${mockupB64}`,
          actualDataUrl: `data:image/png;base64,${actualB64}`,
          title: spec.label,
          w: spec.width,
          h: spec.height,
        },
      );

      fs.writeFileSync(
        path.join(comparisonsDir, `${spec.id}-side-by-side.png`),
        Buffer.from(result.comparisonPngB64, "base64"),
      );
      metricsSummary.push({
        id: spec.id,
        label: spec.label,
        viewport: `${String(spec.width)}x${String(spec.height)}`,
        meanChannelDeltaPct: result.meanChannelDeltaPct,
        pixelSimilarityPct: result.pixelSimilarityPct,
      });
    }

    fs.writeFileSync(
      path.join(visualRootDir, "metrics.json"),
      `${JSON.stringify({ generatedAtUtc: new Date().toISOString(), screens: metricsSummary }, null, 2)}\n`,
    );

    // Compose 00-side-by-side-overview.png grid of all 8 comparison boards
    const compDataUrls = SCREEN_SPECS.map((s) => ({
      id: s.id,
      dataUrl: `data:image/png;base64,${fs
        .readFileSync(path.join(comparisonsDir, `${s.id}-side-by-side.png`))
        .toString("base64")}`,
    }));

    const overviewB64 = await page.evaluate(async (items) => {
      const loadImg = (src: string): Promise<HTMLImageElement> =>
        new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error("Failed to decode board"));
          img.src = src;
        });

      const imgs = await Promise.all(items.map((it) => loadImg(it.dataUrl)));
      const cols = 2;
      const rows = Math.ceil(imgs.length / cols);
      const cellW = 1040;
      const cellH = 560;
      const gap = 28;
      const headerH = 92;
      const canvas = document.createElement("canvas");
      canvas.width = gap + cols * (cellW + gap);
      canvas.height = headerH + rows * (cellH + gap);
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        throw new Error("Overview canvas unavailable");
      }

      ctx.fillStyle = "#FFFAF8";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = "#302731";
      ctx.font = "700 28px 'Fraunces', serif";
      ctx.fillText("Brew V2 Visual Fidelity Overview · Approved Mockups vs Live Chrome", gap, 46);
      ctx.fillStyle = "#6F5E6A";
      ctx.font = "500 15px 'DM Sans', sans-serif";
      ctx.fillText(
        "All 8 approved desktop (1440px) & mobile (430px) screens captured live and compared side-by-side.",
        gap,
        72,
      );

      imgs.forEach((img, idx) => {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        const x = gap + col * (cellW + gap);
        const y = headerH + row * (cellH + gap);
        ctx.fillStyle = "#F6EFEF";
        ctx.fillRect(x, y, cellW, cellH);
        const scale = Math.min(cellW / img.width, cellH / img.height);
        const drawW = Math.round(img.width * scale);
        const drawH = Math.round(img.height * scale);
        const ox = x + Math.round((cellW - drawW) / 2);
        const oy = y + Math.round((cellH - drawH) / 2);
        ctx.drawImage(img, ox, oy, drawW, drawH);
      });

      return canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, "");
    }, compDataUrls);

    fs.writeFileSync(
      path.join(visualRootDir, "00-side-by-side-overview.png"),
      Buffer.from(overviewB64, "base64"),
    );
  });
});
