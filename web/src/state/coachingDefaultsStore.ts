import type { MeetingTone } from "../api/types";

export interface CoachingStyleDefaults {
  readonly defaultDurationMinutes: number;
  readonly defaultTone: MeetingTone;
  readonly defaultStyleNotes: string;
}

export const DEFAULT_STYLE_DEFAULTS: CoachingStyleDefaults = {
  defaultDurationMinutes: 30,
  defaultTone: "warm_casual",
  defaultStyleNotes: "",
};

const VALID_TONES: ReadonlySet<MeetingTone> = new Set<MeetingTone>([
  "warm_casual",
  "curious_exploratory",
  "structured_executive",
  "candid_coaching",
]);

const STORAGE_PREFIX = "brew.coaching.defaults.v1:";

export function loadCoachingDefaults(userId: string | null): CoachingStyleDefaults {
  if (!userId || typeof window === "undefined") {
    return DEFAULT_STYLE_DEFAULTS;
  }
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${userId}`);
    if (!raw) {
      return DEFAULT_STYLE_DEFAULTS;
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const dur =
      typeof parsed["defaultDurationMinutes"] === "number" &&
      parsed["defaultDurationMinutes"] >= 5 &&
      parsed["defaultDurationMinutes"] <= 180
        ? parsed["defaultDurationMinutes"]
        : 30;
    const rawTone = parsed["defaultTone"];
    const tone: MeetingTone =
      typeof rawTone === "string" && VALID_TONES.has(rawTone as MeetingTone)
        ? (rawTone as MeetingTone)
        : "warm_casual";
    const notes =
      typeof parsed["defaultStyleNotes"] === "string" ? parsed["defaultStyleNotes"] : "";
    return {
      defaultDurationMinutes: dur,
      defaultTone: tone,
      defaultStyleNotes: notes,
    };
  } catch {
    return DEFAULT_STYLE_DEFAULTS;
  }
}

export function saveCoachingDefaults(userId: string, next: CoachingStyleDefaults): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${userId}`, JSON.stringify(next));
  } catch {
    // Ignore storage quota errors cleanly.
  }
}
