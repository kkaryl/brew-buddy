"""Async application use cases for inspecting user meetings."""

from __future__ import annotations

from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingRepository
from app.domain.shared.errors import AuthorizationError, EntityNotFoundError


class MeetingService:
    """Async application use cases for inspecting user meetings."""

    def __init__(
        self,
        *,
        meeting_repo: MeetingRepository,
        contact_repo: ContactRepository,
    ) -> None:
        self._meeting_repo = meeting_repo
        self._contact_repo = contact_repo

    async def list_meetings(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings owned by ``principal``, validating optional ``contact_id`` ownership."""
        if contact_id is not None:
            contact = await self._contact_repo.get_for_owner(principal.user_id, contact_id)
            if contact is None:
                if await self._contact_repo.exists_for_any_owner(contact_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return await self._meeting_repo.list_by_owner(
            principal.user_id,
            contact_id=contact_id,
        )
