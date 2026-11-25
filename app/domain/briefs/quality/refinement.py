"""Deterministic parsing of natural-language brief refinement instructions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.briefs.quality.lexicons import DURATION_OVERRIDE_PATTERNS
from app.domain.meetings.types import MeetingTone
from app.domain.shared.types import MeetingDurationMinutes


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
        for pattern in DURATION_OVERRIDE_PATTERNS:
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
