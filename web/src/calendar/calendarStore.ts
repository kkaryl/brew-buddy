import type { ContactResponse } from "../api/types";
import type { CalendarCoffeeChatEvent } from "./calendarTypes";
import { parseIcsCalendarEvents } from "./icsParser";

const STORAGE_PREFIX = "brew.v2.calendar.events:";
const DEMO_DISMISSED_PREFIX = "brew.v2.calendar.demo_disabled:";

function formatIcsUtc(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number): string => String(n).padStart(2, "0");
  return (
    `${String(d.getUTCFullYear())}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T` +
    `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`
  );
}

/**
 * Generates deterministic `.ics` fixture events anchored around `nowMs` for local mock/demo mode
 * so developers and reviewers immediately experience read-only Google Calendar coffee chat detection.
 */
export function buildDemoCalendarIcsFixture(nowMs: number = Date.now(), selfFirstName: string = "Alice"): string {
  const wrappedStart = nowMs - 150 * 60_000; // 2.5h ago
  const wrappedEnd = wrappedStart + 30 * 60_000;

  const upNextStart = nowMs + 42 * 60_000; // Starts in 42 min
  const upNextEnd = upNextStart + 30 * 60_000;

  const thuStart = nowMs + 44 * 60 * 60_000; // +~2 days, 45m
  const thuEnd = thuStart + 45 * 60_000;

  const friStart = nowMs + 72 * 60 * 60_000; // +3 days, 15m
  const friEnd = friStart + 15 * 60_000;

  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Brew//Local Google Calendar Fixture//EN",
    "BEGIN:VEVENT",
    "UID:gcal-demo-wrapped-alex",
    `DTSTART:${formatIcsUtc(wrappedStart)}`,
    `DTEND:${formatIcsUtc(wrappedEnd)}`,
    "SUMMARY:Coffee Chat: Alex Morgan (Northstar AI)",
    "DESCRIPTION:Catch up on golden evaluation datasets and AI adoption lessons. #brew",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:gcal-demo-upnext-maya",
    `DTSTART:${formatIcsUtc(upNextStart)}`,
    `DTEND:${formatIcsUtc(upNextEnd)}`,
    `SUMMARY:Coffee Chat: ${selfFirstName} <> Maya Lin (CloudScale)`,
    "DESCRIPTION:Discuss multi-region failover drills and service-mesh discovery. #brew",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:gcal-demo-samir",
    `DTSTART:${formatIcsUtc(thuStart)}`,
    `DTEND:${formatIcsUtc(thuEnd)}`,
    "SUMMARY:Mentorship Coffee: Dr. Samir Patel",
    "DESCRIPTION:45m quarterly engineering mentorship catch-up.",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:gcal-demo-priya",
    `DTSTART:${formatIcsUtc(friStart)}`,
    `DTEND:${formatIcsUtc(friEnd)}`,
    "SUMMARY:Coffee Chat: Priya Nair (Design Systems)",
    "DESCRIPTION:Tight 15m intro slot on Figma token pipelines.",
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
}

export function loadStoredCalendarEvents(
  userId: string | null,
  options?: {
    readonly isLocalMock?: boolean;
    readonly userDisplayName?: string | null;
    readonly nowMs?: number;
  },
): CalendarCoffeeChatEvent[] {
  const nowMs = options?.nowMs ?? Date.now();
  const selfFirst =
    (options?.userDisplayName ?? "Alice").trim().split(/\s+/)[0] || "Alice";

  if (userId && typeof window !== "undefined") {
    try {
      const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${userId}`);
      if (raw) {
        const parsed = JSON.parse(raw) as unknown;
        if (Array.isArray(parsed)) {
          return parsed as CalendarCoffeeChatEvent[];
        }
      }
      const demoDisabled =
        window.localStorage.getItem(`${DEMO_DISMISSED_PREFIX}${userId}`) === "1";
      if (demoDisabled) {
        return [];
      }
    } catch {
      // Fall back to demo fixture check below.
    }
  }

  if (options?.isLocalMock) {
    const ics = buildDemoCalendarIcsFixture(nowMs, selfFirst);
    return parseIcsCalendarEvents(ics, {
      nowMs,
      selfDisplayName: options.userDisplayName ?? selfFirst,
      source: "gcal",
    });
  }

  return [];
}

export function saveStoredCalendarEvents(
  userId: string | null,
  events: readonly CalendarCoffeeChatEvent[],
): void {
  if (!userId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${userId}`, JSON.stringify(events));
    if (events.length === 0) {
      window.localStorage.setItem(`${DEMO_DISMISSED_PREFIX}${userId}`, "1");
    } else {
      window.localStorage.removeItem(`${DEMO_DISMISSED_PREFIX}${userId}`);
    }
  } catch {
    // Ignore storage quota errors gracefully.
  }
}

export function matchCalendarEventContact(
  event: CalendarCoffeeChatEvent,
  contacts: readonly ContactResponse[],
): ContactResponse | null {
  const target = event.counterpartName.trim().toLowerCase();
  if (!target) {
    return null;
  }
  const exact = contacts.find((c) => c.name.trim().toLowerCase() === target);
  if (exact) {
    return exact;
  }
  return (
    contacts.find((c) => {
      const cName = c.name.trim().toLowerCase();
      return cName.includes(target) || target.includes(cName);
    }) ?? null
  );
}

export function formatCalendarCountdown(startIso: string, nowMs: number = Date.now()): string {
  const startMs = Date.parse(startIso);
  if (Number.isNaN(startMs)) {
    return "Upcoming";
  }
  const diffMin = Math.round((startMs - nowMs) / 60_000);
  if (diffMin <= 0 && diffMin > -45) {
    return "Happening now";
  }
  if (diffMin < 0) {
    return "Wrapped";
  }
  if (diffMin < 60) {
    return `Starts in ${String(diffMin)} min`;
  }
  const hours = Math.round(diffMin / 60);
  if (hours < 24) {
    return `Starts in ${String(hours)}h`;
  }
  const days = Math.round(hours / 24);
  return `In ${String(days)}d`;
}

export function formatCalendarTimeRange(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "";
  }
  const fmt = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${fmt.format(start)} - ${fmt.format(end)}`;
}

export function formatCalendarDayLabel(startIso: string, nowMs: number = Date.now()): string {
  const start = new Date(startIso);
  if (Number.isNaN(start.getTime())) {
    return "";
  }
  const now = new Date(nowMs);
  if (
    start.getFullYear() === now.getFullYear() &&
    start.getMonth() === now.getMonth() &&
    start.getDate() === now.getDate()
  ) {
    return "Today";
  }
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(start);
}
