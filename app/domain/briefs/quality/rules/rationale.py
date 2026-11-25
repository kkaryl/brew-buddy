"""Question rules: rationales linked to goals, redundancy, refinement focus."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import PreparationBrief
from app.domain.briefs.ports import GeneratedBriefContent
from app.domain.briefs.quality.lexicons import (
    CUSTOMER_DISCOVERY_TERMS,
    ENGINEERING_CAREER_TERMS,
    GOAL_LINK_ANCHOR_TERMS,
    QUESTION_STOPWORDS,
)
from app.domain.briefs.quality.policy import BriefQualityPolicy, BriefQualityViolation
from app.domain.briefs.quality.refinement import RefinementResolution
from app.domain.briefs.quality.text import (
    WORD_TOKEN_RE,
    jaccard_similarity,
    normalize_text_for_dedup,
    question_content_tokens,
)
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingPurpose


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
    tokens = set(WORD_TOKEN_RE.findall(" ".join(raw_sources).lower()))
    return {tok for tok in tokens if len(tok) >= 4 and tok not in QUESTION_STOPWORDS}


def check_question_rationales(
    content: GeneratedBriefContent,
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    active_policy: BriefQualityPolicy,
    refinement_instructions: str | None = None,
) -> list[BriefQualityViolation]:
    """Check each question rationale is substantive and linked to the meeting goal."""
    violations: list[BriefQualityViolation] = []

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
        if len(rationale_clean) < active_policy.min_rationale_chars or normalize_text_for_dedup(
            rationale_clean
        ) == normalize_text_for_dedup(q_item.question):
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

        rationale_tokens = set(WORD_TOKEN_RE.findall(rationale_lower))
        has_goal_keyword = bool(goal_keywords & rationale_tokens)
        has_coaching_anchor = any(anchor in rationale_lower for anchor in GOAL_LINK_ANCHOR_TERMS)
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

    return violations


def check_question_redundancy(
    content: GeneratedBriefContent,
    *,
    context: BriefPreparationContext,
    active_policy: BriefQualityPolicy,
    current_brief: PreparationBrief | None = None,
    refinement: RefinementResolution | None = None,
) -> list[BriefQualityViolation]:
    """Check questions for repeats within the brief, repeats of the prior brief, and focus.

    The prior-brief and focus checks apply only when ``refinement`` asks for them.
    """
    violations: list[BriefQualityViolation] = []

    # 7. No repetitive or redundant questions (within brief + vs prior brief when requested)
    contact_name_tokens = set(WORD_TOKEN_RE.findall(context.contact.name.lower()))
    seen_normalized: list[tuple[int, str, set[str]]] = []
    redundant_pair_found = False
    for idx, q_item in enumerate(content.suggested_questions):
        norm_q = normalize_text_for_dedup(q_item.question)
        q_tokens = question_content_tokens(q_item.question, ignored_names=contact_name_tokens)
        for prev_idx, prev_norm, prev_tokens in seen_normalized:
            similarity = jaccard_similarity(q_tokens, prev_tokens)
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
                normalize_text_for_dedup(old_q.question),
                question_content_tokens(old_q.question, ignored_names=contact_name_tokens),
            )
            for old_q in current_brief.suggested_questions
        ]
        for idx, q_item in enumerate(content.suggested_questions):
            norm_q = normalize_text_for_dedup(q_item.question)
            q_tokens = question_content_tokens(q_item.question, ignored_names=contact_name_tokens)
            if any(
                norm_q == old_norm
                or jaccard_similarity(q_tokens, old_tokens)
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
            if set(WORD_TOKEN_RE.findall(q_item.question.lower())) & ENGINEERING_CAREER_TERMS
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
            if set(WORD_TOKEN_RE.findall(q_item.question.lower())) & CUSTOMER_DISCOVERY_TERMS
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

    return violations
