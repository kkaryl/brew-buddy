"""In-memory fake repositories, authenticator, and deterministic agent adapters for Brew."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Mapping, Sequence

from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.health import ClockPort
from app.domain.models import (
    AuthenticatedPrincipal,
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    PreparationBrief,
    TimeBoxedAgendaItem,
    UserPreferences,
)
from app.domain.ports import GeneratedBriefContent, ProposedMemoryCandidate
from app.domain.types import (
    ConsentStatus,
    MeetingDurationMinutes,
    MeetingPurpose,
    MeetingTone,
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
    """Dedicated in-memory repository for ``UserPreferences``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_owner: dict[str, UserPreferences] = {}

    def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        with self._lock:
            return self._by_owner.get(owner_user_id)

    def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        with self._lock:
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
    """Dedicated in-memory repository for ``Contact`` entities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Contact] = {}

    def get_by_id(self, contact_id: str) -> Contact | None:
        with self._lock:
            return self._by_id.get(contact_id)

    def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        with self._lock:
            items = [
                contact
                for contact in self._by_id.values()
                if contact.owner_user_id == owner_user_id
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        with self._lock:
            existing = self._by_id.get(contact.id)
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
            self._by_id[contact.id] = contact
            return contact


class InMemoryMeetingRepository:
    """Dedicated in-memory repository for ``Meeting`` entities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Meeting] = {}

    def get_by_id(self, meeting_id: str) -> Meeting | None:
        with self._lock:
            return self._by_id.get(meeting_id)

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        with self._lock:
            items = [
                meeting
                for meeting in self._by_id.values()
                if meeting.owner_user_id == owner_user_id
                and (contact_id is None or meeting.contact_id == contact_id)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        with self._lock:
            existing = self._by_id.get(meeting.id)
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
            self._by_id[meeting.id] = meeting
            return meeting


class InMemoryBriefRepository:
    """Dedicated in-memory repository for ``PreparationBrief`` entities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, PreparationBrief] = {}

    def get_by_id(self, brief_id: str) -> PreparationBrief | None:
        with self._lock:
            return self._by_id.get(brief_id)

    def list_by_meeting(self, meeting_id: str) -> list[PreparationBrief]:
        with self._lock:
            items = [brief for brief in self._by_id.values() if brief.meeting_id == meeting_id]
        return sorted(items, key=lambda item: (item.version, item.id))

    def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        with self._lock:
            existing = self._by_id.get(brief.id)
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
            self._by_id[brief.id] = brief
            return brief


class InMemoryMemoryProposalRepository:
    """Isolated in-memory repository storing ``MemoryProposal`` records separately."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, MemoryProposal] = {}

    def get_by_id(self, proposal_id: str) -> MemoryProposal | None:
        with self._lock:
            return self._by_id.get(proposal_id)

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
    ) -> list[MemoryProposal]:
        with self._lock:
            items = [
                proposal
                for proposal in self._by_id.values()
                if proposal.owner_user_id == owner_user_id
                and (status is None or proposal.status is status)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        with self._lock:
            existing = self._by_id.get(proposal.id)
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
            self._by_id[proposal.id] = proposal
            return proposal


class InMemoryMemoryRepository:
    """Isolated in-memory repository storing approved ``Memory`` entities only."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Memory] = {}

    def get_by_id(self, memory_id: str) -> Memory | None:
        with self._lock:
            return self._by_id.get(memory_id)

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        with self._lock:
            items = [
                memory
                for memory in self._by_id.values()
                if memory.owner_user_id == owner_user_id
                and (include_revoked or memory.consent_status is ConsentStatus.APPROVED)
                and (scope is None or memory.scope is scope)
                and (contact_id is None or memory.contact_id == contact_id)
                and (memory_type is None or memory.memory_type is memory_type)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        with self._lock:
            existing = self._by_id.get(memory.id)
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
            self._by_id[memory.id] = memory
            return memory

    def delete(self, memory_id: str, *, expected_version: int | None = None) -> None:
        with self._lock:
            existing = self._by_id.get(memory_id)
            if existing is None:
                raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
            if expected_version is not None and existing.version != expected_version:
                raise VersionConflictError(
                    entity_name="Memory",
                    entity_id=memory_id,
                    expected_version=expected_version,
                    actual_version=existing.version,
                )
            del self._by_id[memory_id]


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


def _compose_contact_context(
    *,
    contact: Contact,
    approved_memories: Sequence[Memory],
) -> str:
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

    contact_memories = [mem.text for mem in approved_memories if mem.scope is MemoryScope.CONTACT]
    if contact_memories:
        joined = "; ".join(contact_memories[:3])
        summary = f"{summary} Prior approved notes: {joined}"

    return summary[:2000]


class FakeBriefCoachAgent:
    """Deterministic fake ``BriefCoachAgentPort`` for contract verification without live LLMs."""

    def generate_brief(
        self,
        *,
        meeting: Meeting,
        contact: Contact,
        user_preferences: UserPreferences | None,
        approved_memories: Sequence[Memory],
    ) -> GeneratedBriefContent:
        question_count = (
            user_preferences.preferred_question_count if user_preferences is not None else 3
        )
        question_count = max(1, min(question_count, 6))

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
                    f"Anchors the {purpose_label} discussion in real-world decisions "
                    "rather than generic advice."
                ),
                "core_objective",
            ),
            (
                (
                    "What signal tells you an initiative in your domain is on the right track, "
                    f"{contact.name}?"
                ),
                "Surfaces concrete evaluation criteria and mental models within the timebox.",
                "perspective",
            ),
            (
                "What common misconception do people bring when approaching this space?",
                "Invites candid nuance and memorable insights.",
                "nuance",
            ),
            (
                "Where do you see the biggest upcoming shift over the next two quarters?",
                "Opens forward-looking context for potential future conversations.",
                "outlook",
            ),
            (
                "Who or what resource shaped how you think about this problem?",
                "Creates natural follow-up threads without overstepping.",
                "resources",
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
            contact_context=_compose_contact_context(
                contact=contact,
                approved_memories=approved_memories,
            ),
            meeting_objective=meeting.objective,
            conversation_openers=openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=meeting.duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=questions,
            suggested_follow_up_topics=follow_ups,
            referenced_memory_ids=[mem.id for mem in approved_memories],
            revision_summary=None,
        )

    def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        contact: Contact,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        user_preferences: UserPreferences | None,
        approved_memories: Sequence[Memory],
    ) -> GeneratedBriefContent:
        del user_preferences
        cleaned_instruction = scrub_basic_pii(instructions.strip())
        tone_label = target_tone.value.replace("_", " ")

        updated_openers = [
            (
                f"[{tone_label}] Hi {contact.name}, excited for our focused "
                f"{target_duration_minutes}-minute chat—{cleaned_instruction[:180]}."
            ),
            *current_brief.conversation_openers[:1],
        ]

        updated_questions = list(current_brief.suggested_questions)
        updated_questions[0] = ConversationQuestion(
            id=updated_questions[0].id,
            question=(
                f"With '{cleaned_instruction[:140]}' in mind, what stands out most "
                f"regarding {current_brief.meeting_objective[:120]}?"
            )[:400],
            rationale=(
                f"Updated during revision v{current_brief.version + 1} to reflect caller guidance."
            ),
            category=updated_questions[0].category,
        )

        return GeneratedBriefContent(
            contact_context=_compose_contact_context(
                contact=contact,
                approved_memories=approved_memories,
            ),
            meeting_objective=current_brief.meeting_objective,
            conversation_openers=updated_openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=target_duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=updated_questions,
            suggested_follow_up_topics=current_brief.suggested_follow_up_topics,
            referenced_memory_ids=[mem.id for mem in approved_memories],
            revision_summary=f"Revised brief ({tone_label}): {cleaned_instruction}"[:1000],
        )


class FakeMemoryProposalAgent:
    """Deterministic fake ``MemoryProposalAgentPort`` extracting PII-scrubbed candidates."""

    _PREFERENCE_CUES = (
        "i prefer",
        "my preference",
        "my style",
        "always include",
        "keep agendas",
        "prefer concise",
    )
    _FOLLOW_UP_CUES = (
        "follow up",
        "follow-up",
        "next time",
        "send over",
        "reconnect",
        "share the",
    )

    def propose_memories(
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
        ]
        if not raw_segments:
            raw_segments = [scrubbed.strip()]

        existing_texts = {mem.text.lower() for mem in existing_memories}
        proposals: list[ProposedMemoryCandidate] = []

        for segment in raw_segments[:5]:
            normalized_text = segment[:1000]
            if normalized_text.lower() in existing_texts:
                continue

            lowered = normalized_text.lower()
            is_user_pref = contact is None or any(cue in lowered for cue in self._PREFERENCE_CUES)

            if is_user_pref:
                proposals.append(
                    ProposedMemoryCandidate(
                        scope=MemoryScope.USER_PREFERENCE,
                        contact_id=None,
                        memory_type=MemoryType.COMMUNICATION_PREFERENCE,
                        text=normalized_text,
                        rationale=(
                            "Captures a durable coaching or communication preference "
                            "for future briefs."
                        ),
                        excerpt=normalized_text[:500],
                    )
                )
            elif any(cue in lowered for cue in self._FOLLOW_UP_CUES):
                assert contact is not None
                proposals.append(
                    ProposedMemoryCandidate(
                        scope=MemoryScope.CONTACT,
                        contact_id=contact.id,
                        memory_type=MemoryType.FOLLOW_UP_COMMITMENT,
                        text=normalized_text,
                        rationale=(
                            f"Tracks a follow-up thread discussed with {contact.name} "
                            "for future sessions."
                        ),
                        excerpt=normalized_text[:500],
                    )
                )
            else:
                assert contact is not None
                proposals.append(
                    ProposedMemoryCandidate(
                        scope=MemoryScope.CONTACT,
                        contact_id=contact.id,
                        memory_type=MemoryType.COUNTERPART_BACKGROUND,
                        text=normalized_text,
                        rationale=(
                            f"Preserves user-noted counterpart context about {contact.name}."
                        ),
                        excerpt=normalized_text[:500],
                    )
                )

        if not proposals:
            fallback_text = raw_segments[0][:1000]
            if contact is not None:
                proposals.append(
                    ProposedMemoryCandidate(
                        scope=MemoryScope.CONTACT,
                        contact_id=contact.id,
                        memory_type=MemoryType.RELATIONSHIP_NOTE,
                        text=fallback_text,
                        rationale=f"Candidate relationship context noted for {contact.name}.",
                        excerpt=fallback_text[:500],
                    )
                )
            else:
                proposals.append(
                    ProposedMemoryCandidate(
                        scope=MemoryScope.USER_PREFERENCE,
                        contact_id=None,
                        memory_type=MemoryType.COMMUNICATION_PREFERENCE,
                        text=fallback_text,
                        rationale="Candidate coaching preference noted by user.",
                        excerpt=fallback_text[:500],
                    )
                )

        return proposals


class FakeServiceContainer:
    """Self-contained wiring container holding injected in-memory repositories and fake agents."""

    def __init__(
        self,
        *,
        clock: ClockPort | None = None,
        authenticator: FakeAuthenticator | None = None,
    ) -> None:
        self.clock: ClockPort = clock if clock is not None else SystemUtcClock()
        self.id_generator = UuidIdGenerator()
        self.authenticator = authenticator if authenticator is not None else FakeAuthenticator()
        self.preferences_repo = InMemoryUserPreferencesRepository()
        self.contact_repo = InMemoryContactRepository()
        self.meeting_repo = InMemoryMeetingRepository()
        self.brief_repo = InMemoryBriefRepository()
        self.proposal_repo = InMemoryMemoryProposalRepository()
        self.memory_repo = InMemoryMemoryRepository()
        self.brief_agent = FakeBriefCoachAgent()
        self.proposal_agent = FakeMemoryProposalAgent()
