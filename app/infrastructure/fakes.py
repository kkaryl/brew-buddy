"""Async local fake repositories, authenticator, and deterministic agent adapters for Brew."""

from __future__ import annotations

import asyncio
import re
import threading
import uuid
from collections.abc import Mapping, Sequence

from app.domain.brief_quality import parse_refinement_overrides
from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.health import ClockPort
from app.domain.memory_lifecycle import (
    MemoryRelationKind,
    classify_candidate_against_existing,
    detect_sensitive_or_third_party_assumption,
    ensure_attributed_epistemic_text,
)
from app.domain.models import (
    AuthenticatedPrincipal,
    BriefPreparationContext,
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    PreparationBrief,
    TimeBoxedAgendaItem,
    UserPreferences,
    WorkflowIdempotencyRecord,
)
from app.domain.ports import (
    AuthenticatorPort,
    BriefAttemptMetrics,
    BriefCoachAgentPort,
    BriefRepository,
    ContactRepository,
    GeneratedBriefContent,
    IdGeneratorPort,
    MeetingRepository,
    MemoryProposalAgentPort,
    MemoryProposalRepository,
    MemoryRepository,
    ProposedMemoryCandidate,
    UserPreferencesRepository,
    WorkflowIdempotencyRepository,
)
from app.domain.types import (
    BriefWorkflowOperation,
    ConsentStatus,
    MeetingDurationMinutes,
    MeetingPurpose,
    MeetingTone,
    MemoryLifecycleState,
    MemoryScope,
    MemoryType,
    ProposalStatus,
)
from app.infrastructure.clock import SystemUtcClock

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")

DEFAULT_FAKE_TOKENS: dict[str, AuthenticatedPrincipal] = {
    "brew-dev-token-alice": AuthenticatedPrincipal(
        user_id="usr_alice",
        display_name="Alice Chen",
    ),
    "brew-dev-token-bob": AuthenticatedPrincipal(
        user_id="usr_bob",
        display_name="Bob Rivera",
    ),
}


def scrub_basic_pii(text: str) -> str:
    """Deterministically redact email addresses and phone numbers from free-form text."""
    scrubbed = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    return _PHONE_RE.sub("[REDACTED_PHONE]", scrubbed)


class UuidIdGenerator:
    """Collision-resistant prefixed identifier generator."""

    def new_id(self, prefix: str) -> str:
        """Generate a URL-safe prefixed identifier."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SequentialIdGenerator:
    """Deterministic sequential ID generator useful for reproducible tests."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    def new_id(self, prefix: str) -> str:
        """Return the next sequential ID for ``prefix``."""
        with self._lock:
            next_num = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = next_num
            return f"{prefix}_{next_num:04d}"


class FakeAuthenticator:
    """In-memory bearer token authenticator mapping opaque tokens to user principals."""

    def __init__(
        self,
        tokens: Mapping[str, AuthenticatedPrincipal] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, AuthenticatedPrincipal] = dict(
            tokens if tokens is not None else DEFAULT_FAKE_TOKENS
        )

    def register_token(self, token: str, principal: AuthenticatedPrincipal) -> None:
        """Register or replace an in-memory bearer token for testing."""
        cleaned = token.strip()
        if not cleaned:
            msg = "Token cannot be empty."
            raise ValueError(msg)
        with self._lock:
            self._tokens[cleaned] = principal

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Verify ``token`` and return the bound ``AuthenticatedPrincipal``."""
        cleaned = token.strip()
        if not cleaned:
            raise AuthenticationError("Bearer token cannot be empty.")
        with self._lock:
            principal = self._tokens.get(cleaned)
        if principal is None:
            raise AuthenticationError("Invalid or unrecognized bearer token.")
        return principal


class InMemoryUserPreferencesRepository:
    """Async fake repository mirroring ``users/{uid}/preferences/default``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, UserPreferences] = {}

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id)

    async def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        async with self._lock:
            existing = self._by_owner.get(preferences.owner_user_id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"UserPreferences for '{preferences.owner_user_id}' already exist.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="UserPreferences",
                        entity_id=preferences.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="UserPreferences",
                        entity_id=existing.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            self._by_owner[preferences.owner_user_id] = preferences
            return preferences


class InMemoryContactRepository:
    """Async fake repository mirroring ``users/{uid}/contacts/{contactId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Contact]] = {}

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(contact_id)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        async with self._lock:
            return any(contact_id in user_contacts for user_contacts in self._by_owner.values())

    async def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        async with self._lock:
            items = list(self._by_owner.get(owner_user_id, {}).values())
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(contact.owner_user_id, {})
            existing = user_bucket.get(contact.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Contact '{contact.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Contact", entity_id=contact.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Contact",
                        entity_id=contact.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[contact.id] = contact
            return contact


class InMemoryMeetingRepository:
    """Async fake repository mirroring ``users/{uid}/meetings/{meetingId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Meeting]] = {}

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(meeting_id)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        async with self._lock:
            return any(meeting_id in user_meetings for user_meetings in self._by_owner.values())

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        async with self._lock:
            items = [
                meeting
                for meeting in self._by_owner.get(owner_user_id, {}).values()
                if contact_id is None or meeting.contact_id == contact_id
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(meeting.owner_user_id, {})
            existing = user_bucket.get(meeting.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Meeting '{meeting.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Meeting",
                        entity_id=meeting.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[meeting.id] = meeting
            return meeting


class InMemoryBriefRepository:
    """Async fake repository mirroring ``users/{uid}/briefs/{briefId}`` and immutable revisions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, PreparationBrief]] = {}
        self._revisions_by_owner: dict[str, dict[str, dict[int, PreparationBrief]]] = {}

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(brief_id)

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        async with self._lock:
            return any(brief_id in user_briefs for user_briefs in self._by_owner.values())

    async def list_by_meeting(
        self,
        owner_user_id: str,
        meeting_id: str,
    ) -> list[PreparationBrief]:
        async with self._lock:
            items = [
                brief
                for brief in self._by_owner.get(owner_user_id, {}).values()
                if brief.meeting_id == meeting_id
            ]
        return sorted(items, key=lambda item: (item.version, item.id))

    async def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(brief.owner_user_id, {})
            existing = user_bucket.get(brief.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"PreparationBrief '{brief.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="PreparationBrief",
                        entity_id=brief.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="PreparationBrief",
                        entity_id=brief.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[brief.id] = brief
            rev_bucket = self._revisions_by_owner.setdefault(brief.owner_user_id, {}).setdefault(
                brief.id, {}
            )
            rev_bucket[brief.version] = brief
            return brief

    async def list_revisions(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> list[PreparationBrief]:
        async with self._lock:
            rev_map = self._revisions_by_owner.get(owner_user_id, {}).get(brief_id, {})
            items = list(rev_map.values())
        return sorted(items, key=lambda item: item.version)

    async def get_revision(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> PreparationBrief | None:
        async with self._lock:
            return self._revisions_by_owner.get(owner_user_id, {}).get(brief_id, {}).get(version)


class InMemoryWorkflowIdempotencyRepository:
    """Async fake repository storing deduplication records per ``(owner, operation, key)``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._records: dict[tuple[str, str, str], WorkflowIdempotencyRecord] = {}

    async def get(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> WorkflowIdempotencyRecord | None:
        async with self._lock:
            return self._records.get((owner_user_id, operation.value, idempotency_key))

    async def save(
        self,
        record: WorkflowIdempotencyRecord,
    ) -> WorkflowIdempotencyRecord:
        async with self._lock:
            self._records[
                (record.owner_user_id, record.operation.value, record.idempotency_key)
            ] = record
            return record


class InMemoryMemoryProposalRepository:
    """Async fake repository mirroring ``users/{uid}/memoryProposals/{proposalId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, MemoryProposal]] = {}

    async def get_for_owner(
        self,
        owner_user_id: str,
        proposal_id: str,
    ) -> MemoryProposal | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(proposal_id)

    async def exists_for_any_owner(self, proposal_id: str) -> bool:
        async with self._lock:
            return any(proposal_id in user_proposals for user_proposals in self._by_owner.values())

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        async with self._lock:
            items = [
                proposal
                for proposal in self._by_owner.get(owner_user_id, {}).values()
                if (status is None or proposal.status is status)
                and (contact_id is None or proposal.contact_id == contact_id)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(proposal.owner_user_id, {})
            existing = user_bucket.get(proposal.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"MemoryProposal '{proposal.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="MemoryProposal",
                        entity_id=proposal.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="MemoryProposal",
                        entity_id=proposal.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[proposal.id] = proposal
            return proposal


class InMemoryMemoryRepository:
    """Async fake repository mirroring ``users/{uid}/memories/{memoryId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Memory]] = {}
        self._deleted_by_owner: dict[str, dict[str, Memory]] = {}

    async def get_for_owner(self, owner_user_id: str, memory_id: str) -> Memory | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(memory_id)

    async def exists_for_any_owner(self, memory_id: str) -> bool:
        async with self._lock:
            return any(memory_id in user_memories for user_memories in self._by_owner.values())

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
        include_superseded: bool = False,
    ) -> list[Memory]:
        async with self._lock:
            items = [
                memory
                for memory in self._by_owner.get(owner_user_id, {}).values()
                if (include_revoked or memory.consent_status is ConsentStatus.APPROVED)
                and (include_superseded or memory.lifecycle_state is MemoryLifecycleState.APPROVED)
                and (scope is None or memory.scope is scope)
                and (contact_id is None or memory.contact_id == contact_id)
                and (memory_type is None or memory.memory_type is memory_type)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(memory.owner_user_id, {})
            existing = user_bucket.get(memory.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Memory '{memory.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Memory", entity_id=memory.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Memory",
                        entity_id=memory.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[memory.id] = memory
            return memory

    async def delete(
        self,
        owner_user_id: str,
        memory_id: str,
        *,
        expected_version: int | None = None,
        deleted_snapshot: Memory | None = None,
    ) -> None:
        async with self._lock:
            user_bucket = self._by_owner.get(owner_user_id, {})
            existing = user_bucket.get(memory_id)
            if existing is None:
                raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
            if expected_version is not None and existing.version != expected_version:
                raise VersionConflictError(
                    entity_name="Memory",
                    entity_id=memory_id,
                    expected_version=expected_version,
                    actual_version=existing.version,
                )
            tombstone = deleted_snapshot or existing.mark_deleted(deleted_at=existing.updated_at)
            self._deleted_by_owner.setdefault(owner_user_id, {})[memory_id] = tombstone
            del user_bucket[memory_id]

    async def get_deleted_for_owner(
        self,
        owner_user_id: str,
        memory_id: str,
    ) -> Memory | None:
        async with self._lock:
            return self._deleted_by_owner.get(owner_user_id, {}).get(memory_id)


def _build_time_boxed_agenda(
    *,
    duration_minutes: int,
    purpose: MeetingPurpose,
) -> list[TimeBoxedAgendaItem]:
    opening_minutes = max(1, duration_minutes // 5)
    closing_minutes = max(1, duration_minutes // 5)
    core_minutes = duration_minutes - opening_minutes - closing_minutes
    purpose_label = purpose.value.replace("_", " ")
    return [
        TimeBoxedAgendaItem(
            title="Rapport & Context Alignment",
            duration_minutes=opening_minutes,
            description=(
                f"Set a welcoming tone, reconnect on shared context, and confirm the "
                f"{duration_minutes}-minute timebox."
            ),
        ),
        TimeBoxedAgendaItem(
            title=f"Core {purpose_label.title()} Discussion",
            duration_minutes=core_minutes,
            description=(
                f"Explore prioritized questions aligned with the {purpose_label} objective "
                f"and listen for concrete examples."
            ),
        ),
        TimeBoxedAgendaItem(
            title="Synthesis & Next Steps",
            duration_minutes=closing_minutes,
            description=(
                "Summarize takeaways, confirm any agreed follow-ups, and express appreciation."
            ),
        ),
    ]


def _compose_contact_context(context: BriefPreparationContext) -> str:
    contact = context.contact
    descriptor_parts = [contact.name]
    if contact.title:
        descriptor_parts.append(contact.title)
    if contact.role and contact.role != contact.title:
        descriptor_parts.append(contact.role)
    if contact.organization:
        descriptor_parts.append(f"at {contact.organization}")

    summary = ", ".join(descriptor_parts) + "."
    if contact.context_notes:
        summary = f"{summary} Context: {contact.context_notes}"

    if context.recent_meetings:
        recent_objectives = "; ".join(m.objective[:100] for m in context.recent_meetings[:2])
        summary = f"{summary} Recent meetings: {recent_objectives}"

    if context.contact_memories:
        joined = "; ".join(mem.text for mem in context.contact_memories[:3])
        summary = f"{summary} Prior approved notes: {joined}"

    return summary[:2000]


class FakeBriefCoachAgent:
    """Async deterministic fake ``BriefCoachAgentPort`` consuming ``BriefPreparationContext``."""

    async def generate_brief(
        self,
        *,
        meeting: Meeting,
        context: BriefPreparationContext,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        del corrective_feedback
        if attempt_metrics is not None:
            attempt_metrics.model_invocations += 1

        contact = context.contact
        user_preferences = context.user_preferences
        question_count = (
            user_preferences.preferred_question_count if user_preferences is not None else 6
        )
        question_count = max(1, min(question_count, 8))

        tone_label = meeting.tone.value.replace("_", " ")
        purpose_label = meeting.purpose.value.replace("_", " ")
        openers = [
            (
                f"Thanks for carving out {meeting.duration_minutes} minutes, {contact.name}—"
                f"looking forward to our {purpose_label} conversation ({tone_label} style)."
            ),
            (
                f"Before we dive into {meeting.objective[:120]}, I'd love to hear what has been "
                f"top of mind for you recently."
            ),
        ]

        base_templates: list[tuple[str, str, str]] = [
            (
                (
                    f"Looking at {meeting.objective[:120]}, "
                    "what trade-offs have mattered most in practice?"
                ),
                (
                    f"Anchors the {purpose_label} objective in real-world decisions "
                    "rather than generic advice."
                ),
                "core_objective",
            ),
            (
                (
                    "What signal tells you an initiative in your domain is on the right track, "
                    f"{contact.name}?"
                ),
                "Surfaces concrete evaluation criteria aligned with the meeting goal.",
                "perspective",
            ),
            (
                "What common misconception do people bring when approaching this space?",
                "Invites candid nuance and memorable insights relevant to our discussion.",
                "nuance",
            ),
            (
                "Where do you see the biggest upcoming shift over the next two quarters?",
                "Opens forward-looking roadmap context for potential future conversations.",
                "outlook",
            ),
            (
                "Which habit or operating cadence helped your team navigate growing complexity?",
                "Connects practical execution lessons directly to our conversation objective.",
                "execution",
            ),
            (
                "Who or what resource shaped how you think about this problem?",
                "Creates natural follow-up threads and shared learning context.",
                "resources",
            ),
            (
                "When priorities collide, what framework helps you decide what to defer?",
                "Highlights concrete prioritization trade-offs tied to the meeting purpose.",
                "prioritization",
            ),
            (
                "Before we wrap, is there any context or connection that would be useful to you?",
                "Closes with reciprocity appropriate to relationship building.",
                "closing",
            ),
        ]

        questions = [
            ConversationQuestion(
                id=f"q_{idx + 1}",
                question=prompt[:400],
                rationale=rationale[:500],
                category=category,
            )
            for idx, (prompt, rationale, category) in enumerate(base_templates[:question_count])
        ]

        follow_ups = [
            f"Share a concise recap of key takeaways with {contact.name}.",
            (
                "Follow through on resources or next steps discussed around "
                f"{meeting.objective[:100]}."
            ),
        ]

        return GeneratedBriefContent(
            contact_context=_compose_contact_context(context),
            meeting_objective=meeting.objective,
            conversation_openers=openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=meeting.duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=questions,
            suggested_follow_up_topics=follow_ups,
            referenced_memory_ids=context.referenced_memory_ids,
            revision_summary=None,
        )

    async def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        context: BriefPreparationContext,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        del corrective_feedback
        if attempt_metrics is not None:
            attempt_metrics.model_invocations += 1

        contact = context.contact
        cleaned_instruction = scrub_basic_pii(instructions.strip())
        tone_label = target_tone.value.replace("_", " ")
        resolution = parse_refinement_overrides(
            cleaned_instruction,
            explicit_duration_minutes=target_duration_minutes,
            explicit_tone=target_tone,
            fallback_duration_minutes=current_brief.duration_minutes,
            fallback_tone=current_brief.tone,
        )

        updated_openers = [
            (
                f"Hi {contact.name}, glad we could catch up for {target_duration_minutes} "
                f"minutes ({tone_label})—excited to explore {cleaned_instruction[:140]}."
            ),
            (
                current_brief.conversation_openers[1]
                if len(current_brief.conversation_openers) > 1
                else (
                    f"Before jumping into {current_brief.meeting_objective[:110]}, how has "
                    "your week been unfolding?"
                )
            ),
        ]

        desired_count = len(current_brief.suggested_questions)
        rev_num = current_brief.version + 1

        if resolution.focus_customer_discovery:
            discovery_pool = [
                (
                    "Walk me through how your team currently handles this workflow end to end?",
                    "Grounds customer discovery in real current-state workflow behavior.",
                    "discovery_workflow",
                ),
                (
                    "Which step in that process creates the sharpest bottleneck or manual cost?",
                    "Identifies high-friction customer pain points worth solving.",
                    "discovery_pain",
                ),
                (
                    "What workarounds or tools have you already evaluated to solve this problem?",
                    "Surfaces existing alternatives and switching barriers for discovery.",
                    "discovery_alternatives",
                ),
                (
                    "How do you measure whether an onboarding or workflow improvement succeeded?",
                    "Links customer discovery findings to concrete evaluation metrics.",
                    "discovery_metrics",
                ),
                (
                    "Who else on the team feels this friction most acutely during adoption?",
                    "Maps stakeholder roles and adoption dynamics for the objective.",
                    "discovery_stakeholders",
                ),
                (
                    "What would need to be true for fixing this problem to become urgent now?",
                    "Tests priority and timing constraints against our discovery goal.",
                    "discovery_urgency",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_disc_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(discovery_pool[: max(5, desired_count)])
            ]
        elif resolution.focus_engineering_career:
            eng_pool = [
                (
                    "Which technical project shifted your engineering career trajectory the most?",
                    "Connects concrete engineering career inflection points to our goal.",
                    "engineering_career",
                ),
                (
                    "How did your day-to-day system design scope change as you grew into senior "
                    "technical leadership?",
                    "Clarifies engineering role progression and technical scope trade-offs.",
                    "technical_scope",
                ),
                (
                    "What signal helped you decide between deepening IC architecture work versus "
                    "broader platform leadership?",
                    "Explores career ladder decisions aligned with the mentorship objective.",
                    "career_decisions",
                ),
                (
                    "Which production reliability or scaling failure taught you the most durable "
                    "engineering lesson?",
                    "Extracts grounded systems engineering wisdom without generic clichés.",
                    "systems_lessons",
                ),
                (
                    "How do you carve out time for hands-on technical context alongside org-wide "
                    "architecture reviews?",
                    "Addresses sustainable engineering operating habits for career growth.",
                    "operating_cadence",
                ),
                (
                    "What capability do engineers overlook when aiming for staff-plus impact?",
                    "Surfaces actionable coaching guidance linked to career advancement.",
                    "staff_growth",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_eng_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(eng_pool[: max(5, desired_count)])
            ]
        elif resolution.avoid_prior_questions:
            fresh_pool = [
                (
                    f"In revision {rev_num}, what unexpected constraint reshaped how you view "
                    f"{current_brief.meeting_objective[:90]}?",
                    "Explores an unasked constraint angle tied to the meeting objective.",
                    "constraints",
                ),
                (
                    "Looking back at a recent launch, which early assumption turned out false?",
                    "Uncovers candid retrospective lessons not covered in earlier questions.",
                    "retrospective",
                ),
                (
                    "How do you align cross-functional partners when technical timelines tighten?",
                    "Examines stakeholder alignment mechanics relevant to our goal.",
                    "alignment",
                ),
                (
                    "What metric would make six months from now look like a clear success?",
                    "Anchors concrete outcome criteria for future follow-up sessions.",
                    "outcomes",
                ),
                (
                    "Which emerging tool or workflow change has genuinely saved your team time?",
                    "Surfaces practical operational leverage without repeating prior prompts.",
                    "leverage",
                ),
                (
                    "Who else in your ecosystem approaches this domain from a contrasting angle?",
                    "Opens fresh relationship threads and perspective diversity.",
                    "ecosystem",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_fresh_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(fresh_pool[: max(5, desired_count)])
            ]
        else:
            updated_questions = list(current_brief.suggested_questions)
            updated_questions[0] = ConversationQuestion(
                id=updated_questions[0].id,
                question=(
                    f"With '{cleaned_instruction[:120]}' in mind, what practical decision stands "
                    f"out regarding {current_brief.meeting_objective[:110]}?"
                )[:400],
                rationale=(
                    f"Updated during revision v{rev_num} to advance the meeting objective "
                    "under caller guidance."
                ),
                category=updated_questions[0].category,
            )

        return GeneratedBriefContent(
            contact_context=_compose_contact_context(context),
            meeting_objective=current_brief.meeting_objective,
            conversation_openers=updated_openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=target_duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=updated_questions,
            suggested_follow_up_topics=list(current_brief.suggested_follow_up_topics),
            referenced_memory_ids=context.referenced_memory_ids,
            revision_summary=f"Revised brief ({tone_label}): {cleaned_instruction}"[:1000],
        )


class FakeMemoryProposalAgent:
    """Async deterministic fake ``MemoryProposalAgentPort`` extracting PII-scrubbed candidates."""

    _PREFERENCE_CUES = (
        "i prefer",
        "actually, i now prefer",
        "i now prefer",
        "i like",
        "my preference",
        "my style",
        "always include",
        "keep agendas",
        "prefer concise",
        "prefer having",
        "prefer structured",
        "prefer informal",
    )
    _FOLLOW_UP_CUES = (
        "follow up",
        "follow-up",
        "next time",
        "send over",
        "reconnect",
        "share the",
        "recommended learning",
        "recommended exploring",
    )

    async def propose_memories(
        self,
        *,
        notes: str,
        meeting: Meeting | None,
        contact: Contact | None,
        existing_memories: Sequence[Memory],
    ) -> list[ProposedMemoryCandidate]:
        del meeting
        scrubbed = scrub_basic_pii(notes)
        raw_segments = [
            segment.strip()
            for segment in re.split(r"[\n.;]+", scrubbed)
            if len(segment.strip()) >= 5
            and detect_sensitive_or_third_party_assumption(segment) is None
        ]
        if not raw_segments:
            return []

        contact_name = contact.name if contact is not None else None
        proposals: list[ProposedMemoryCandidate] = []

        for segment in raw_segments[:5]:
            raw_excerpt = segment[:500]
            lowered = segment.lower()
            is_user_pref = contact is None or any(cue in lowered for cue in self._PREFERENCE_CUES)

            if is_user_pref:
                scope = MemoryScope.USER_PREFERENCE
                target_cid = None
                mem_type = MemoryType.COMMUNICATION_PREFERENCE
                rationale = (
                    "Captures a caller-stated coaching or communication preference "
                    "for future briefs."
                )
            elif any(cue in lowered for cue in self._FOLLOW_UP_CUES):
                assert contact is not None
                scope = MemoryScope.CONTACT
                target_cid = contact.id
                mem_type = MemoryType.FOLLOW_UP_COMMITMENT
                rationale = (
                    f"Tracks a session-attributed recommendation or follow-up thread with "
                    f"{contact.name}."
                )
            else:
                assert contact is not None
                scope = MemoryScope.CONTACT
                target_cid = contact.id
                mem_type = MemoryType.COUNTERPART_BACKGROUND
                rationale = (
                    f"Preserves session-attributed counterpart context noted about {contact.name}."
                )

            attributed_text = ensure_attributed_epistemic_text(
                segment[:1000],
                scope=scope,
                contact_name=contact_name,
            )
            relation = classify_candidate_against_existing(
                scope=scope,
                contact_id=target_cid,
                memory_type=mem_type,
                text=attributed_text,
                existing_memories=existing_memories,
                contact_name=contact_name,
            )
            if relation.kind is MemoryRelationKind.DUPLICATE:
                continue

            supersedes_id = (
                relation.matched_memory.id
                if relation.kind is MemoryRelationKind.SUPERSEDES
                and relation.matched_memory is not None
                else None
            )
            proposals.append(
                ProposedMemoryCandidate(
                    scope=scope,
                    contact_id=target_cid,
                    memory_type=mem_type,
                    text=attributed_text,
                    rationale=rationale,
                    excerpt=raw_excerpt,
                    supersedes_memory_id=supersedes_id,
                )
            )

        return proposals


class ServiceContainer:
    """Protocol-typed dependency container supporting both local fakes and Firestore backends."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        authenticator: AuthenticatorPort,
        preferences_repo: UserPreferencesRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        proposal_repo: MemoryProposalRepository,
        memory_repo: MemoryRepository,
        brief_agent: BriefCoachAgentPort,
        proposal_agent: MemoryProposalAgentPort,
        idempotency_repo: WorkflowIdempotencyRepository | None = None,
    ) -> None:
        self.clock = clock
        self.id_generator = id_generator
        self.authenticator = authenticator
        self.preferences_repo = preferences_repo
        self.contact_repo = contact_repo
        self.meeting_repo = meeting_repo
        self.brief_repo = brief_repo
        self.proposal_repo = proposal_repo
        self.memory_repo = memory_repo
        self.brief_agent = brief_agent
        self.proposal_agent = proposal_agent
        self.idempotency_repo: WorkflowIdempotencyRepository = (
            idempotency_repo
            if idempotency_repo is not None
            else InMemoryWorkflowIdempotencyRepository()
        )


class FakeServiceContainer(ServiceContainer):
    """Self-contained wiring container holding injected local fake repositories and agents."""

    def __init__(
        self,
        *,
        clock: ClockPort | None = None,
        authenticator: AuthenticatorPort | None = None,
        brief_agent: BriefCoachAgentPort | None = None,
    ) -> None:
        super().__init__(
            clock=clock if clock is not None else SystemUtcClock(),
            id_generator=UuidIdGenerator(),
            authenticator=(authenticator if authenticator is not None else FakeAuthenticator()),
            preferences_repo=InMemoryUserPreferencesRepository(),
            contact_repo=InMemoryContactRepository(),
            meeting_repo=InMemoryMeetingRepository(),
            brief_repo=InMemoryBriefRepository(),
            proposal_repo=InMemoryMemoryProposalRepository(),
            memory_repo=InMemoryMemoryRepository(),
            brief_agent=brief_agent if brief_agent is not None else FakeBriefCoachAgent(),
            proposal_agent=FakeMemoryProposalAgent(),
            idempotency_repo=InMemoryWorkflowIdempotencyRepository(),
        )
