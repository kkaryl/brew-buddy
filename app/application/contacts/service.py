"""Async application use cases for counterpart contact management."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.shared.validation import translate_pydantic_error
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthorizationError, EntityNotFoundError
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
    ) -> None:
        self._contact_repo = contact_repo
        self._clock = clock
        self._id_generator = id_generator

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
