import type { MeetingPurpose } from "../api/types";

export type CalendarEventSource = "gcal" | "ics";

export type CalendarTemporalStatus = "wrapped" | "up_next" | "upcoming";

export interface CalendarCoffeeChatEvent {
  readonly id: string;
  readonly title: string;
  readonly counterpartName: string;
  readonly counterpartTitle: string | null;
  readonly counterpartOrganization: string | null;
  readonly counterpartRole: string | null;
  readonly purpose: MeetingPurpose;
  readonly scheduledStartIso: string;
  readonly scheduledEndIso: string;
  readonly durationMinutes: number;
  readonly notesExcerpt: string | null;
  readonly source: CalendarEventSource;
  readonly temporalStatus: CalendarTemporalStatus;
}
