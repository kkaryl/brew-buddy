"""Table-driven unit and HTTP tests for Brew's end-to-end Meeting Preparation Workflow."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ConfigDict, PrivateAttr

from app.application.brief_workflow import (
    BriefWorkflowSafeguardConfig,
    MeetingPreparationWorkflow,
)
from app.application.memory_persistence_service import MemoryPersistenceService
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.application.services import BriefService, ContactService
from app.config import AppSettings
from app.domain.brief_quality import (
    evaluate_brief_quality,
    parse_refinement_overrides,
)
from app.domain.errors import (
    BrewDomainError,
    ConflictError,
    ModelExecutionError,
    ModelOutputValidationError,
    ModelTimeoutError,
    PersistenceOperationError,
)
from app.domain.models import (
    AuthenticatedPrincipal,
    BriefPreparationContext,
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    MemorySource,
    TimeBoxedAgendaItem,
)
from app.domain.ports import GeneratedBriefContent
from app.domain.types import (
    BriefWorkflowTerminalState,
    ConsentStatus,
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryScope,
    MemorySourceType,
    MemoryType,
)
from app.fast_api_app import create_app
from app.infrastructure.adk_brief_coach import AdkConversationCoachBriefAdapter
from app.infrastructure.fakes import (
    FakeAuthenticator,
    FakeMemoryProposalAgent,
    InMemoryBriefRepository,
    InMemoryContactRepository,
    InMemoryMeetingRepository,
    InMemoryMemoryProposalRepository,
    InMemoryMemoryRepository,
    InMemoryUserPreferencesRepository,
    InMemoryWorkflowIdempotencyRepository,
    SequentialIdGenerator,
    ServiceContainer,
)
from app.infrastructure.observability import StructuredJsonFormatter
from app.tools.coaching_tools import CoachingToolDependencies


class DeterministicStepClock:
    """Deterministic UTC clock advancing 30 seconds per read."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 23, 15, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        value = self._now
        self._now = self._now + timedelta(seconds=30)
        return value


@dataclass(frozen=True)
class DelayedTimeoutStep:
    """Simulated slow model turn exceeding the configured deadline."""

    sleep_seconds: float


StepAction = (
    LlmResponse
    | Exception
    | DelayedTimeoutStep
    | Callable[[LlmRequest, int], LlmResponse | DelayedTimeoutStep]
)


class DeterministicMockCoachLlm(BaseLlm):
    """Deterministic ADK ``BaseLlm`` test double driving tool calls and structured JSON turns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _steps: list[Any] = PrivateAttr(default_factory=list)
    _captured_requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(self, steps: list[Any]) -> None:
        super().__init__(model="deterministic-mock-gemini")
        self._steps = list(steps)
        self._captured_requests = []

    @property
    def captured_requests(self) -> list[LlmRequest]:
        return self._captured_requests

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        call_index = len(self._captured_requests)
        self._captured_requests.append(llm_request.model_copy(deep=True))

        if not self._steps:
            raise RuntimeError("DeterministicMockCoachLlm ran out of scripted steps.")

        step = self._steps.pop(0)
        if callable(step):
            step = step(llm_request, call_index)

        if isinstance(step, DelayedTimeoutStep):
            await asyncio.sleep(step.sleep_seconds)
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="{}")],
                )
            )
            return

        if isinstance(step, Exception):
            raise step

        assert isinstance(step, LlmResponse)
        yield step


class FailingMeetingHistoryRepository(InMemoryMeetingRepository):
    """Repository double failing ``list_by_owner`` to exercise tool error & retry safeguards."""

    def __init__(self) -> None:
        super().__init__()
        self.list_attempts = 0

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        del owner_user_id, contact_id
        self.list_attempts += 1
        raise PersistenceOperationError("Simulated Firestore meeting history timeout.")


def _tool_call_response(*calls: tuple[str, dict[str, Any]]) -> LlmResponse:
    parts = [
        types.Part(
            function_call=types.FunctionCall(
                id=f"fc_{idx + 1}_{name}",
                name=name,
                args=args,
            )
        )
        for idx, (name, args) in enumerate(calls)
    ]
    return LlmResponse(content=types.Content(role="model", parts=parts))


def _json_brief_response(payload: dict[str, Any] | str) -> LlmResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        )
    )


def _valid_brief_json_payload(
    *,
    contact_name: str = "Priya Nair",
    contact_org: str = "Nimbus Cloud",
    objective: str = "Understand distributed platform reliability trade-offs.",
    duration_minutes: int = 30,
    question_count: int = 6,
    referenced_memory_ids: list[str] | None = None,
    revision_summary: str | None = None,
    question_theme: str = "general",
    opener_style: str = "warm",
) -> dict[str, Any]:
    warmup = max(2, duration_minutes // 5)
    wrap = max(2, duration_minutes // 5)
    core = duration_minutes - warmup - wrap

    if opener_style == "casual":
        openers = [
            f"Hey {contact_name}, thanks so much for making {duration_minutes} minutes today!",
            f"Before we jump into {objective.lower()[:80]}, how has your week been going?",
        ]
    else:
        openers = [
            (
                f"Thanks for carving out {duration_minutes} minutes today, {contact_name}—"
                f"looking forward to discussing {objective[:90]}."
            ),
            (
                f"At {contact_org}, what has been most energizing for your team this quarter "
                "before we dive in?"
            ),
            "Happy to keep us crisp on time so we cover what is most relevant to both of us.",
        ]

    if question_theme == "engineering_career":
        bank = [
            (
                "q_eng_1",
                "Which architecture project marked the biggest inflection point in your "
                "engineering career?",
                "Links concrete engineering career milestones directly to our mentorship goal.",
                "engineering_career",
            ),
            (
                "q_eng_2",
                "How did your technical system design scope shift when transitioning to "
                "principal-level leadership?",
                "Clarifies senior-to-principal engineering role trade-offs for our objective.",
                "technical_scope",
            ),
            (
                "q_eng_3",
                "What production reliability failure taught you the most durable systems lesson?",
                "Grounds engineering career advice in real operational trade-offs.",
                "systems_lessons",
            ),
            (
                "q_eng_4",
                "How do you balance hands-on code and architecture depth against cross-org "
                "influence?",
                "Explores sustainable engineering leadership habits relevant to career growth.",
                "leadership",
            ),
            (
                "q_eng_5",
                "What signal tells you an engineer is ready to own multi-quarter platform "
                "strategy?",
                "Surfaces concrete evaluation criteria aligned with our career objective.",
                "career_criteria",
            ),
            (
                "q_eng_6",
                "Which technical skill compounded most unexpectedly over the past five years?",
                "Uncovers non-obvious engineering growth leverage for follow-up reflection.",
                "compounding_skills",
            ),
        ]
    elif question_theme == "customer_discovery":
        bank = [
            (
                "q_disc_1",
                "Walk me through how your team currently triages reliability bottlenecks today?",
                "Maps the real current-state customer workflow before testing assumptions.",
                "current_workflow",
            ),
            (
                "q_disc_2",
                "Which manual step in your incident or onboarding process costs the most "
                "engineering time?",
                "Pinpoints concrete customer pain points and operational friction.",
                "pain_points",
            ),
            (
                "q_disc_3",
                "What internal tools or vendor workarounds have you already evaluated to solve "
                "this problem?",
                "Reveals existing alternatives and adoption barriers for customer discovery.",
                "alternatives",
            ),
            (
                "q_disc_4",
                "How does your organization measure whether a workflow tool delivered real value?",
                "Connects customer discovery insights to concrete outcome metrics.",
                "metrics",
            ),
            (
                "q_disc_5",
                "Who else has to sign off when adopting a new developer workflow tool?",
                "Clarifies buyer and stakeholder dynamics tied to our discovery goal.",
                "stakeholders",
            ),
            (
                "q_disc_6",
                "What trigger would move solving this bottleneck from nice-to-have to urgent this "
                "quarter?",
                "Tests urgency and prioritization constraints for customer discovery.",
                "urgency",
            ),
        ]
    else:
        bank = [
            (
                "q_1",
                f"When tackling {objective[:90]}, which architectural trade-off has mattered most?",
                "Anchors the conversation objective in real-world decision-making.",
                "architecture",
            ),
            (
                "q_2",
                f"What early signal tells your team at {contact_org} that a reliability bet is "
                "paying off?",
                "Surfaces concrete evaluation metrics aligned with the meeting purpose.",
                "metrics",
            ),
            (
                "q_3",
                "Which common misconception trips teams up when scaling multi-region services?",
                "Invites candid nuance and practical lessons tied to our discussion goal.",
                "nuance",
            ),
            (
                "q_4",
                "How do you sequence technical debt paydown alongside urgent product milestones?",
                "Explores prioritization trade-offs directly relevant to our objective.",
                "prioritization",
            ),
            (
                "q_5",
                "Where do you see the biggest reliability shift over the next two quarters?",
                "Opens forward-looking roadmap perspective for future follow-ups.",
                "outlook",
            ),
            (
                "q_6",
                "Before we wrap, is there a topic or connection that would be helpful to you?",
                "Closes with thoughtful reciprocity suited to relationship building.",
                "reciprocity",
            ),
        ]

    questions = [
        {
            "id": q_id,
            "question": q_prompt,
            "rationale": q_rationale,
            "category": q_cat,
        }
        for q_id, q_prompt, q_rationale, q_cat in bank[:question_count]
    ]

    return {
        "contact_context": f"{contact_name}, Engineering Director at {contact_org}.",
        "meeting_objective": objective,
        "conversation_openers": openers,
        "time_boxed_agenda": [
            {
                "title": "Warm-up & Context",
                "duration_minutes": warmup,
                "description": "Reconnect briefly and align on the session timebox.",
            },
            {
                "title": "Prioritized Questions",
                "duration_minutes": core,
                "description": "Explore high-priority questions tied to the meeting objective.",
            },
            {
                "title": "Synthesis & Next Steps",
                "duration_minutes": wrap,
                "description": "Recap key insights and agree on any follow-up threads.",
            },
        ],
        "suggested_questions": questions,
        "suggested_follow_up_topics": [
            f"Send a brief thank-you note and recap to {contact_name}.",
            "Follow up on shared reliability architecture practices.",
        ],
        "referenced_memory_ids": referenced_memory_ids or [],
        "revision_summary": revision_summary,
    }


class _WorkflowHarness:
    """Self-contained ADK + repositories harness for deterministic workflow testing."""

    def __init__(
        self,
        *,
        mock_llm: DeterministicMockCoachLlm,
        meeting_repo: InMemoryMeetingRepository | None = None,
        model_timeout_seconds: float = 2.0,
        safeguards: BriefWorkflowSafeguardConfig | None = None,
    ) -> None:
        self.clock = DeterministicStepClock()
        self.ids = SequentialIdGenerator()
        self.preferences_repo = InMemoryUserPreferencesRepository()
        self.contact_repo = InMemoryContactRepository()
        self.meeting_repo = meeting_repo or InMemoryMeetingRepository()
        self.brief_repo = InMemoryBriefRepository()
        self.proposal_repo = InMemoryMemoryProposalRepository()
        self.memory_repo = InMemoryMemoryRepository()
        self.idempotency_repo = InMemoryWorkflowIdempotencyRepository()
        self.proposal_agent = FakeMemoryProposalAgent()
        self.mock_llm = mock_llm

        self.tool_deps = CoachingToolDependencies(
            preferences_reader=self.preferences_repo,
            contact_reader=self.contact_repo,
            meeting_reader=self.meeting_repo,
            memory_reader=self.memory_repo,
            proposal_stager=self.proposal_repo,
            proposal_agent=self.proposal_agent,
            clock=self.clock,
            id_generator=self.ids,
            io_timeout_seconds=1.0,
        )
        self.settings = AppSettings(
            environment="test",
            otel_to_cloud=False,
            http_timeout_seconds=model_timeout_seconds,
        )
        self.adk_brief_adapter = AdkConversationCoachBriefAdapter(
            tool_dependencies=self.tool_deps,
            settings=self.settings,
            model_override=mock_llm,
            model_timeout_seconds=model_timeout_seconds,
        )
        self.contact_service = ContactService(
            contact_repo=self.contact_repo,
            clock=self.clock,
            id_generator=self.ids,
        )
        self.retrieval_service = MemoryRetrievalService(
            preferences_repo=self.preferences_repo,
            contact_repo=self.contact_repo,
            meeting_repo=self.meeting_repo,
            memory_repo=self.memory_repo,
        )
        self.persistence_service = MemoryPersistenceService(
            preferences_repo=self.preferences_repo,
            proposal_repo=self.proposal_repo,
            memory_repo=self.memory_repo,
            contact_repo=self.contact_repo,
            meeting_repo=self.meeting_repo,
            brief_repo=self.brief_repo,
            proposal_agent=self.proposal_agent,
            clock=self.clock,
            id_generator=self.ids,
        )
        self.workflow = MeetingPreparationWorkflow(
            preferences_repo=self.preferences_repo,
            contact_repo=self.contact_repo,
            meeting_repo=self.meeting_repo,
            brief_repo=self.brief_repo,
            memory_repo=self.memory_repo,
            memory_persistence=self.persistence_service,
            brief_agent=self.adk_brief_adapter,
            clock=self.clock,
            id_generator=self.ids,
            idempotency_repo=self.idempotency_repo,
            safeguards=safeguards,
        )
        self.brief_service = BriefService(
            meeting_repo=self.meeting_repo,
            brief_repo=self.brief_repo,
            memory_retrieval=self.retrieval_service,
            memory_persistence=self.persistence_service,
            brief_agent=self.adk_brief_adapter,
            clock=self.clock,
            id_generator=self.ids,
            idempotency_repo=self.idempotency_repo,
            safeguards=safeguards,
        )


@dataclass(frozen=True)
class WorkflowTableCase:
    """Declarative table-driven scenario covering required end-to-end workflow behaviors."""

    case_id: str
    expected_terminal_state: BriefWorkflowTerminalState
    expect_exception: type[BrewDomainError] | None = None


WORKFLOW_TABLE_CASES: tuple[WorkflowTableCase, ...] = (
    WorkflowTableCase(
        case_id="new_contact",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
    WorkflowTableCase(
        case_id="returning_contact",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
    WorkflowTableCase(
        case_id="missing_preferences",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
    WorkflowTableCase(
        case_id="revised_meeting_duration",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
    WorkflowTableCase(
        case_id="tool_failure",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
    WorkflowTableCase(
        case_id="invalid_model_output_repaired",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED_REPAIRED,
    ),
    WorkflowTableCase(
        case_id="invalid_model_output_unrecoverable",
        expected_terminal_state=BriefWorkflowTerminalState.FAILED_OUTPUT_VALIDATION,
        expect_exception=ModelOutputValidationError,
    ),
    WorkflowTableCase(
        case_id="model_timeout",
        expected_terminal_state=BriefWorkflowTerminalState.FAILED_MODEL_TIMEOUT,
        expect_exception=ModelTimeoutError,
    ),
    WorkflowTableCase(
        case_id="duplicate_request",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED_IDEMPOTENT_REPLAY,
    ),
    WorkflowTableCase(
        case_id="repeated_refinement",
        expected_terminal_state=BriefWorkflowTerminalState.COMPLETED,
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", WORKFLOW_TABLE_CASES, ids=lambda c: c.case_id)
async def test_table_driven_end_to_end_meeting_preparation_workflow(
    case: WorkflowTableCase,
) -> None:
    alice = AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice Chen")
    bob = AuthenticatedPrincipal(user_id="usr_bob", display_name="Bob Rivera")
    objective = "Understand distributed platform reliability trade-offs."

    if case.case_id == "new_contact":
        mock_llm = DeterministicMockCoachLlm(
            [
                _tool_call_response(
                    ("get_user_preferences", {"max_preference_memories": 5}),
                    ("get_contact_context", {"contact_id": "cnt_0001", "max_memories": 5}),
                    ("get_meeting_history", {"contact_id": "cnt_0001", "limit": 5}),
                ),
                _json_brief_response(_valid_brief_json_payload()),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        await harness.persistence_service.upsert_user_preferences(
            principal=alice,
            preferred_question_count=6,
            communication_style_notes="Warm, direct open-ended prompts.",
            focus_areas=["reliability", "architecture"],
        )
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        result = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
            request_id="req_new_contact_01",
            trace_id="trc_new_contact_01",
        )

        assert result.diagnostics.terminal_state is case.expected_terminal_state
        assert result.diagnostics.request_id == "req_new_contact_01"
        assert result.diagnostics.trace_id == "trc_new_contact_01"
        assert result.diagnostics.model_invocations == 2
        assert result.diagnostics.tool_invocations == 3
        assert result.diagnostics.regeneration_count == 0
        assert result.brief.version == 1
        assert result.brief.referenced_memory_ids == []
        assert 2 <= len(result.brief.conversation_openers) <= 3
        assert 5 <= len(result.brief.suggested_questions) <= 8
        assert sum(seg.duration_minutes for seg in result.brief.time_boxed_agenda) == 30
        revisions = await harness.brief_repo.list_revisions(alice.user_id, result.brief.id)
        assert [rev.version for rev in revisions] == [1]
        return

    if case.case_id == "returning_contact":
        mock_llm = DeterministicMockCoachLlm(
            [
                _tool_call_response(
                    ("get_user_preferences", {"max_preference_memories": 5}),
                    ("get_contact_context", {"contact_id": "cnt_0001", "max_memories": 5}),
                    ("get_meeting_history", {"contact_id": "cnt_0001", "limit": 5}),
                ),
                _json_brief_response(
                    _valid_brief_json_payload(
                        referenced_memory_ids=["mem_pref_alice", "mem_cnt_priya"],
                    )
                ),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )
        t0 = harness.clock.now_utc()
        await harness.meeting_repo.save(
            Meeting(
                id="mtg_prior_01",
                owner_user_id=alice.user_id,
                contact_id=contact.id,
                purpose=MeetingPurpose.COFFEE_CHAT,
                objective="Initial intro on multi-region failover architecture.",
                duration_minutes=30,
                notes="Priya shared cell-based failover rollout lessons.",
                status=MeetingStatus.COMPLETED,
                created_at=t0,
                updated_at=t0,
            )
        )
        src = MemorySource(
            source_type=MemorySourceType.MEETING_NOTES,
            meeting_id="mtg_prior_01",
            proposal_id="prop_approved_01",
            excerpt="Cell-based failover rollout lessons.",
            recorded_at=t0,
        )
        await harness.memory_repo.save(
            Memory(
                id="mem_pref_alice",
                owner_user_id=alice.user_id,
                scope=MemoryScope.USER_PREFERENCE,
                memory_type=MemoryType.AGENDA_PREFERENCE,
                text="Keep opening rapport concise under 6 minutes.",
                source=src,
                consent_status=ConsentStatus.APPROVED,
                created_at=t0,
                updated_at=t0,
            )
        )
        await harness.memory_repo.save(
            Memory(
                id="mem_cnt_priya",
                owner_user_id=alice.user_id,
                scope=MemoryScope.CONTACT,
                contact_id=contact.id,
                memory_type=MemoryType.FOLLOW_UP_COMMITMENT,
                text="Follow up with Priya on cell-based failover benchmarks.",
                source=src,
                consent_status=ConsentStatus.APPROVED,
                created_at=t0,
                updated_at=t0,
            )
        )
        # Unapproved proposal and Bob's memory must never appear in context
        await harness.proposal_repo.save(
            MemoryProposal(
                id="prop_unapproved",
                owner_user_id=alice.user_id,
                scope=MemoryScope.CONTACT,
                contact_id=contact.id,
                memory_type=MemoryType.RELATIONSHIP_NOTE,
                text="Unapproved note that must remain isolated.",
                rationale="Pending human approval.",
                source=src,
                created_at=t0,
                updated_at=t0,
            )
        )
        await harness.memory_repo.save(
            Memory(
                id="mem_bob_private",
                owner_user_id=bob.user_id,
                scope=MemoryScope.USER_PREFERENCE,
                memory_type=MemoryType.COMMUNICATION_PREFERENCE,
                text="Bob private memory.",
                source=src,
                consent_status=ConsentStatus.APPROVED,
                created_at=t0,
                updated_at=t0,
            )
        )

        result = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
        )

        assert result.diagnostics.terminal_state is case.expected_terminal_state
        assert set(result.brief.referenced_memory_ids) == {"mem_pref_alice", "mem_cnt_priya"}
        assert "prop_unapproved" not in result.brief.referenced_memory_ids
        assert "mem_bob_private" not in result.brief.referenced_memory_ids
        return

    if case.case_id == "missing_preferences":
        mock_llm = DeterministicMockCoachLlm(
            [
                _tool_call_response(
                    ("get_user_preferences", {"max_preference_memories": 5}),
                    ("get_contact_context", {"contact_id": "cnt_0001", "max_memories": 5}),
                ),
                _json_brief_response(_valid_brief_json_payload(question_count=5)),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )
        assert await harness.preferences_repo.get_by_owner(alice.user_id) is None

        result = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.MENTORSHIP,
            tone=MeetingTone.CURIOUS_EXPLORATORY,
            meeting_objective=objective,
            duration_minutes=30,
        )

        assert result.diagnostics.terminal_state is case.expected_terminal_state
        assert len(result.brief.suggested_questions) == 5
        assert result.brief.tone is MeetingTone.CURIOUS_EXPLORATORY
        return

    if case.case_id == "revised_meeting_duration":
        mock_llm = DeterministicMockCoachLlm(
            [
                _json_brief_response(_valid_brief_json_payload(duration_minutes=30)),
                _json_brief_response(
                    _valid_brief_json_payload(
                        duration_minutes=15,
                        question_count=5,
                        revision_summary="Tightened agenda and pacing for a 15-minute window.",
                    )
                ),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )
        initial = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
        )
        # Natural-language duration override without explicit duration_minutes field
        revised = await harness.workflow.execute_refinement(
            principal=alice,
            brief_id=initial.brief.id,
            instructions="I only have 15 minutes",
            expected_version=1,
        )

        assert revised.diagnostics.terminal_state is case.expected_terminal_state
        assert revised.diagnostics.previous_version == 1
        assert revised.brief.version == 2
        assert revised.brief.duration_minutes == 15
        assert sum(seg.duration_minutes for seg in revised.brief.time_boxed_agenda) == 15
        assert revised.meeting.duration_minutes == 15
        assert revised.meeting.version == 2

        # Previous revision v1 must still exist untouched alongside v2
        revisions = await harness.brief_repo.list_revisions(alice.user_id, initial.brief.id)
        assert [rev.version for rev in revisions] == [1, 2]
        assert revisions[0].duration_minutes == 30
        assert revisions[1].duration_minutes == 15
        return

    if case.case_id == "tool_failure":
        failing_meeting_repo = FailingMeetingHistoryRepository()
        # Model attempts get_meeting_history 3 times; safeguard allows 1 initial + 1 retry
        # and caps the 3rd attempt with TOOL_RETRY_LIMIT_EXCEEDED, then model finishes cleanly.
        history_call = ("get_meeting_history", {"contact_id": "cnt_0001", "limit": 5})
        mock_llm = DeterministicMockCoachLlm(
            [
                _tool_call_response(history_call),
                _tool_call_response(history_call),
                _tool_call_response(history_call),
                _json_brief_response(_valid_brief_json_payload()),
            ]
        )
        harness = _WorkflowHarness(
            mock_llm=mock_llm,
            meeting_repo=failing_meeting_repo,
            safeguards=BriefWorkflowSafeguardConfig(
                max_model_invocations=6,
                max_tool_retries=1,
            ),
        )
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        result = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
        )

        assert result.diagnostics.terminal_state is case.expected_terminal_state
        # Only 2 actual ADK tool invocations executed; the 3rd was blocked by the retry cap
        assert result.diagnostics.tool_invocations == 2
        assert "meeting_history" in result.diagnostics.degraded_sources
        assert "get_meeting_history" in result.diagnostics.degraded_sources
        assert result.brief.version == 1
        return

    if case.case_id == "invalid_model_output_repaired":
        flawed_first_candidate = _valid_brief_json_payload()
        # Violates opener count (only 1) AND fabricates unsupported degree ("PhD from MIT")
        flawed_first_candidate["conversation_openers"] = [
            "Hi Priya, congratulations on your PhD from MIT—can I pick your brain?"
        ]

        captured_repair_prompts: list[str] = []

        def _second_attempt_step(req: LlmRequest, _idx: int) -> LlmResponse:
            user_texts = [
                part.text
                for content in (req.contents or [])
                for part in (content.parts or [])
                if part.text
            ]
            captured_repair_prompts.extend(user_texts)
            return _json_brief_response(_valid_brief_json_payload())

        mock_llm = DeterministicMockCoachLlm(
            [
                _json_brief_response(flawed_first_candidate),
                _second_attempt_step,
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        result = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
        )

        assert result.diagnostics.terminal_state is case.expected_terminal_state
        assert result.diagnostics.attempt_count == 2
        assert result.diagnostics.regeneration_count == 1
        assert result.diagnostics.model_invocations == 2
        assert any("CORRECTIVE REGENERATION REQUIRED" in text for text in captured_repair_prompts)
        assert result.brief.version == 1
        return

    if case.case_id == "invalid_model_output_unrecoverable":
        # Attempt 1 is malformed JSON; Attempt 2 has unsupported biographical claim & 1 opener.
        # Workflow MUST stop after 1 corrective regeneration without an unbounded loop.
        still_bad = _valid_brief_json_payload()
        still_bad["conversation_openers"] = ["Only one opener."]
        mock_llm = DeterministicMockCoachLlm(
            [
                _json_brief_response("not valid json {{{{"),
                _json_brief_response(still_bad),
                # Extra sentinel step that MUST NEVER be consumed
                _json_brief_response(_valid_brief_json_payload()),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        assert case.expect_exception is not None
        with pytest.raises(case.expect_exception) as exc_info:
            await harness.workflow.execute_generation(
                principal=alice,
                contact_id=contact.id,
                purpose=MeetingPurpose.COFFEE_CHAT,
                tone=MeetingTone.WARM_CASUAL,
                meeting_objective=objective,
                duration_minutes=30,
            )

        err = exc_info.value
        assert isinstance(err, ModelOutputValidationError)
        assert err.code == "MODEL_OUTPUT_VALIDATION_ERROR"
        diag = err.workflow_diagnostics
        assert diag is not None
        assert diag.terminal_state is case.expected_terminal_state
        assert diag.regeneration_count == 1
        assert diag.model_invocations == 2
        assert len(mock_llm.captured_requests) == 2
        assert await harness.meeting_repo.list_by_owner(alice.user_id) == []
        return

    if case.case_id == "model_timeout":
        mock_llm = DeterministicMockCoachLlm(
            [
                DelayedTimeoutStep(sleep_seconds=0.25),
                # Must NOT run corrective regeneration after timeout
                _json_brief_response(_valid_brief_json_payload()),
            ]
        )
        harness = _WorkflowHarness(
            mock_llm=mock_llm,
            model_timeout_seconds=0.05,
        )
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        assert case.expect_exception is not None
        with pytest.raises(case.expect_exception) as exc_info:
            await harness.workflow.execute_generation(
                principal=alice,
                contact_id=contact.id,
                purpose=MeetingPurpose.COFFEE_CHAT,
                tone=MeetingTone.WARM_CASUAL,
                meeting_objective=objective,
                duration_minutes=30,
            )

        err = exc_info.value
        assert isinstance(err, ModelTimeoutError)
        assert err.code == "MODEL_TIMEOUT"
        diag = err.workflow_diagnostics
        assert diag is not None
        assert diag.terminal_state is case.expected_terminal_state
        assert diag.regeneration_count == 0
        assert len(mock_llm.captured_requests) == 1
        assert await harness.meeting_repo.list_by_owner(alice.user_id) == []
        return

    if case.case_id == "duplicate_request":
        mock_llm = DeterministicMockCoachLlm(
            [
                _json_brief_response(_valid_brief_json_payload()),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )

        first = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
            idempotency_key="idem_dup_01",
            request_id="req_dup_first",
        )
        replay = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective=objective,
            duration_minutes=30,
            idempotency_key="idem_dup_01",
            request_id="req_dup_second",
        )

        assert replay.diagnostics.terminal_state is case.expected_terminal_state
        assert replay.diagnostics.replayed is True
        assert replay.diagnostics.model_invocations == 0
        assert replay.diagnostics.tool_invocations == 0
        assert replay.brief.id == first.brief.id
        assert replay.brief.version == 1
        assert len(mock_llm.captured_requests) == 1
        assert len(await harness.meeting_repo.list_by_owner(alice.user_id)) == 1

        # Reusing same idempotency_key with mutated payload raises ConflictError
        with pytest.raises(ConflictError) as conflict_exc:
            await harness.workflow.execute_generation(
                principal=alice,
                contact_id=contact.id,
                purpose=MeetingPurpose.COFFEE_CHAT,
                tone=MeetingTone.WARM_CASUAL,
                meeting_objective="Completely different meeting objective.",
                duration_minutes=30,
                idempotency_key="idem_dup_01",
            )
        assert conflict_exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"
        return

    if case.case_id == "repeated_refinement":
        mock_llm = DeterministicMockCoachLlm(
            [
                # v1: initial structured_executive 45-min brief
                _json_brief_response(
                    _valid_brief_json_payload(duration_minutes=45, opener_style="warm")
                ),
                # v2: "Make the questions less formal"
                _json_brief_response(
                    _valid_brief_json_payload(
                        duration_minutes=45,
                        opener_style="casual",
                        revision_summary="Shifted openers and phrasing to warm casual tone.",
                    )
                ),
                # v3: "Focus more on their engineering career."
                _json_brief_response(
                    _valid_brief_json_payload(
                        duration_minutes=45,
                        opener_style="casual",
                        question_theme="engineering_career",
                        revision_summary="Refocused questions around engineering career growth.",
                    )
                ),
                # v4: fresh customer discovery questions after caller says prior were asked
                _json_brief_response(
                    _valid_brief_json_payload(
                        duration_minutes=45,
                        opener_style="casual",
                        question_theme="customer_discovery",
                        revision_summary=(
                            "Replaced prior questions with fresh customer discovery prompts."
                        ),
                    )
                ),
            ]
        )
        harness = _WorkflowHarness(mock_llm=mock_llm)
        contact = await harness.contact_service.create_contact(
            principal=alice,
            name="Priya Nair",
            title="Engineering Director",
            organization="Nimbus Cloud",
        )
        t0 = harness.clock.now_utc()
        await harness.memory_repo.save(
            Memory(
                id="mem_established_01",
                owner_user_id=alice.user_id,
                scope=MemoryScope.CONTACT,
                contact_id=contact.id,
                memory_type=MemoryType.COUNTERPART_BACKGROUND,
                text="Priya leads multi-region reliability at Nimbus Cloud.",
                source=MemorySource(
                    source_type=MemorySourceType.DIRECT_USER_INPUT,
                    recorded_at=t0,
                ),
                consent_status=ConsentStatus.APPROVED,
                created_at=t0,
                updated_at=t0,
            )
        )

        v1 = await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.NETWORKING,
            tone=MeetingTone.STRUCTURED_EXECUTIVE,
            meeting_objective=objective,
            duration_minutes=45,
        )
        v2 = await harness.workflow.execute_refinement(
            principal=alice,
            brief_id=v1.brief.id,
            instructions="Make the questions less formal",
            expected_version=1,
        )
        v3 = await harness.workflow.execute_refinement(
            principal=alice,
            brief_id=v1.brief.id,
            instructions="Focus more on their engineering career.",
            expected_version=2,
        )
        v4 = await harness.workflow.execute_refinement(
            principal=alice,
            brief_id=v1.brief.id,
            instructions=(
                "I have already asked these questions before. "
                "Give me more customer discovery questions"
            ),
            expected_version=3,
        )

        assert v4.diagnostics.terminal_state is case.expected_terminal_state
        assert v2.brief.tone is MeetingTone.WARM_CASUAL
        assert v3.brief.version == 3
        assert v4.brief.version == 4
        assert v4.diagnostics.previous_version == 3
        # Unchanged fields & established memories preserved across refinements
        assert v4.brief.id == v1.brief.id
        assert v4.brief.meeting_id == v1.brief.meeting_id
        assert v4.brief.contact_id == contact.id
        assert v4.brief.created_at == v1.brief.created_at
        assert "mem_established_01" in v4.brief.referenced_memory_ids

        # All 4 versions preserved in revision store without silent overwrite
        revisions = await harness.brief_repo.list_revisions(alice.user_id, v1.brief.id)
        assert [rev.version for rev in revisions] == [1, 2, 3, 4]
        assert revisions[0].tone is MeetingTone.STRUCTURED_EXECUTIVE
        assert revisions[1].tone is MeetingTone.WARM_CASUAL
        assert {q.id for q in revisions[2].suggested_questions}.isdisjoint(
            {q.id for q in revisions[3].suggested_questions}
        )
        return

    pytest.fail(f"Unhandled workflow table case: {case.case_id}")


def test_deterministic_brief_quality_checks_catch_all_policy_violations() -> None:
    now = datetime(2026, 11, 23, 15, 0, 0, tzinfo=UTC)
    contact = Contact(
        id="cnt_q",
        owner_user_id="usr_alice",
        name="Jordan Lee",
        title="Staff Engineer",
        organization="Acme Cloud",
        created_at=now,
        updated_at=now,
    )
    meeting = Meeting(
        id="mtg_q",
        owner_user_id="usr_alice",
        contact_id=contact.id,
        purpose=MeetingPurpose.MENTORSHIP,
        tone=MeetingTone.WARM_CASUAL,
        objective="Learn staff-level technical architecture leadership habits.",
        duration_minutes=30,
        created_at=now,
        updated_at=now,
    )
    context = BriefPreparationContext(owner_user_id="usr_alice", contact=contact)

    bad_content = GeneratedBriefContent(
        contact_context=(
            "Jordan Lee graduated from Stanford with a PhD and is married to a founder."
        ),
        meeting_objective=meeting.objective,
        conversation_openers=["Pursuant to our calendar invite, can I pick your brain?"],
        time_boxed_agenda=[
            TimeBoxedAgendaItem(
                title="Single Block",
                duration_minutes=20,
                description="Everything in one segment.",
            )
        ],
        suggested_questions=[
            ConversationQuestion(
                id="q_1",
                question="What architecture decisions shaped your staff scope?",
                rationale="Good one.",
            ),
            ConversationQuestion(
                id="q_2",
                question="Which architecture decisions shaped your staff scope?",
                rationale="Connects to architecture leadership objective.",
            ),
        ],
        suggested_follow_up_topics=["Send recap"],
        referenced_memory_ids=["mem_hallucinated_99"],
    )

    report = evaluate_brief_quality(
        bad_content,
        meeting=meeting,
        context=context,
        target_duration_minutes=30,
        target_tone=MeetingTone.WARM_CASUAL,
    )
    assert report.passed is False
    codes = {v.code for v in report.violations}
    assert "OPENER_COUNT_OUT_OF_RANGE" in codes
    assert "QUESTION_COUNT_OUT_OF_RANGE" in codes
    assert "AGENDA_DURATION_MISMATCH" in codes
    assert "AGENDA_UNREALISTIC_STRUCTURE" in codes
    assert "RATIONALE_NOT_LINKED_TO_GOAL" in codes
    assert "INAPPROPRIATE_TONE_OR_CLICHE" in codes
    assert "TONE_MISMATCH" in codes
    assert "UNGROUNDED_MEMORY_REFERENCE" in codes
    assert "UNSUPPORTED_BIOGRAPHICAL_CLAIM" in codes
    assert "REDUNDANT_QUESTIONS" in codes


@pytest.mark.asyncio
async def test_model_invocation_budget_cap_and_unified_correlation_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Model tries to loop tool calls beyond max_model_invocations=2
    mock_llm = DeterministicMockCoachLlm(
        [
            _tool_call_response(("get_user_preferences", {"max_preference_memories": 5})),
            _tool_call_response(("get_contact_context", {"contact_id": "cnt_0001"})),
            _json_brief_response(_valid_brief_json_payload()),
        ]
    )
    harness = _WorkflowHarness(
        mock_llm=mock_llm,
        safeguards=BriefWorkflowSafeguardConfig(max_model_invocations=2),
    )
    alice = AuthenticatedPrincipal(user_id="usr_alice")
    contact = await harness.contact_service.create_contact(
        principal=alice,
        name="Priya Nair",
        organization="Nimbus Cloud",
    )

    caplog.set_level(logging.INFO)
    with pytest.raises(ModelExecutionError) as exc_info:
        await harness.workflow.execute_generation(
            principal=alice,
            contact_id=contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective="Understand platform reliability trade-offs.",
            duration_minutes=30,
            request_id="req_corr_900",
            trace_id="trc_corr_900",
        )

    assert exc_info.value.code == "MODEL_INVOCATION_LIMIT_EXCEEDED"
    diag = exc_info.value.workflow_diagnostics
    assert diag is not None
    assert diag.terminal_state is BriefWorkflowTerminalState.FAILED_MODEL_ERROR
    assert diag.request_id == "req_corr_900"
    assert diag.trace_id == "trc_corr_900"
    assert diag.model_invocations == 2

    formatter = StructuredJsonFormatter()
    tracked_loggers = ("app.application.brief_workflow", "app.plugins.workflow_safeguards")
    workflow_json_logs = [
        json.loads(formatter.format(rec))
        for rec in caplog.records
        if rec.name.startswith(tracked_loggers)
    ]
    assert workflow_json_logs
    assert all(entry.get("request_id") == "req_corr_900" for entry in workflow_json_logs)
    assert all(entry.get("trace_id") == "trc_corr_900" for entry in workflow_json_logs)


def test_http_brief_workflow_endpoints_idempotency_revisions_and_error_classification(
    tmp_path: Path,
) -> None:
    mock_llm = DeterministicMockCoachLlm(
        [
            # 1. Initial generation
            _tool_call_response(
                ("get_contact_context", {"contact_id": "cnt_0001", "max_memories": 5})
            ),
            _json_brief_response(_valid_brief_json_payload(duration_minutes=30)),
            # 2. Refinement to 15 minutes
            _json_brief_response(
                _valid_brief_json_payload(
                    duration_minutes=15,
                    question_count=5,
                    revision_summary="Condensed to 15 minutes.",
                )
            ),
            # 3. Timeout failure -> HTTP 504
            DelayedTimeoutStep(sleep_seconds=0.25),
            # 4. Unrecoverable invalid output -> HTTP 422 MODEL_OUTPUT_VALIDATION_ERROR
            _json_brief_response("invalid json payload"),
            _json_brief_response("still invalid json payload"),
        ]
    )

    clock = DeterministicStepClock()
    ids = SequentialIdGenerator()
    prefs_repo = InMemoryUserPreferencesRepository()
    contact_repo = InMemoryContactRepository()
    meeting_repo = InMemoryMeetingRepository()
    brief_repo = InMemoryBriefRepository()
    proposal_repo = InMemoryMemoryProposalRepository()
    memory_repo = InMemoryMemoryRepository()
    idempotency_repo = InMemoryWorkflowIdempotencyRepository()
    proposal_agent = FakeMemoryProposalAgent()

    settings = AppSettings(
        environment="test",
        otel_to_cloud=False,
        http_timeout_seconds=0.05,
        web_dist_dir=tmp_path / "no-dist",
    )
    adk_adapter = AdkConversationCoachBriefAdapter(
        tool_dependencies=CoachingToolDependencies(
            preferences_reader=prefs_repo,
            contact_reader=contact_repo,
            meeting_reader=meeting_repo,
            memory_reader=memory_repo,
            proposal_stager=proposal_repo,
            proposal_agent=proposal_agent,
            clock=clock,
            id_generator=ids,
            io_timeout_seconds=1.0,
        ),
        settings=settings,
        model_override=mock_llm,
        model_timeout_seconds=0.05,
    )
    container = ServiceContainer(
        clock=clock,
        id_generator=ids,
        authenticator=FakeAuthenticator(
            {"tok-alice": AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")}
        ),
        preferences_repo=prefs_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        proposal_repo=proposal_repo,
        memory_repo=memory_repo,
        brief_agent=adk_adapter,
        proposal_agent=proposal_agent,
        idempotency_repo=idempotency_repo,
    )

    with TestClient(create_app(settings, service_container=container)) as client:
        headers = {"Authorization": "Bearer tok-alice", "X-Request-ID": "req_http_01"}
        contact_id = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={"name": "Priya Nair", "organization": "Nimbus Cloud"},
        ).json()["id"]

        gen_body = {
            "contact_id": contact_id,
            "purpose": "coffee_chat",
            "tone": "warm_casual",
            "meeting_objective": "Understand distributed platform reliability trade-offs.",
            "duration_minutes": 30,
        }
        gen_resp = client.post(
            "/api/v1/briefs/generate",
            headers={**headers, "Idempotency-Key": "idem_http_gen_1"},
            json=gen_body,
        )
        assert gen_resp.status_code == 201
        assert gen_resp.headers["X-Request-ID"] == "req_http_01"
        gen_json = gen_resp.json()
        brief_id = gen_json["id"]
        assert gen_json["workflow"]["terminal_state"] == "completed"
        assert gen_json["workflow"]["replayed"] is False
        assert gen_json["workflow"]["tool_invocations"] == 1

        # Duplicate HTTP request with same Idempotency-Key replays without touching LLM
        dup_resp = client.post(
            "/api/v1/briefs/generate",
            headers={**headers, "Idempotency-Key": "idem_http_gen_1"},
            json=gen_body,
        )
        assert dup_resp.status_code == 201
        dup_json = dup_resp.json()
        assert dup_json["id"] == brief_id
        assert dup_json["workflow"]["terminal_state"] == "completed_idempotent_replay"
        assert dup_json["workflow"]["replayed"] is True
        assert dup_json["workflow"]["model_invocations"] == 0

        # Refine with natural-language 15-minute instruction
        rev_resp = client.post(
            f"/api/v1/briefs/{brief_id}/revise",
            headers={"Authorization": "Bearer tok-alice", "X-Request-ID": "req_http_02"},
            json={"instructions": "I only have 15 minutes", "expected_version": 1},
        )
        assert rev_resp.status_code == 200
        rev_json = rev_resp.json()
        assert rev_json["version"] == 2
        assert rev_json["duration_minutes"] == 15
        assert rev_json["workflow"]["previous_version"] == 1

        # Inspect immutable revision history via GET /api/v1/briefs/{id}/revisions
        hist_resp = client.get(f"/api/v1/briefs/{brief_id}/revisions", headers=headers)
        assert hist_resp.status_code == 200
        hist_json = hist_resp.json()
        assert hist_json["total"] == 2
        assert [item["version"] for item in hist_json["items"]] == [1, 2]
        assert hist_json["items"][0]["duration_minutes"] == 30
        assert hist_json["items"][1]["duration_minutes"] == 15

        # Model timeout -> HTTP 504 MODEL_TIMEOUT
        timeout_resp = client.post(
            "/api/v1/briefs/generate",
            headers={"Authorization": "Bearer tok-alice", "X-Request-ID": "req_http_timeout"},
            json=gen_body,
        )
        assert timeout_resp.status_code == 504
        assert timeout_resp.json()["error"]["code"] == "MODEL_TIMEOUT"
        assert timeout_resp.json()["error"]["trace_id"] == "req_http_timeout"

        # Invalid model output after single repair -> HTTP 422 MODEL_OUTPUT_VALIDATION_ERROR
        invalid_out_resp = client.post(
            "/api/v1/briefs/generate",
            headers={"Authorization": "Bearer tok-alice", "X-Request-ID": "req_http_bad_out"},
            json=gen_body,
        )
        assert invalid_out_resp.status_code == 422
        err_body = invalid_out_resp.json()["error"]
        assert err_body["code"] == "MODEL_OUTPUT_VALIDATION_ERROR"
        assert err_body["details"]


def test_parse_refinement_overrides_handles_natural_language_directives() -> None:
    res = parse_refinement_overrides(
        "Make the questions less formal; I only have 15 minutes and already asked these before.",
        explicit_duration_minutes=None,
        explicit_tone=None,
        fallback_duration_minutes=45,
        fallback_tone=MeetingTone.STRUCTURED_EXECUTIVE,
    )
    assert res.target_duration_minutes == 15
    assert res.target_tone is MeetingTone.WARM_CASUAL
    assert res.less_formal_requested is True
    assert res.avoid_prior_questions is True
