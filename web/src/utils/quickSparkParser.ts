import type { MeetingPurpose, MeetingTone } from "../api/types";

export interface ParsedQuickSpark {
  readonly counterpartName: string | null;
  readonly organization: string | null;
  readonly durationMinutes: number | null;
  readonly purpose: MeetingPurpose | null;
  readonly tone: MeetingTone | null;
  readonly objective: string | null;
}

const DURATION_REGEX = /\b(\d{1,3})\s*(?:m|min|mins|minute|minutes)\b/i;
const HALF_HOUR_REGEX = /\b(?:half[\s-]*an?[\s-]*hour|half[\s-]*hour)\b/i;
const ONE_HOUR_REGEX = /\b(?:an?\s+hour|1\s*(?:h|hr|hour))\b/i;

export function parseQuickSparkPrompt(rawInput: string): ParsedQuickSpark {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return {
      counterpartName: null,
      organization: null,
      durationMinutes: null,
      purpose: null,
      tone: null,
      objective: null,
    };
  }

  let durationMinutes: number | null = null;
  const durMatch = DURATION_REGEX.exec(trimmed);
  if (durMatch?.[1]) {
    const parsed = Number.parseInt(durMatch[1], 10);
    if (Number.isInteger(parsed) && parsed >= 5 && parsed <= 180) {
      durationMinutes = parsed;
    }
  } else if (HALF_HOUR_REGEX.test(trimmed)) {
    durationMinutes = 30;
  } else if (ONE_HOUR_REGEX.test(trimmed)) {
    durationMinutes = 60;
  }

  const lower = trimmed.toLowerCase();
  let purpose: MeetingPurpose | null = null;
  if (lower.includes("mentor")) {
    purpose = "mentorship";
  } else if (lower.includes("customer discovery") || lower.includes("user research") || lower.includes("discovery")) {
    purpose = "customer_discovery";
  } else if (lower.includes("network") || lower.includes("intro")) {
    purpose = "networking";
  } else if (lower.includes("coffee") || lower.includes("1:1") || lower.includes("catch up") || lower.includes("catch-up")) {
    purpose = "coffee_chat";
  }

  let tone: MeetingTone | null = null;
  if (lower.includes("executive") || lower.includes("structured") || lower.includes("formal")) {
    tone = "structured_executive";
  } else if (lower.includes("candid") || lower.includes("direct") || lower.includes("coaching")) {
    tone = "candid_coaching";
  } else if (lower.includes("curious") || lower.includes("exploratory") || lower.includes("deep")) {
    tone = "curious_exploratory";
  } else if (lower.includes("casual") || lower.includes("warm") || lower.includes("informal") || lower.includes("relaxed")) {
    tone = "warm_casual";
  }

  // Extract "with <Name> [(Role at Org) | at <Org>]" before "about/on/for/to discuss"
  let counterpartName: string | null = null;
  let organization: string | null = null;
  const withMatch =
    /\bwith\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})(?:\s*\(([^)]{1,60})\))?(?:\s+(?:at|from)\s+([A-Z0-9][A-Za-z0-9.&' -]{1,40}?))?(?=\s+(?:about|on|regarding|around|to\s+discuss|for)\b|[,.]|$)/.exec(
      trimmed,
    );
  if (withMatch?.[1]) {
    counterpartName = withMatch[1].trim();
    if (withMatch[3]) {
      organization = withMatch[3].trim();
    } else if (withMatch[2]) {
      const parenOrg = /\b(?:at|from)\s+([A-Z0-9][A-Za-z0-9.&' -]{1,40})$/.exec(
        withMatch[2].trim(),
      );
      organization = parenOrg?.[1]?.trim() ?? withMatch[2].trim();
    }
  }

  let objective: string | null = null;
  const objMatch = /\b(?:about|regarding|around|to\s+discuss)\s+(.+)$/i.exec(trimmed);
  if (objMatch?.[1]) {
    const cleaned = objMatch[1].trim().replace(/[.]+$/, "");
    if (cleaned.length >= 3) {
      objective = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    }
  } else if (trimmed.length >= 10) {
    objective = trimmed;
  }

  return {
    counterpartName,
    organization,
    durationMinutes,
    purpose,
    tone,
    objective,
  };
}
