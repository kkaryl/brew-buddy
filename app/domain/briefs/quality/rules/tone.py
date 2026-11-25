"""Tone rules: flattery, cliches and register mismatch."""

from __future__ import annotations

from app.domain.briefs.quality.lexicons import (
    FLATTERY_AND_CLICHE_PATTERNS,
    OVERLY_FORMAL_PATTERNS,
    OVERLY_SLANGY_EXECUTIVE_PATTERNS,
)
from app.domain.briefs.quality.policy import BriefQualityViolation
from app.domain.briefs.quality.refinement import RefinementResolution
from app.domain.meetings.types import MeetingTone


def check_tone_and_cliches(
    combined_prose: str,
    *,
    target_tone: MeetingTone,
    refinement: RefinementResolution | None = None,
) -> list[BriefQualityViolation]:
    """Check ``combined_prose`` for flattery, cliches and a register that misses the tone.

    ``combined_prose`` is the contact context, openers and question texts joined by the gate.
    """
    violations: list[BriefQualityViolation] = []

    # 5. Appropriate tone and audience (anti-flattery, anti-cliché, register alignment)
    for label, pattern in FLATTERY_AND_CLICHE_PATTERNS:
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
    if expect_casual and OVERLY_FORMAL_PATTERNS.search(combined_prose):
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
    if target_tone is MeetingTone.STRUCTURED_EXECUTIVE and OVERLY_SLANGY_EXECUTIVE_PATTERNS.search(
        combined_prose
    ):
        violations.append(
            BriefQualityViolation(
                code="TONE_MISMATCH",
                field="conversation_openers",
                message="Brief uses informal slang unsuitable for a structured_executive tone.",
            )
        )

    return violations
