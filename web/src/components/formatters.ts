import { BrewApiError } from "../api/client";
import type {
  ErrorDetailItem,
  MeetingPurpose,
  MeetingTone,
  MemoryEpistemicStatus,
  MemoryLifecycleState,
  MemoryScope,
  MemorySourceType,
  MemoryType,
} from "../api/types";

export interface FeedbackNotice {
  readonly kind: "error" | "success" | "info";
  readonly title: string;
  readonly message?: string;
  readonly details?: readonly ErrorDetailItem[];
  readonly traceId?: string | null;
}

export function errorToFeedbackNotice(
  err: unknown,
  fallbackTitle: string,
): FeedbackNotice {
  if (err instanceof BrewApiError) {
    return {
      kind: "error",
      title: fallbackTitle,
      message: err.message,
      details: err.details,
      traceId: err.traceId,
    };
  }
  if (err instanceof Error) {
    return {
      kind: "error",
      title: fallbackTitle,
      message: err.message,
    };
  }
  return {
    kind: "error",
    title: fallbackTitle,
    message: "An unexpected error occurred.",
  };
}

export const MEETING_PURPOSE_OPTIONS: readonly {
  readonly value: MeetingPurpose;
  readonly label: string;
}[] = [
  { value: "coffee_chat", label: "Coffee Chat" },
  { value: "networking", label: "Networking" },
  { value: "mentorship", label: "Mentorship" },
  { value: "customer_discovery", label: "Customer Discovery" },
];

export const MEETING_TONE_OPTIONS: readonly {
  readonly value: MeetingTone;
  readonly label: string;
}[] = [
  { value: "warm_casual", label: "Warm & Casual" },
  { value: "curious_exploratory", label: "Curious & Exploratory" },
  { value: "structured_executive", label: "Structured Executive" },
  { value: "candid_coaching", label: "Candid Coaching" },
];

export const DURATION_PRESETS: readonly number[] = [15, 30, 45, 60];

export const MEMORY_TYPE_OPTIONS: readonly {
  readonly value: MemoryType;
  readonly label: string;
}[] = [
  { value: "counterpart_background", label: "Counterpart Context" },
  { value: "shared_interest", label: "Shared Interest" },
  { value: "follow_up_commitment", label: "Follow-Up" },
  { value: "relationship_note", label: "Relationship Note" },
  { value: "communication_preference", label: "Communication Preference" },
  { value: "agenda_preference", label: "Agenda Preference" },
];

export function formatPurposeLabel(purpose: MeetingPurpose): string {
  const match = MEETING_PURPOSE_OPTIONS.find((opt) => opt.value === purpose);
  return match ? match.label : purpose;
}

export function formatToneLabel(tone: MeetingTone): string {
  const match = MEETING_TONE_OPTIONS.find((opt) => opt.value === tone);
  return match ? match.label : tone;
}

export function formatMemoryTypeLabel(memoryType: MemoryType): string {
  const match = MEMORY_TYPE_OPTIONS.find((opt) => opt.value === memoryType);
  return match ? match.label : memoryType;
}

export function formatMemoryScopeLabel(scope: MemoryScope): string {
  return scope === "contact" ? "Counterpart Memory" : "Personal Preference";
}

export function formatEpistemicLabel(status: MemoryEpistemicStatus): string {
  return status === "user_reported_observation"
    ? "Session-attributed note"
    : "User-stated preference";
}

export function formatLifecycleLabel(state: MemoryLifecycleState): string {
  switch (state) {
    case "proposed":
      return "Proposed";
    case "approved":
      return "Approved";
    case "rejected":
      return "Rejected";
    case "superseded":
      return "Superseded";
    case "deleted":
      return "Deleted";
  }
}

export function formatSourceTypeLabel(sourceType: MemorySourceType): string {
  switch (sourceType) {
    case "meeting_notes":
      return "Meeting notes";
    case "brief_refinement":
      return "Brief refinement";
    case "direct_user_input":
      return "Direct input";
  }
}

export function formatShortTimestamp(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return isoTimestamp;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

export interface ContactFieldErrors {
  readonly name?: string;
  readonly title?: string;
  readonly role?: string;
  readonly organization?: string;
  readonly context_notes?: string;
}

export function validateContactForm(fields: {
  readonly name: string;
  readonly title: string;
  readonly role: string;
  readonly organization: string;
  readonly contextNotes: string;
}): ContactFieldErrors {
  const errors: Record<string, string> = {};
  const name = fields.name.trim();
  if (!name) {
    errors["name"] = "Counterpart name is required.";
  } else if (name.length > 120) {
    errors["name"] = "Name must be 120 characters or fewer.";
  }

  if (fields.title.trim().length > 120) {
    errors["title"] = "Title must be 120 characters or fewer.";
  }
  if (fields.role.trim().length > 120) {
    errors["role"] = "Role must be 120 characters or fewer.";
  }
  if (fields.organization.trim().length > 160) {
    errors["organization"] = "Organization must be 160 characters or fewer.";
  }

  const notes = fields.contextNotes.trim();
  if (notes.length > 0 && notes.length < 3) {
    errors["context_notes"] = "Context notes must be at least 3 characters when provided.";
  } else if (notes.length > 2000) {
    errors["context_notes"] = "Context notes must be 2,000 characters or fewer.";
  }

  return errors as ContactFieldErrors;
}

export interface BriefGenerationFieldErrors {
  readonly meeting_objective?: string;
  readonly duration_minutes?: string;
  readonly preferred_question_count?: string;
  readonly communication_style_notes?: string;
}

export function validateBriefGenerationForm(fields: {
  readonly meetingObjective: string;
  readonly durationMinutes: number;
  readonly preferredQuestionCount: string;
  readonly communicationStyleNotes: string;
}): BriefGenerationFieldErrors {
  const errors: Record<string, string> = {};
  const objective = fields.meetingObjective.trim();
  if (objective.length < 3) {
    errors["meeting_objective"] = "Enter a meeting objective (at least 3 characters).";
  } else if (objective.length > 500) {
    errors["meeting_objective"] = "Meeting objective must be 500 characters or fewer.";
  }

  if (
    !Number.isInteger(fields.durationMinutes) ||
    fields.durationMinutes < 5 ||
    fields.durationMinutes > 180
  ) {
    errors["duration_minutes"] = "Duration must be between 5 and 180 minutes.";
  }

  const rawCount = fields.preferredQuestionCount.trim();
  if (rawCount) {
    const parsed = Number.parseInt(rawCount, 10);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 15) {
      errors["preferred_question_count"] = "Question count must be between 1 and 15.";
    }
  }

  const styleNotes = fields.communicationStyleNotes.trim();
  if (styleNotes.length > 0 && styleNotes.length < 3) {
    errors["communication_style_notes"] = "Style notes must be at least 3 characters.";
  } else if (styleNotes.length > 1000) {
    errors["communication_style_notes"] = "Style notes must be 1,000 characters or fewer.";
  }

  return errors as BriefGenerationFieldErrors;
}
