"""Per-stage model routing and the specialist agents that use it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import CONVERSATION_COACH_INSTRUCTION, build_conversation_coach_agent
from app.config import AppSettings
from app.domain.types import (
    BRIEF_REFINER_AGENT_NAME,
    BRIEF_SYNTHESIZER_AGENT_NAME,
    BriefWorkflowOperation,
    brief_specialist_agent_name,
)
from app.infrastructure.adk_brief_coach import AdkConversationCoachBriefAdapter
from app.infrastructure.adk_memory_extractor import AdkMemoryProposalAdapter
from app.infrastructure.fakes import FakeServiceContainer
from app.model_routing import ModelStage, build_gemini_model, resolve_model_id
from app.prompts import (
    BRIEF_REFINER_INSTRUCTION,
    BRIEF_SYNTHESIZER_INSTRUCTION,
    SHARED_COACHING_PRINCIPLES,
)
from app.tools.coaching_tools import CoachingToolDependencies

BASE_MODEL = "base-flash-under-test"
SYNTHESIS_MODEL = "advanced-synthesis-under-test"


def _settings(**overrides: str | None) -> AppSettings:
    values: dict[str, object] = {
        "environment": "test",
        "otel_to_cloud": False,
        "gemini_model": BASE_MODEL,
        "synthesis_model": SYNTHESIS_MODEL,
        "refinement_model": None,
        "memory_extraction_model": None,
    }
    values.update(overrides)
    return AppSettings.model_validate(values)


def _brief_adapter(settings: AppSettings) -> AdkConversationCoachBriefAdapter:
    container = FakeServiceContainer()
    return AdkConversationCoachBriefAdapter(
        tool_dependencies=CoachingToolDependencies(
            preferences_reader=container.preferences_repo,
            contact_reader=container.contact_repo,
            meeting_reader=container.meeting_repo,
            memory_reader=container.memory_repo,
            proposal_stager=container.proposal_repo,
            proposal_agent=container.proposal_agent,
            clock=container.clock,
            id_generator=container.id_generator,
        ),
        settings=settings,
    )


def test_advanced_model_is_the_default_for_synthesis_only() -> None:
    assert AppSettings.model_fields["synthesis_model"].default == "gemini-4-hydrogen"
    assert AppSettings.model_fields["gemini_model"].default == "gemini-3.8-flash"
    assert AppSettings.model_fields["refinement_model"].default is None
    assert AppSettings.model_fields["memory_extraction_model"].default is None


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (ModelStage.BRIEF_SYNTHESIS, SYNTHESIS_MODEL),
        (ModelStage.BRIEF_REFINEMENT, BASE_MODEL),
        (ModelStage.MEMORY_EXTRACTION, BASE_MODEL),
        (ModelStage.HISTORY_SUMMARIZATION, BASE_MODEL),
        (ModelStage.CONVERSATION, BASE_MODEL),
    ],
)
def test_each_stage_routes_to_its_configured_model(stage: ModelStage, expected: str) -> None:
    settings = _settings()

    assert resolve_model_id(settings, stage) == expected
    assert build_gemini_model(settings, stage=stage).model == expected


def test_optional_stage_overrides_replace_the_base_model() -> None:
    settings = _settings(
        refinement_model="refine-under-test",
        memory_extraction_model="extract-under-test",
    )

    assert resolve_model_id(settings, ModelStage.BRIEF_REFINEMENT) == "refine-under-test"
    assert resolve_model_id(settings, ModelStage.MEMORY_EXTRACTION) == "extract-under-test"
    assert resolve_model_id(settings, ModelStage.CONVERSATION) == BASE_MODEL


def test_blank_optional_overrides_fall_back_and_blank_synthesis_is_rejected() -> None:
    settings = _settings(refinement_model="   ", memory_extraction_model="")
    assert settings.refinement_model is None
    assert settings.memory_extraction_model is None
    assert resolve_model_id(settings, ModelStage.BRIEF_REFINEMENT) == BASE_MODEL

    with pytest.raises(ValidationError):
        _settings(synthesis_model="   ")


@pytest.mark.parametrize(
    ("operation", "expected_name", "expected_model"),
    [
        (BriefWorkflowOperation.GENERATE, BRIEF_SYNTHESIZER_AGENT_NAME, SYNTHESIS_MODEL),
        (BriefWorkflowOperation.REVISE, BRIEF_REFINER_AGENT_NAME, "refine-under-test"),
    ],
)
def test_brief_workflow_uses_a_routed_specialist_per_operation(
    operation: BriefWorkflowOperation,
    expected_name: str,
    expected_model: str,
) -> None:
    adapter = _brief_adapter(_settings(refinement_model="refine-under-test"))

    agent = adapter._build_workflow_agent(operation)

    assert agent.name == expected_name == brief_specialist_agent_name(operation)
    assert getattr(agent.model, "model", None) == expected_model
    # Read-only on the brief path: the staging tool is neither attached nor mentioned.
    tool_names = {getattr(tool, "name", "") for tool in agent.tools}
    assert tool_names == {"get_user_preferences", "get_contact_context", "get_meeting_history"}
    assert isinstance(agent.instruction, str)
    assert "suggest_memory_candidates" not in agent.instruction
    assert SHARED_COACHING_PRINCIPLES in agent.instruction


def test_specialist_instructions_are_distinct_and_share_the_safety_principles() -> None:
    assert BRIEF_SYNTHESIZER_INSTRUCTION != BRIEF_REFINER_INSTRUCTION
    assert "`brief_synthesizer`" in BRIEF_SYNTHESIZER_INSTRUCTION
    assert "`brief_refiner`" in BRIEF_REFINER_INSTRUCTION
    for instruction in (
        BRIEF_SYNTHESIZER_INSTRUCTION,
        BRIEF_REFINER_INSTRUCTION,
        CONVERSATION_COACH_INSTRUCTION,
    ):
        assert instruction.endswith(SHARED_COACHING_PRINCIPLES)
    # Only the conversational coach is told about the staging tool it actually has.
    assert "suggest_memory_candidates" in CONVERSATION_COACH_INSTRUCTION


def test_extractor_and_conversation_agents_stay_on_their_own_routes() -> None:
    settings = _settings(memory_extraction_model="extract-under-test")

    extractor = AdkMemoryProposalAdapter(settings=settings)._build_extractor_agent()
    coach = build_conversation_coach_agent(settings)

    assert getattr(extractor.model, "model", None) == "extract-under-test"
    assert extractor.tools == []
    assert getattr(coach.model, "model", None) == BASE_MODEL
