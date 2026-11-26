"""Async application use cases for counterpart contact management."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.shared.telemetry import brew_span
from app.application.shared.validation import translate_pydantic_error
from app.domain.briefs.ports import BriefRepository
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingRepository
from app.domain.memory.ports import MemoryProposalRepository, MemoryRepository
from app.domain.memory.types import MemoryScope
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import (
    AuthorizationError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.shared.ports import IdGeneratorPort

logger = logging.getLogger(__name__)


class ContactService:
    """Async application use cases for counterpart contact management."""

    def __init__(
        self,
        *,
        contact_repo: ContactRepository,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        meeting_repo: MeetingRepository | None = None,
        brief_repo: BriefRepository | None = None,
        memory_repo: MemoryRepository | None = None,
        proposal_repo: MemoryProposalRepository | None = None,
    ) -> None:
        self._contact_repo = contact_repo
        self._clock = clock
        self._id_generator = id_generator
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._memory_repo = memory_repo
        self._proposal_repo = proposal_repo

    async def create_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        name: str,
        title: str | None = None,
        role: str | None = None,
        organization: str | None = None,
        context_notes: str | None = None,
    ) -> Contact:
        """Create and persist a new contact owned by ``principal``."""
        now = self._clock.now_utc()
        try:
            contact = Contact(
                id=self._id_generator.new_id("cnt"),
                owner_user_id=principal.user_id,
                name=name,
                title=title,
                role=role,
                organization=organization,
                context_notes=context_notes,
                created_at=now,
                updated_at=now,
                version=1,
            )
        except ValidationError as exc:
            raise translate_pydantic_error(exc) from exc

        saved = await self._contact_repo.save(contact)
        logger.info("Contact created", extra={"event_type": "contact.created"})
        return saved

    async def list_contacts(self, *, principal: AuthenticatedPrincipal) -> list[Contact]:
        """List contacts belonging to ``principal``."""
        return await self._contact_repo.list_by_owner(principal.user_id)

    async def get_owned_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
    ) -> Contact:
        """Fetch a contact and enforce caller ownership."""
        contact = await self._contact_repo.get_for_owner(principal.user_id, contact_id)
        if contact is None:
            if await self._contact_repo.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return contact

    async def delete_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
        expected_version: int | None = None,
    ) -> None:
        """Delete an owned contact and cascade-delete their briefs, meetings, and memories."""
        uid = principal.user_id
        with brew_span(
            "brew.contact.delete",
            operation_name="contact.delete",
            tracer_name=__name__,
        ) as tracker:
            contact = await self.get_owned_contact(principal=principal, contact_id=contact_id)
            if expected_version is not None and contact.version != expected_version:
                raise VersionConflictError(
                    entity_name="Contact",
                    entity_id=contact_id,
                    expected_version=expected_version,
                    actual_version=contact.version,
                )

            deleted_brief_ids: set[str] = set()
            if self._brief_repo is not None:
                contact_briefs = await self._brief_repo.list_by_contact(uid, contact.id)
                for brief in contact_briefs:
                    if brief.owner_user_id == uid:
                        await self._brief_repo.delete(uid, brief.id)
                        deleted_brief_ids.add(brief.id)

            deleted_meetings = 0
            if self._meeting_repo is not None:
                meetings = await self._meeting_repo.list_by_owner(uid, contact_id=contact.id)
                for mtg in meetings:
                    if mtg.owner_user_id != uid:
                        continue
                    if self._brief_repo is not None:
                        mtg_briefs = await self._brief_repo.list_by_meeting(uid, mtg.id)
                        for brief in mtg_briefs:
                            if brief.owner_user_id == uid and brief.id not in deleted_brief_ids:
                                await self._brief_repo.delete(uid, brief.id)
                                deleted_brief_ids.add(brief.id)
                    await self._meeting_repo.delete(uid, mtg.id)
                    deleted_meetings += 1

            deleted_proposals = 0
            if self._proposal_repo is not None:
                proposals = await self._proposal_repo.list_by_owner(uid, contact_id=contact.id)
                for proposal in proposals:
                    if proposal.owner_user_id == uid:
                        await self._proposal_repo.delete(uid, proposal.id)
                        deleted_proposals += 1

            deleted_memories = 0
            if self._memory_repo is not None:
                now = self._clock.now_utc()
                memories = await self._memory_repo.list_by_owner(
                    uid,
                    scope=MemoryScope.CONTACT,
                    contact_id=contact.id,
                    include_revoked=True,
                    include_superseded=True,
                )
                for memory in memories:
                    if memory.owner_user_id == uid:
                        tombstone = memory.mark_deleted(deleted_at=max(now, memory.created_at))
                        await self._memory_repo.delete(
                            uid,
                            memory.id,
                            deleted_snapshot=tombstone,
                        )
                        deleted_memories += 1

            await self._contact_repo.delete(uid, contact.id, expected_version=expected_version)

            tracker.set_attributes(
                {
                    "brew.contact.deleted_briefs_count": len(deleted_brief_ids),
                    "brew.contact.deleted_meetings_count": deleted_meetings,
                    "brew.contact.deleted_proposals_count": deleted_proposals,
                    "brew.contact.deleted_memories_count": deleted_memories,
                }
            )
            logger.info(
                "Contact and associated briefs, meetings, and memories deleted",
                extra={
                    "event_type": "contact.deleted",
                    "operation_name": "contact.delete",
                    "result_status": tracker.status,
                },
            )
