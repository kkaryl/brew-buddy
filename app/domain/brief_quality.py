"""Deterministic quality checks and refinement instruction parsing for preparation briefs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    BriefPreparationContext,
    Meeting,
    PreparationBrief,
)
from app.domain.ports import GeneratedBriefContent
from app.domain.types import MeetingDurationMinutes, MeetingPurpose, MeetingTone

_WORD_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")

_QUESTION_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "are",
        "been",
        "before",
        "between",
        "both",
        "can",
        "could",
        "did",
        "does",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "into",
        "just",
        "like",
        "love",
        "make",
        "more",
        "most",
        "much",
        "over",
        "really",
        "share",
        "should",
        "some",
        "such",
        "tell",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "today",
        "very",
        "walk",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "with",
        "would",
        "you",
        "your",
    }
)

_GOAL_LINK_ANCHOR_TERMS = frozenset(
    {
        "agenda",
        "align",
        "approach",
        "architecture",
        "bottleneck",
        "career",
        "challenge",
        "chat",
        "coaching",
        "connection",
        "context",
        "conversation",
        "criteria",
        "customer",
        "decision",
        "depth",
        "direction",
        "discovery",
        "discussion",
        "domain",
        "engineering",
        "evaluation",
        "example",
        "experience",
        "explore",
        "feedback",
        "focus",
        "follow",
        "future",
        "goal",
        "growth",
        "guidance",
        "history",
        "hypothesis",
        "impact",
        "insight",
        "leadership",
        "learn",
        "lesson",
        "mentor",
        "mentorship",
        "metric",
        "misconception",
        "networking",
        "next",
        "nuance",
        "objective",
        "onboarding",
        "opportunity",
        "outcome",
        "pain",
        "perspective",
        "plan",
        "practical",
        "practice",
        "priorit",
        "problem",
        "product",
        "project",
        "purpose",
        "question",
        "rapport",
        "reciprocity",
        "relationship",
        "reliability",
        "resource",
        "revised",
        "revision",
        "roadmap",
        "role",
        "scale",
        "scaling",
        "scope",
        "shift",
        "signal",
        "solution",
        "staff",
        "step",
        "story",
        "strategy",
        "system",
        "team",
        "technical",
        "thread",
        "timebox",
        "trade",
        "transition",
        "understand",
        "value",
        "workflow",
    }
)

_FLATTERY_AND_CLICHE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("generic 'pick your brain' cliché", re.compile(r"\bpick your brain\b", re.IGNORECASE)),
    (
        "generic 'keeps you up at night' cliché",
        re.compile(r"\bkeeps you up at night\b", re.IGNORECASE),
    ),
    (
        "excessive sycophantic flattery",
        re.compile(
            r"\b(?:true visionary|legendary career|greatest leader|deeply humbled|"
            r"world-famous genius|unparalleled brilliance)\b",
            re.IGNORECASE,
        ),
    ),
)

_OVERLY_FORMAL_PATTERNS = re.compile(
    r"\b(?:pursuant to|herewith|heretofore|dear sir or madam|esteemed colleague|"
    r"humbly request your audience)\b",
    re.IGNORECASE,
)

_OVERLY_SLANGY_EXECUTIVE_PATTERNS = re.compile(
    r"\b(?:what's up dude|vibe check|spill the tea|lowkey|no cap)\b",
    re.IGNORECASE,
)

_UNSUPPORTED_BIO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "unsupported academic credential or university",
        re.compile(
            r"\b(?:phd|mba|b\.s\.|m\.s\.|graduated from|alumnus of|alumni of|"
            r"studied at|degree from)\b(?:\s+[A-Za-z0-9.&'-]+){0,4}",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported past employer, tenure, or founding claim",
        re.compile(
            r"\b(?:previously worked at|formerly at|former (?:vp|director|cto|ceo|engineer|"
            r"lead|manager) at|co-founded|founded|spent \d+\+?\s+years at)\b"
            r"(?:\s+[A-Za-z0-9.&'-]+){0,4}",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported award, publication, or patent claim",
        re.compile(
            r"\b(?:keynote speaker at|authored the book|published a paper|"
            r"patent holder|won the [a-z0-9 -]+ award)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "private personal characteristic inference",
        re.compile(
            r"\b(?:married to|marital status|has \d+ children|has kids|pregnant|"
            r"religious beliefs|political affiliation|medical condition|personal net worth)\b",
            re.IGNORECASE,
        ),
    ),
)

_DURATION_OVERRIDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:only have|shorten(?:ed)?(?:\s+it|\s+agenda)?\s+to|tighten(?:ed)?(?:\s+agenda)?\s+to|"
        r"cut(?:\s+it)?\s+to|down to|make it|cap(?:\s+it)?\s+at|have(?:\s+just|\s+only)?)\s+"
        r"(\d{1,3})\s*(?:-|\s)?(?:minutes?|mins?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,3})\s*(?:-|\s)?(?:minute|min)\s+(?:chat|meeting|call|session|sync|slot|agenda)\b",
        re.IGNORECASE,
    ),
)

_ENGINEERING_CAREER_TERMS = frozenset(
    {
        "architecture",
        "career",
        "code",
        "coding",
        "design",
        "distributed",
        "engineer",
        "engineering",
        "ic",
        "infrastructure",
        "ladder",
        "lead",
        "leadership",
        "platform",
        "principal",
        "production",
        "reliability",
        "role",
        "scale",
        "scaling",
        "scope",
        "senior",
        "service",
        "software",
        "staff",
        "system",
        "systems",
        "tech",
        "technical",
    }
)

_CUSTOMER_DISCOVERY_TERMS = frozenset(
    {
        "adopt",
        "adoption",
        "alternative",
        "bottleneck",
        "budget",
        "buyer",
        "buying",
        "cost",
        "current",
        "currently",
        "customer",
        "decide",
        "discovery",
        "evaluate",
        "friction",
        "manual",
        "measure",
        "metric",
        "onboarding",
        "pain",
        "pilot",
        "problem",
        "process",
        "solve",
        "solving",
        "spend",
        "team",
        "time",
        "tool",
        "tooling",
        "urgent",
        "value",
        "workaround",
        "workflow",
    }
)


class BriefQualityViolation(BaseModel):
    """Single deterministic quality check violation detected on a candidate brief."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str
    message: str


class BriefQualityReport(BaseModel):
    """Aggregate outcome of deterministic brief quality validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    violations: list[BriefQualityViolation] = Field(default_factory=list)

    def formatted_feedback(self) -> list[str]:
        """Format violations as concise, actionable repair instructions for regeneration."""
        return [f"[{item.code}] {item.field}: {item.message}" for item in self.violations]


class BriefQualityPolicy(BaseModel):
    """Configurable bounds for Brew's deterministic brief quality gates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_openers: Annotated[int, Field(ge=1, le=5)] = 2
    max_openers: Annotated[int, Field(ge=1, le=10)] = 3
    min_questions: Annotated[int, Field(ge=1, le=10)] = 5
    max_questions: Annotated[int, Field(ge=1, le=15)] = 8
    explicit_question_count: Annotated[int, Field(ge=1, le=15)] | None = None
    max_question_jaccard_similarity: Annotated[float, Field(gt=0.3, le=1.0)] = 0.72
    min_rationale_chars: Annotated[int, Field(ge=5, le=100)] = 15


class RefinementResolution(BaseModel):
    """Deterministic interpretation of natural-language brief refinement instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_duration_minutes: MeetingDurationMinutes
    target_tone: MeetingTone
    less_formal_requested: bool = False
    avoid_prior_questions: bool = False
    focus_engineering_career: bool = False
    focus_customer_discovery: bool = False


def parse_refinement_overrides(
    instructions: str,
    *,
    explicit_duration_minutes: int | None,
    explicit_tone: MeetingTone | None,
    fallback_duration_minutes: int,
    fallback_tone: MeetingTone,
) -> RefinementResolution:
    """Resolve explicit and natural-language duration, tone, and topic directives."""
    lowered = instructions.lower()

    resolved_duration = explicit_duration_minutes
    if resolved_duration is None:
        for pattern in _DURATION_OVERRIDE_PATTERNS:
            match = pattern.search(instructions)
            if match is not None:
                parsed_minutes = int(match.group(1))
                if 5 <= parsed_minutes <= 180:
                    resolved_duration = parsed_minutes
                    break
    if resolved_duration is None:
        resolved_duration = fallback_duration_minutes

    less_formal = any(
        cue in lowered
        for cue in (
            "less formal",
            "more casual",
            "informal",
            "keep it casual",
            "conversational and relaxed",
            "warmer tone",
        )
    )

    resolved_tone = explicit_tone
    if resolved_tone is None:
        if less_formal:
            resolved_tone = MeetingTone.WARM_CASUAL
        elif any(cue in lowered for cue in ("more formal", "executive", "structured tone")):
            resolved_tone = MeetingTone.STRUCTURED_EXECUTIVE
        elif any(cue in lowered for cue in ("candid", "direct coaching", "blunt")):
            resolved_tone = MeetingTone.CANDID_COACHING
        elif "customer discovery" in lowered or "exploratory" in lowered:
            resolved_tone = MeetingTone.CURIOUS_EXPLORATORY
        else:
            resolved_tone = fallback_tone

    avoid_prior = any(
        cue in lowered
        for cue in (
            "already asked",
            "asked these",
            "asked those",
            "new questions",
            "different questions",
            "fresh questions",
            "avoid repeating",
            "don't repeat",
            "do not repeat",
        )
    )
    focus_eng = any(
        cue in lowered
        for cue in (
            "engineering career",
            "technical career",
            "engineering path",
            "engineering leadership",
            "software engineering",
        )
    )
    focus_discovery = "customer discovery" in lowered or "user research" in lowered

    return RefinementResolution(
        target_duration_minutes=resolved_duration,
        target_tone=resolved_tone,
        less_formal_requested=less_formal,
        avoid_prior_questions=avoid_prior,
        focus_engineering_career=focus_eng,
        focus_customer_discovery=focus_discovery,
    )


def _normalize_text_for_dedup(text: str) -> str:
    return " ".join(_WORD_TOKEN_RE.findall(text.lower()))


def _question_content_tokens(text: str, *, ignored_names: set[str]) -> set[str]:
    tokens = set(_WORD_TOKEN_RE.findall(text.lower()))
    return {
        tok
        for tok in tokens
        if len(tok) >= 3 and tok not in _QUESTION_STOPWORDS and tok not in ignored_names
    }


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _build_grounding_corpus(
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    current_brief: PreparationBrief | None = None,
    refinement_instructions: str | None = None,
) -> str:
    fragments: list[str] = [
        context.contact.name,
        context.contact.title or "",
        context.contact.role or "",
        context.contact.organization or "",
        context.contact.context_notes or "",
        meeting.objective,
        meeting.notes or "",
        refinement_instructions or "",
    ]
    if context.user_preferences is not None:
        fragments.append(context.user_preferences.communication_style_notes or "")
        fragments.extend(context.user_preferences.focus_areas)
    fragments.extend(item.text for item in context.preference_memories)
    fragments.extend(item.text for item in context.contact_memories)
    for item in context.contact_memories:
        if item.source.excerpt:
            fragments.append(item.source.excerpt)
    for summary in context.recent_meetings:
        fragments.append(summary.objective)
        if summary.notes_excerpt:
            fragments.append(summary.notes_excerpt)
    if current_brief is not None:
        fragments.append(current_brief.contact_context)
        fragments.append(current_brief.meeting_objective)
    return " ".join(part for part in fragments if part).lower()


def _build_goal_keywords(
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    target_purpose: MeetingPurpose,
    refinement_instructions: str | None = None,
) -> set[str]:
    raw_sources = [
        meeting.objective,
        target_purpose.value.replace("_", " "),
        refinement_instructions or "",
    ]
    if context.user_preferences is not None:
        raw_sources.extend(context.user_preferences.focus_areas)
    tokens = set(_WORD_TOKEN_RE.findall(" ".join(raw_sources).lower()))
    return {tok for tok in tokens if len(tok) >= 4 and tok not in _QUESTION_STOPWORDS}


def evaluate_brief_quality(
    content: GeneratedBriefContent,
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    target_duration_minutes: int,
    target_tone: MeetingTone,
    policy: BriefQualityPolicy | None = None,
    current_brief: PreparationBrief | None = None,
    refinement: RefinementResolution | None = None,
    refinement_instructions: str | None = None,
) -> BriefQualityReport:
    """Run deterministic quality, grounding, tone, agenda, and redundancy checks."""
    active_policy = policy or BriefQualityPolicy()
    violations: list[BriefQualityViolation] = []

    # 1. Conversation openers count & uniqueness (2 to 3 openers)
    opener_count = len(content.conversation_openers)
    if not (active_policy.min_openers <= opener_count <= active_policy.max_openers):
        violations.append(
            BriefQualityViolation(
                code="OPENER_COUNT_OUT_OF_RANGE",
                field="conversation_openers",
                message=(
                    f"Expected {active_policy.min_openers} to {active_policy.max_openers} "
                    f"conversation openers, got {opener_count}."
                ),
            )
        )
    normalized_openers = [_normalize_text_for_dedup(op) for op in content.conversation_openers]
    if len(set(normalized_openers)) != len(normalized_openers):
        violations.append(
            BriefQualityViolation(
                code="DUPLICATE_OPENERS",
                field="conversation_openers",
                message="Conversation openers must be distinct rather than repeated.",
            )
        )

    # 2. Prioritized question count (5 to 8 by default, or explicit caller preference)
    question_count = len(content.suggested_questions)
    if active_policy.explicit_question_count is not None and not (
        active_policy.min_questions
        <= active_policy.explicit_question_count
        <= active_policy.max_questions
    ):
        allowed_min = min(active_policy.explicit_question_count, active_policy.min_questions)
        allowed_max = max(active_policy.explicit_question_count, active_policy.max_questions)
        if question_count != active_policy.explicit_question_count and not (
            active_policy.min_questions <= question_count <= active_policy.max_questions
        ):
            violations.append(
                BriefQualityViolation(
                    code="QUESTION_COUNT_OUT_OF_RANGE",
                    field="suggested_questions",
                    message=(
                        f"Expected {active_policy.explicit_question_count} (or "
                        f"{allowed_min}-{allowed_max}) prioritized questions, got {question_count}."
                    ),
                )
            )
    elif not (active_policy.min_questions <= question_count <= active_policy.max_questions):
        violations.append(
            BriefQualityViolation(
                code="QUESTION_COUNT_OUT_OF_RANGE",
                field="suggested_questions",
                message=(
                    f"Expected {active_policy.min_questions} to {active_policy.max_questions} "
                    f"prioritized questions, got {question_count}."
                ),
            )
        )

    question_ids = [item.id for item in content.suggested_questions]
    if len(set(question_ids)) != len(question_ids):
        violations.append(
            BriefQualityViolation(
                code="DUPLICATE_QUESTION_IDS",
                field="suggested_questions",
                message="Every suggested question must have a unique id.",
            )
        )

    # 3. Realistic time-boxed agenda for the selected duration
    agenda = content.time_boxed_agenda
    allocated_minutes = sum(item.duration_minutes for item in agenda)
    if allocated_minutes != target_duration_minutes:
        violations.append(
            BriefQualityViolation(
                code="AGENDA_DURATION_MISMATCH",
                field="time_boxed_agenda",
                message=(
                    f"Agenda segments must sum strictly to {target_duration_minutes} minutes, "
                    f"got {allocated_minutes} minutes."
                ),
            )
        )

    max_realistic_segments = max(3, min(8, target_duration_minutes // 3))
    if len(agenda) < 2 or len(agenda) > max_realistic_segments:
        violations.append(
            BriefQualityViolation(
                code="AGENDA_UNREALISTIC_STRUCTURE",
                field="time_boxed_agenda",
                message=(
                    f"Agenda for a {target_duration_minutes}-minute meeting must have between "
                    f"2 and {max_realistic_segments} realistic segments, got {len(agenda)}."
                ),
            )
        )
    elif target_duration_minutes >= 10 and agenda[0].duration_minutes > int(
        target_duration_minutes * 0.65
    ):
        violations.append(
            BriefQualityViolation(
                code="AGENDA_UNREALISTIC_PACING",
                field="time_boxed_agenda",
                message=(
                    "Opening rapport segment consumes over 65% of the total meeting duration, "
                    "leaving insufficient time for prioritized questions."
                ),
            )
        )

    # 4. Question rationales linked to meeting goals
    goal_keywords = _build_goal_keywords(
        meeting=meeting,
        context=context,
        target_purpose=meeting.purpose,
        refinement_instructions=refinement_instructions,
    )
    for idx, q_item in enumerate(content.suggested_questions):
        rationale_clean = q_item.rationale.strip()
        rationale_lower = rationale_clean.lower()
        if len(rationale_clean) < active_policy.min_rationale_chars or _normalize_text_for_dedup(
            rationale_clean
        ) == _normalize_text_for_dedup(q_item.question):
            violations.append(
                BriefQualityViolation(
                    code="RATIONALE_NOT_LINKED_TO_GOAL",
                    field=f"suggested_questions[{idx}].rationale",
                    message=(
                        "Question rationale must be substantive and distinct from the "
                        "question text."
                    ),
                )
            )
            continue

        rationale_tokens = set(_WORD_TOKEN_RE.findall(rationale_lower))
        has_goal_keyword = bool(goal_keywords & rationale_tokens)
        has_coaching_anchor = any(anchor in rationale_lower for anchor in _GOAL_LINK_ANCHOR_TERMS)
        if not (has_goal_keyword or has_coaching_anchor):
            violations.append(
                BriefQualityViolation(
                    code="RATIONALE_NOT_LINKED_TO_GOAL",
                    field=f"suggested_questions[{idx}].rationale",
                    message=(
                        "Question rationale must explain how the question advances the "
                        "meeting objective, purpose, or coaching goal."
                    ),
                )
            )

    # 5. Appropriate tone and audience (anti-flattery, anti-cliché, register alignment)
    combined_prose = " \n ".join(
        [
            content.contact_context,
            *content.conversation_openers,
            *(q.question for q in content.suggested_questions),
        ]
    )
    for label, pattern in _FLATTERY_AND_CLICHE_PATTERNS:
        if pattern.search(combined_prose):
            violations.append(
                BriefQualityViolation(
                    code="INAPPROPRIATE_TONE_OR_CLICHE",
                    field="suggested_questions",
                    message=f"Brief contains {label}; use grounded, specific coaching language.",
                )
            )

    expect_casual = target_tone is MeetingTone.WARM_CASUAL or (
        refinement is not None and refinement.less_formal_requested
    )
    if expect_casual and _OVERLY_FORMAL_PATTERNS.search(combined_prose):
        violations.append(
            BriefQualityViolation(
                code="TONE_MISMATCH",
                field="conversation_openers",
                message=(
                    "Brief uses stiff, overly formal phrasing despite a warm/less-formal "
                    "tone requirement."
                ),
            )
        )
    if target_tone is MeetingTone.STRUCTURED_EXECUTIVE and _OVERLY_SLANGY_EXECUTIVE_PATTERNS.search(
        combined_prose
    ):
        violations.append(
            BriefQualityViolation(
                code="TONE_MISMATCH",
                field="conversation_openers",
                message="Brief uses informal slang unsuitable for a structured_executive tone.",
            )
        )

    # 6. Grounding: no unsupported biographical claims or hallucinated memory IDs
    allowed_memory_ids = set(context.referenced_memory_ids)
    if current_brief is not None:
        allowed_memory_ids.update(current_brief.referenced_memory_ids)
    ungrounded_mem_ids = [
        mem_id for mem_id in content.referenced_memory_ids if mem_id not in allowed_memory_ids
    ]
    if ungrounded_mem_ids:
        violations.append(
            BriefQualityViolation(
                code="UNGROUNDED_MEMORY_REFERENCE",
                field="referenced_memory_ids",
                message=(
                    "Brief references memory IDs that were not retrieved from approved "
                    f"storage: {', '.join(ungrounded_mem_ids)}."
                ),
            )
        )

    grounding_corpus = _build_grounding_corpus(
        meeting=meeting,
        context=context,
        current_brief=current_brief,
        refinement_instructions=refinement_instructions,
    )
    grounding_tokens = set(_WORD_TOKEN_RE.findall(grounding_corpus))
    for claim_label, bio_pattern in _UNSUPPORTED_BIO_PATTERNS:
        for match in bio_pattern.finditer(combined_prose):
            matched_phrase = match.group(0).strip().lower()
            phrase_tokens = {
                tok
                for tok in _WORD_TOKEN_RE.findall(matched_phrase)
                if len(tok) >= 3 and tok not in {"from", "the", "with", "years", "spent", "has"}
            }
            if matched_phrase not in grounding_corpus and not phrase_tokens.issubset(
                grounding_tokens
            ):
                violations.append(
                    BriefQualityViolation(
                        code="UNSUPPORTED_BIOGRAPHICAL_CLAIM",
                        field="contact_context",
                        message=(
                            f"Detected {claim_label} ('{match.group(0).strip()}') not supported "
                            "by saved contact profile, memories, or meeting input."
                        ),
                    )
                )
                break

    # 7. No repetitive or redundant questions (within brief + vs prior brief when requested)
    contact_name_tokens = set(_WORD_TOKEN_RE.findall(context.contact.name.lower()))
    seen_normalized: list[tuple[int, str, set[str]]] = []
    redundant_pair_found = False
    for idx, q_item in enumerate(content.suggested_questions):
        norm_q = _normalize_text_for_dedup(q_item.question)
        q_tokens = _question_content_tokens(q_item.question, ignored_names=contact_name_tokens)
        for prev_idx, prev_norm, prev_tokens in seen_normalized:
            similarity = _jaccard_similarity(q_tokens, prev_tokens)
            if norm_q == prev_norm or similarity >= active_policy.max_question_jaccard_similarity:
                violations.append(
                    BriefQualityViolation(
                        code="REDUNDANT_QUESTIONS",
                        field=f"suggested_questions[{idx}].question",
                        message=(
                            f"Question {idx + 1} is repetitive or redundant with "
                            f"question {prev_idx + 1}; diversify question angles."
                        ),
                    )
                )
                redundant_pair_found = True
                break
        if redundant_pair_found:
            break
        seen_normalized.append((idx, norm_q, q_tokens))

    if refinement is not None and refinement.avoid_prior_questions and current_brief is not None:
        prior_questions: Sequence[tuple[str, set[str]]] = [
            (
                _normalize_text_for_dedup(old_q.question),
                _question_content_tokens(old_q.question, ignored_names=contact_name_tokens),
            )
            for old_q in current_brief.suggested_questions
        ]
        for idx, q_item in enumerate(content.suggested_questions):
            norm_q = _normalize_text_for_dedup(q_item.question)
            q_tokens = _question_content_tokens(q_item.question, ignored_names=contact_name_tokens)
            if any(
                norm_q == old_norm
                or _jaccard_similarity(q_tokens, old_tokens)
                >= active_policy.max_question_jaccard_similarity
                for old_norm, old_tokens in prior_questions
            ):
                violations.append(
                    BriefQualityViolation(
                        code="REPEATED_PRIOR_BRIEF_QUESTIONS",
                        field=f"suggested_questions[{idx}].question",
                        message=(
                            "Caller indicated prior questions were already asked, but "
                            f"question {idx + 1} repeats an earlier brief question."
                        ),
                    )
                )
                break

    if refinement is not None and refinement.focus_engineering_career:
        eng_matches = sum(
            1
            for q_item in content.suggested_questions
            if set(_WORD_TOKEN_RE.findall(q_item.question.lower())) & _ENGINEERING_CAREER_TERMS
        )
        if eng_matches < min(2, len(content.suggested_questions)):
            violations.append(
                BriefQualityViolation(
                    code="REFINEMENT_FOCUS_MISSED",
                    field="suggested_questions",
                    message=(
                        "Refinement requested focusing on engineering career, but questions "
                        "do not substantively address technical or career progression."
                    ),
                )
            )

    if refinement is not None and refinement.focus_customer_discovery:
        disc_matches = sum(
            1
            for q_item in content.suggested_questions
            if set(_WORD_TOKEN_RE.findall(q_item.question.lower())) & _CUSTOMER_DISCOVERY_TERMS
        )
        if disc_matches < min(2, len(content.suggested_questions)):
            violations.append(
                BriefQualityViolation(
                    code="REFINEMENT_FOCUS_MISSED",
                    field="suggested_questions",
                    message=(
                        "Refinement requested customer discovery questions, but questions "
                        "do not substantively explore workflow pain points or current solutions."
                    ),
                )
            )

    return BriefQualityReport(passed=len(violations) == 0, violations=violations)
