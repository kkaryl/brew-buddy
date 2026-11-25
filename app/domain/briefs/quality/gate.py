"""Deterministic brief quality gate that applies every rule group in order."""

from __future__ import annotations

from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import PreparationBrief
from app.domain.briefs.ports import GeneratedBriefContent
from app.domain.briefs.quality.policy import (
    BriefQualityPolicy,
    BriefQualityReport,
    BriefQualityViolation,
)
from app.domain.briefs.quality.refinement import RefinementResolution
from app.domain.briefs.quality.rules.agenda import check_agenda_timing
from app.domain.briefs.quality.rules.grounding import check_grounding_and_biographical_claims
from app.domain.briefs.quality.rules.rationale import (
    check_question_rationales,
    check_question_redundancy,
)
from app.domain.briefs.quality.rules.structure import check_structure_and_counts
from app.domain.briefs.quality.rules.tone import check_tone_and_cliches
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingTone


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

    # Rule groups run in the order the checks were originally written, so the violations
    # (and the repair feedback built from them) keep their order.
    violations.extend(check_structure_and_counts(content, active_policy=active_policy))
    violations.extend(check_agenda_timing(content, target_duration_minutes=target_duration_minutes))
    violations.extend(
        check_question_rationales(
            content,
            meeting=meeting,
            context=context,
            active_policy=active_policy,
            refinement_instructions=refinement_instructions,
        )
    )

    # The tone and grounding groups scan the same prose.
    combined_prose = " \n ".join(
        [
            content.contact_context,
            *content.conversation_openers,
            *(q.question for q in content.suggested_questions),
        ]
    )
    violations.extend(
        check_tone_and_cliches(combined_prose, target_tone=target_tone, refinement=refinement)
    )
    violations.extend(
        check_grounding_and_biographical_claims(
            content,
            combined_prose=combined_prose,
            meeting=meeting,
            context=context,
            current_brief=current_brief,
            refinement_instructions=refinement_instructions,
        )
    )
    violations.extend(
        check_question_redundancy(
            content,
            context=context,
            active_policy=active_policy,
            current_brief=current_brief,
            refinement=refinement,
        )
    )

    return BriefQualityReport(passed=len(violations) == 0, violations=violations)
