/**
 * Client-side persistence for starred Pocket Glance cue cards per brief (`localStorage`).
 * Defaults cleanly to starring the top 2 questions (or first question when only 1 exists)
 * when a user has not customized stars for a given brief yet.
 */

const STORAGE_PREFIX = "brew.v2.starred_questions:";

export function loadStarredQuestionIds(
  userId: string | null,
  briefId: string,
  allQuestionIds: readonly string[],
): ReadonlySet<string> {
  const defaultIds = new Set<string>(allQuestionIds.slice(0, Math.min(2, allQuestionIds.length)));
  if (!userId || !briefId || typeof window === "undefined") {
    return defaultIds;
  }

  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${userId}:${briefId}`);
    if (!raw) {
      return defaultIds;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return defaultIds;
    }
    const validSet = new Set<string>(allQuestionIds);
    const filtered = parsed.filter(
      (id): id is string => typeof id === "string" && validSet.has(id),
    );
    return new Set<string>(filtered);
  } catch {
    return defaultIds;
  }
}

export function saveStarredQuestionIds(
  userId: string | null,
  briefId: string,
  starredIds: ReadonlySet<string>,
): void {
  if (!userId || !briefId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      `${STORAGE_PREFIX}${userId}:${briefId}`,
      JSON.stringify(Array.from(starredIds)),
    );
  } catch {
    // Ignore storage quota errors gracefully.
  }
}

export function toggleQuestionStar(
  current: ReadonlySet<string>,
  questionId: string,
): Set<string> {
  const next = new Set<string>(current);
  if (next.has(questionId)) {
    next.delete(questionId);
  } else {
    next.add(questionId);
  }
  return next;
}
