"""Grounding rules: memory references and biographical claims."""

from __future__ import annotations

from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import PreparationBrief
from app.domain.briefs.ports import GeneratedBriefContent
from app.domain.briefs.quality.lexicons import UNSUPPORTED_BIO_PATTERNS
from app.domain.briefs.quality.policy import BriefQualityViolation
from app.domain.briefs.quality.text import WORD_TOKEN_RE
from app.domain.meetings.models import Meeting


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


def check_grounding_and_biographical_claims(
    content: GeneratedBriefContent,
    *,
    combined_prose: str,
    meeting: Meeting,
    context: BriefPreparationContext,
    current_brief: PreparationBrief | None = None,
    refinement_instructions: str | None = None,
) -> list[BriefQualityViolation]:
    """Check memory references and biographical claims are supported by saved context.

    ``combined_prose`` is the contact context, openers and question texts joined by the gate.
    """
    violations: list[BriefQualityViolation] = []

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
    grounding_tokens = set(WORD_TOKEN_RE.findall(grounding_corpus))
    for claim_label, bio_pattern in UNSUPPORTED_BIO_PATTERNS:
        for match in bio_pattern.finditer(combined_prose):
            matched_phrase = match.group(0).strip().lower()
            phrase_tokens = {
                tok
                for tok in WORD_TOKEN_RE.findall(matched_phrase)
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

    return violations
