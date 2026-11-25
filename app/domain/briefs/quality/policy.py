"""Brief quality policy bounds, violation and report models."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


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
