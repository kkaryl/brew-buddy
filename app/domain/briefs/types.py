"""Brief text types, workflow operation and outcome enums, and specialist agent names."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

OpenerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=400),
]


AgendaTitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
]


AgendaDescriptionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=400),
]


QuestionPromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=400),
]


FollowUpTopicText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=300),
]


class BriefWorkflowTerminalState(StrEnum):
    """Explicit terminal outcomes for the meeting preparation and refinement workflow."""

    COMPLETED = "completed"
    COMPLETED_REPAIRED = "completed_repaired"
    COMPLETED_IDEMPOTENT_REPLAY = "completed_idempotent_replay"
    FAILED_INPUT_VALIDATION = "failed_input_validation"
    FAILED_NOT_FOUND = "failed_not_found"
    FAILED_FORBIDDEN = "failed_forbidden"
    FAILED_CONFLICT = "failed_conflict"
    FAILED_OUTPUT_VALIDATION = "failed_output_validation"
    FAILED_MODEL_TIMEOUT = "failed_model_timeout"
    FAILED_MODEL_ERROR = "failed_model_error"
    FAILED_PERSISTENCE = "failed_persistence"


class BriefWorkflowOperation(StrEnum):
    """Supported brief workflow execution modes."""

    GENERATE = "generate"
    REVISE = "revise"


BRIEF_SYNTHESIZER_AGENT_NAME = "brief_synthesizer"


BRIEF_REFINER_AGENT_NAME = "brief_refiner"


def brief_specialist_agent_name(operation: BriefWorkflowOperation) -> str:
    """Return the name of the specialist agent that serves ``operation``."""
    if operation is BriefWorkflowOperation.GENERATE:
        return BRIEF_SYNTHESIZER_AGENT_NAME
    return BRIEF_REFINER_AGENT_NAME
