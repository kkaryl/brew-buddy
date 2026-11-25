"""Agenda rules: time-box total, segment count and opening-segment pacing."""

from __future__ import annotations

from app.domain.briefs.ports import GeneratedBriefContent
from app.domain.briefs.quality.policy import BriefQualityViolation


def check_agenda_timing(
    content: GeneratedBriefContent,
    *,
    target_duration_minutes: int,
) -> list[BriefQualityViolation]:
    """Check the agenda sums to the target duration and has realistic structure and pacing."""
    violations: list[BriefQualityViolation] = []

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

    return violations
