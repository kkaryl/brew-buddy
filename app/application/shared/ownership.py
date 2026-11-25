"""Owner-scoped lookups that fail closed, shared by every use case that takes a record id."""

from __future__ import annotations

from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactReaderPort
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingReaderPort
from app.domain.shared.errors import AuthorizationError, EntityNotFoundError


async def require_owned_contact(
    reader: ContactReaderPort,
    owner_user_id: str,
    contact_id: str,
) -> Contact:
    """Return the caller's contact.

    Raises ``AuthorizationError`` when the id belongs to another user and
    ``EntityNotFoundError`` when it does not exist. The owner of the returned record is
    checked again, so an adapter that ignores its owner filter cannot leak a record.
    """
    contact = await reader.get_for_owner(owner_user_id, contact_id)
    if contact is None:
        if await reader.exists_for_any_owner(contact_id):
            raise AuthorizationError()
        raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
    if contact.owner_user_id != owner_user_id:
        raise AuthorizationError()
    return contact


async def require_owned_meeting(
    reader: MeetingReaderPort,
    owner_user_id: str,
    meeting_id: str,
) -> Meeting:
    """Return the caller's meeting, with the same guarantees as ``require_owned_contact``."""
    meeting = await reader.get_for_owner(owner_user_id, meeting_id)
    if meeting is None:
        if await reader.exists_for_any_owner(meeting_id):
            raise AuthorizationError()
        raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting_id)
    if meeting.owner_user_id != owner_user_id:
        raise AuthorizationError()
    return meeting
