"""Structure rules: opener and question counts, duplicate openers and question ids."""

from __future__ import annotations

from app.domain.briefs.ports import GeneratedBriefContent
from app.domain.briefs.quality.policy import BriefQualityPolicy, BriefQualityViolation
from app.domain.briefs.quality.text import normalize_text_for_dedup


def check_structure_and_counts(
    content: GeneratedBriefContent,
    *,
    active_policy: BriefQualityPolicy,
) -> list[BriefQualityViolation]:
    """Check opener count and uniqueness, question count, and question id uniqueness."""
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
    normalized_openers = [normalize_text_for_dedup(op) for op in content.conversation_openers]
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

    return violations
