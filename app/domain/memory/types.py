"""Memory enumerations and text types used only by the memory context."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

RawSessionNotesText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=10000),
]


class MemoryScope(StrEnum):
    """Target scope of a memory or memory proposal."""

    USER_PREFERENCE = "user_preference"
    CONTACT = "contact"


class MemoryType(StrEnum):
    """Semantic classification of a proposed or approved memory."""

    COMMUNICATION_PREFERENCE = "communication_preference"
    AGENDA_PREFERENCE = "agenda_preference"
    COUNTERPART_BACKGROUND = "counterpart_background"
    SHARED_INTEREST = "shared_interest"
    FOLLOW_UP_COMMITMENT = "follow_up_commitment"
    RELATIONSHIP_NOTE = "relationship_note"


class ConsentStatus(StrEnum):
    """User consent status for durable memories."""

    APPROVED = "approved"
    REVOKED = "revoked"


class ProposalStatus(StrEnum):
    """Human-in-the-loop review status of a memory proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemoryExtractionJobStatus(StrEnum):
    """Lifecycle of a background memory-extraction job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` once the job can no longer change."""
        return self in {MemoryExtractionJobStatus.SUCCEEDED, MemoryExtractionJobStatus.FAILED}


class MemoryLifecycleState(StrEnum):
    """Canonical lifecycle state across staged proposals and durable memories."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryEpistemicStatus(StrEnum):
    """Epistemic status ensuring memories are framed as attributed context, not world facts."""

    USER_REPORTED_OBSERVATION = "user_reported_observation"
    USER_STATED_PREFERENCE = "user_stated_preference"


class MemorySourceType(StrEnum):
    """Originating workflow context for a memory or memory proposal."""

    MEETING_NOTES = "meeting_notes"
    BRIEF_REFINEMENT = "brief_refinement"
    DIRECT_USER_INPUT = "direct_user_input"
