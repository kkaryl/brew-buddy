import { loadGoogleIdentityServicesScript } from "../auth/googleFirebaseAuth";
import type { CalendarCoffeeChatEvent } from "./calendarTypes";
import {
  classifyTemporalStatus,
  extractCounterpartDetails,
  inferPurposeFromCalendarSummary,
  isExplicitCoffeeChatEvent,
} from "./icsParser";

export const GOOGLE_CALENDAR_READONLY_SCOPE =
  "https://www.googleapis.com/auth/calendar.events.readonly";

const CALENDAR_TIMEOUT_MS = 10_000;

interface GoogleCalendarApiEventItem {
  readonly id?: string;
  readonly status?: string;
  readonly summary?: string;
  readonly description?: string;
  readonly start?: { readonly dateTime?: string; readonly date?: string };
  readonly end?: { readonly dateTime?: string; readonly date?: string };
  readonly attendees?: readonly {
    readonly email?: string;
    readonly displayName?: string;
    readonly self?: boolean;
    readonly resource?: boolean;
  }[];
}

interface GoogleCalendarEventsListResponse {
  readonly items?: readonly GoogleCalendarApiEventItem[];
}

/**
 * Request a read-only Google Calendar OAuth 2.0 access token via Google Identity Services.
 * Strictly requests `calendar.events.readonly` and never writes or mutates calendar events.
 */
export async function requestGoogleCalendarReadOnlyToken(clientId: string): Promise<string> {
  await loadGoogleIdentityServicesScript();
  const oauth2 = window.google?.accounts?.oauth2;
  if (!oauth2?.initTokenClient) {
    throw new Error("Google Identity Services OAuth client is unavailable in this browser.");
  }

  return new Promise<string>((resolve, reject) => {
    const tokenClient = oauth2.initTokenClient({
      client_id: clientId,
      scope: GOOGLE_CALENDAR_READONLY_SCOPE,
      prompt: "consent",
      callback: (resp) => {
        if (resp.error) {
          reject(
            new Error(
              resp.error_description
                ? `Google Calendar authorization failed: ${resp.error_description}`
                : `Google Calendar authorization failed (${resp.error}).`,
            ),
          );
          return;
        }
        const token = resp.access_token?.trim();
        if (!token) {
          reject(new Error("Google Calendar authorization did not return an access token."));
          return;
        }
        resolve(token);
      },
      error_callback: (err) => {
        if (err.type === "popup_closed") {
          reject(new Error("Google Calendar permission popup was closed."));
          return;
        }
        reject(new Error(err.message ?? "Could not open Google Calendar permission popup."));
      },
    });
    tokenClient.requestAccessToken({ prompt: "consent" });
  });
}

/**
 * Fetch upcoming and recent coffee chat events from the user's primary Google Calendar
 * within a 24-hour lookback to 7-day lookahead window (strictly read-only).
 */
export async function fetchReadOnlyGoogleCalendarEvents(
  accessToken: string,
  options?: {
    readonly nowMs?: number | undefined;
    readonly selfDisplayName?: string | readonly string[] | null | undefined;
  },
): Promise<CalendarCoffeeChatEvent[]> {
  const nowMs = options?.nowMs ?? Date.now();
  const timeMin = new Date(nowMs - 24 * 60 * 60 * 1000).toISOString();
  const timeMax = new Date(nowMs + 7 * 24 * 60 * 60 * 1000).toISOString();

  const params = new URLSearchParams({
    timeMin,
    timeMax,
    singleEvents: "true",
    orderBy: "startTime",
    maxResults: "50",
  });

  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), CALENDAR_TIMEOUT_MS);

  try {
    const response = await fetch(
      `https://www.googleapis.com/calendar/v3/calendars/primary/events?${params.toString()}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: "application/json",
        },
        signal: controller.signal,
      },
    );

    if (!response.ok) {
      throw new Error(`Google Calendar sync failed with HTTP ${String(response.status)}.`);
    }

    const payload = (await response.json()) as GoogleCalendarEventsListResponse;
    const rawItems = payload.items ?? [];
    const results: CalendarCoffeeChatEvent[] = [];

    for (const item of rawItems) {
      if (item.status === "cancelled") {
        continue;
      }
      const summary = (item.summary ?? "").replace(/\u2014/g, ":").trim();
      const description = (item.description ?? "").replace(/\u2014/g, ":").trim();
      const humanAttendees = (item.attendees ?? []).filter((att) => !att.resource);
      if (
        !summary ||
        !isExplicitCoffeeChatEvent(summary, description, {
          attendeeCount: item.attendees ? humanAttendees.length : undefined,
        })
      ) {
        continue;
      }

      const startIso = item.start?.dateTime;
      const endIso = item.end?.dateTime;
      if (!startIso || !endIso) {
        // Ignore all-day date-only blocks.
        continue;
      }

      const startMs = Date.parse(startIso);
      const endMs = Date.parse(endIso);
      if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs <= startMs) {
        continue;
      }

      const durationMinutes = Math.round((endMs - startMs) / 60_000);
      if (durationMinutes < 5 || durationMinutes > 180) {
        continue;
      }

      const extracted = extractCounterpartDetails(summary, options?.selfDisplayName);
      const externalAttendee = humanAttendees.find((att) => !att.self && att.displayName);
      const counterpartName =
        extracted.counterpartName !== "Coffee Chat Guest"
          ? extracted.counterpartName
          : (externalAttendee?.displayName?.trim() ?? "Coffee Chat Guest");

      results.push({
        id: item.id ?? `gcal_${String(startMs)}`,
        title: summary,
        counterpartName,
        counterpartTitle: null,
        counterpartOrganization: extracted.counterpartOrganization,
        counterpartRole: extracted.counterpartRole,
        purpose: inferPurposeFromCalendarSummary(summary),
        scheduledStartIso: new Date(startMs).toISOString(),
        scheduledEndIso: new Date(endMs).toISOString(),
        durationMinutes,
        notesExcerpt: description ? description.slice(0, 280) : null,
        source: "gcal",
        temporalStatus: classifyTemporalStatus(startMs, endMs, nowMs),
      });
    }

    return results;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Google Calendar request timed out after 10s. Please try again.");
    }
    throw err instanceof Error ? err : new Error("Unable to read Google Calendar events.");
  } finally {
    globalThis.clearTimeout(timer);
  }
}
