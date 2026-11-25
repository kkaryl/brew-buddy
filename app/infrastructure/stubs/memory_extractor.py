"""Scripted deterministic memory proposal agent standing in for the model."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.application.shared.telemetry import brew_span
from app.domain.contacts.models import Contact
from app.domain.meetings.models import Meeting
from app.domain.memory.attribution import ensure_attributed_epistemic_text
from app.domain.memory.models import Memory
from app.domain.memory.ports import ProposedMemoryCandidate
from app.domain.memory.relations import MemoryRelationKind, classify_candidate_against_existing
from app.domain.memory.sensitivity import detect_sensitive_or_third_party_assumption
from app.domain.memory.types import MemoryScope, MemoryType
from app.infrastructure.stubs.pii import scrub_basic_pii


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
        with brew_span(
            "brew.agent.invoke",
            operation_name="agent.invoke",
            tracer_name=__name__,
            agent_name="memory_candidate_extractor",
            agent_version="1.0.0",
            model_name="fake-deterministic-extractor",
        ):
            return await self._propose_memories_impl(
                notes=notes,
                meeting=meeting,
                contact=contact,
                existing_memories=existing_memories,
            )

    async def _propose_memories_impl(
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
