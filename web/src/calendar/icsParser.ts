import type { MeetingPurpose } from "../api/types";
import type {
  CalendarCoffeeChatEvent,
  CalendarEventSource,
  CalendarTemporalStatus,
} from "./calendarTypes";

const BREW_HASHTAG_REGEX = /(?:^|[\s([,;])#brew\b/i;

const GROUP_MEETING_TITLE_REGEX =
  /\b(?:team|all[- ]hands|stand[- ]?up|town\s+hall|sprint|retro(?:spective)?|scrum|staff\s+meeting|guild|committee|board\s+meeting)\b/i;

const EXPLICIT_SUMMARY_CHAT_REGEX =
  /(?:(?<![0-9a-z-])1[:/-]1(?![0-9a-z-])|\b(?:coffee\s+chat|mentorship\s+coffee|networking\s+chat|intro\s+chat|catch[- ]up)\b|\b(?:coffee|mentorship)\s*:)/i;

const EXPLICIT_DESCRIPTION_PHRASE_REGEX =
  /\b(?:coffee\s+chat|mentorship\s+coffee|networking\s+chat|intro\s+chat)\b/i;

export interface CoffeeChatFilterOptions {
  readonly attendeeCount?: number | undefined;
}

export function hasExplicitBrewHashtag(summary: string, description: string = ""): boolean {
  return BREW_HASHTAG_REGEX.test(summary) || BREW_HASHTAG_REGEX.test(description);
}

export function isExplicitCoffeeChatEvent(
  summary: string,
  description: string = "",
  options?: CoffeeChatFilterOptions,
): boolean {
  if (hasExplicitBrewHashtag(summary, description)) {
    return true;
  }
  if (options?.attendeeCount !== undefined && options.attendeeCount > 2) {
    return false;
  }
  if (GROUP_MEETING_TITLE_REGEX.test(summary)) {
    return false;
  }
  return (
    EXPLICIT_SUMMARY_CHAT_REGEX.test(summary) ||
    EXPLICIT_DESCRIPTION_PHRASE_REGEX.test(description)
  );
}

export function inferPurposeFromCalendarSummary(summary: string): MeetingPurpose {
  const lower = summary.toLowerCase();
  if (lower.includes("mentor")) {
    return "mentorship";
  }
  if (lower.includes("discovery") || lower.includes("customer")) {
    return "customer_discovery";
  }
  if (lower.includes("network") || lower.includes("intro")) {
    return "networking";
  }
  return "coffee_chat";
}

export function classifyTemporalStatus(
  startMs: number,
  endMs: number,
  nowMs: number,
): CalendarTemporalStatus {
  if (endMs <= nowMs) {
    return "wrapped";
  }
  const twoHoursMs = 2 * 60 * 60 * 1000;
  if (startMs - nowMs <= twoHoursMs) {
    return "up_next";
  }
  return "upcoming";
}

export function extractCounterpartDetails(
  summary: string,
  selfDisplayName?: string | readonly string[] | null,
): {
  readonly counterpartName: string;
  readonly counterpartOrganization: string | null;
  readonly counterpartRole: string | null;
} {
  let body = summary
    .replace(/^(?:mentorship\s+coffee|coffee\s+chat|mentorship|networking\s+chat|1:1|1-1)\s*[:·-]\s*/i, "")
    .trim();

  let counterpartOrganization: string | null = null;
  const parenMatch = /\(([^()]{2,60})\)\s*$/.exec(body);
  if (parenMatch?.[1]) {
    counterpartOrganization = parenMatch[1].trim();
    body = body.slice(0, parenMatch.index).trim();
  }

  // Handle "Alice <> Maya Lin" or "Maya Lin / Alice Chen"
  const pairParts = body.split(/\s*(?:<>|<->|\/|\+|&|\bwith\b)\s*/i).map((p) => p.trim()).filter(Boolean);
  let chosenName = body;
  if (pairParts.length >= 2) {
    const rawNames = Array.isArray(selfDisplayName)
      ? selfDisplayName
      : typeof selfDisplayName === "string"
        ? [selfDisplayName]
        : [];
    const selfCandidates = rawNames
      .map((name) => name.trim().toLowerCase())
      .filter((name) => name.length > 0)
      .map((full) => ({
        full,
        first: full.split(/\s+/)[0] ?? "",
      }));
    const other = pairParts.find((part) => {
      const lower = part.toLowerCase();
      if (selfCandidates.length === 0) {
        return true;
      }
      return !selfCandidates.some(
        (self) =>
          lower === self.full ||
          (self.first.length > 0 && (lower === self.first || lower.startsWith(`${self.first} `))),
      );
    });
    chosenName = other ?? pairParts[pairParts.length - 1] ?? body;
  }

  const counterpartRole = summary.toLowerCase().includes("mentor")
    ? "Mentor"
    : summary.toLowerCase().includes("intro")
      ? "Networking Contact"
      : null;

  return {
    counterpartName: chosenName || "Coffee Chat Guest",
    counterpartOrganization,
    counterpartRole,
  };
}

function unfoldIcsLines(rawIcs: string): string[] {
  const normalized = rawIcs.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const unfolded = normalized.replace(/\n[ \t]/g, "");
  return unfolded.split("\n");
}

function parseIcsTimestampMs(rawVal: string): number | null {
  const cleaned = rawVal.trim();
  // Format: YYYYMMDDTHHMMSSZ or YYYYMMDDTHHMMSS
  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$/.exec(cleaned);
  if (match) {
    const [, y, m, d, hh, mm, ss, z] = match;
    if (z === "Z") {
      return Date.UTC(
        Number(y),
        Number(m) - 1,
        Number(d),
        Number(hh),
        Number(mm),
        Number(ss),
      );
    }
    return new Date(
      Number(y),
      Number(m) - 1,
      Number(d),
      Number(hh),
      Number(mm),
      Number(ss),
    ).getTime();
  }
  const fallback = Date.parse(cleaned);
  return Number.isNaN(fallback) ? null : fallback;
}

function unescapeIcsText(value: string): string {
  return value
    .replace(/\\n/gi, " ")
    .replace(/\\,/g, ",")
    .replace(/\\;/g, ";")
    .replace(/\\\\/g, "\\")
    .replace(/\u2014/g, ":")
    .trim();
}

export function parseIcsCalendarEvents(
  rawIcs: string,
  options?: {
    readonly nowMs?: number | undefined;
    readonly selfDisplayName?: string | readonly string[] | null | undefined;
    readonly source?: CalendarEventSource | undefined;
  },
): CalendarCoffeeChatEvent[] {
  const nowMs = options?.nowMs ?? Date.now();
  const source: CalendarEventSource = options?.source ?? "ics";
  const lines = unfoldIcsLines(rawIcs);

  const results: CalendarCoffeeChatEvent[] = [];
  let inEvent = false;
  let fields: Record<string, string> = {};
  let humanAttendeeCount = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.toUpperCase() === "BEGIN:VEVENT") {
      inEvent = true;
      fields = {};
      humanAttendeeCount = 0;
      continue;
    }
    if (trimmed.toUpperCase() === "END:VEVENT") {
      inEvent = false;
      const status = (fields["STATUS"] ?? "").toUpperCase();
      if (status === "CANCELLED") {
        continue;
      }

      const summary = unescapeIcsText(fields["SUMMARY"] ?? "");
      const description = unescapeIcsText(fields["DESCRIPTION"] ?? "");
      if (
        !summary ||
        !isExplicitCoffeeChatEvent(summary, description, {
          attendeeCount: humanAttendeeCount > 0 ? humanAttendeeCount : undefined,
        })
      ) {
        continue;
      }

      const startMs = parseIcsTimestampMs(fields["DTSTART"] ?? "");
      const endMs = parseIcsTimestampMs(fields["DTEND"] ?? "");
      if (startMs === null) {
        continue;
      }
      const resolvedEndMs = endMs !== null && endMs > startMs ? endMs : startMs + 30 * 60_000;
      const rawMinutes = Math.round((resolvedEndMs - startMs) / 60_000);
      if (rawMinutes < 5 || rawMinutes > 180) {
        continue;
      }

      const extracted = extractCounterpartDetails(summary, options?.selfDisplayName);
      const uid = unescapeIcsText(fields["UID"] ?? `ics_${String(startMs)}_${String(results.length)}`);

      results.push({
        id: uid,
        title: summary,
        counterpartName: extracted.counterpartName,
        counterpartTitle: null,
        counterpartOrganization: extracted.counterpartOrganization,
        counterpartRole: extracted.counterpartRole,
        purpose: inferPurposeFromCalendarSummary(summary),
        scheduledStartIso: new Date(startMs).toISOString(),
        scheduledEndIso: new Date(resolvedEndMs).toISOString(),
        durationMinutes: rawMinutes,
        notesExcerpt: description ? description.slice(0, 280) : null,
        source,
        temporalStatus: classifyTemporalStatus(startMs, resolvedEndMs, nowMs),
      });
      continue;
    }

    if (inEvent) {
      const colonIdx = trimmed.indexOf(":");
      if (colonIdx > 0) {
        const rawKey = trimmed.slice(0, colonIdx);
        const rawVal = trimmed.slice(colonIdx + 1);
        const baseKey = (rawKey.split(";")[0] ?? rawKey).toUpperCase();
        if (baseKey === "ATTENDEE") {
          const upperKeyParams = rawKey.toUpperCase();
          const isResource =
            upperKeyParams.includes("CUTYPE=ROOM") ||
            upperKeyParams.includes("CUTYPE=RESOURCE");
          if (!isResource) {
            humanAttendeeCount += 1;
          }
        } else {
          fields[baseKey] = rawVal;
        }
      }
    }
  }

  return results.sort(
    (a, b) => Date.parse(a.scheduledStartIso) - Date.parse(b.scheduledStartIso),
  );
}
