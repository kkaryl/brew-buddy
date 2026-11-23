"""Async Google Cloud Firestore repositories enforcing per-user document partitioning.

Document paths:
- ``users/{uid}/preferences/default``
- ``users/{uid}/contacts/{contactId}``
- ``users/{uid}/meetings/{meetingId}``
- ``users/{uid}/briefs/{briefId}``
- ``users/{uid}/memories/{memoryId}``
- ``users/{uid}/memoryProposals/{proposalId}``
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from enum import Enum
from typing import Any, cast

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from opentelemetry import trace
from pydantic import BaseModel

from app.domain.errors import (
    BrewDomainError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
    PersistenceOperationError,
    VersionConflictError,
)
from app.domain.models import (
    Contact,
    Meeting,
    Memory,
    MemoryProposal,
    PreparationBrief,
    UserPreferences,
    WorkflowIdempotencyRecord,
)
from app.domain.types import (
    BriefWorkflowOperation,
    ConsentStatus,
    MemoryScope,
    MemoryType,
    ProposalStatus,
)

USERS_COLLECTION = "users"
PREFERENCES_SUBCOLLECTION = "preferences"
DEFAULT_PREFERENCES_DOC_ID = "default"
CONTACTS_SUBCOLLECTION = "contacts"
MEETINGS_SUBCOLLECTION = "meetings"
BRIEFS_SUBCOLLECTION = "briefs"
BRIEF_REVISIONS_SUBCOLLECTION = "revisions"
MEMORIES_SUBCOLLECTION = "memories"
MEMORY_PROPOSALS_SUBCOLLECTION = "memoryProposals"
WORKFLOW_IDEMPOTENCY_SUBCOLLECTION = "workflowIdempotency"

_tracer = trace.get_tracer(__name__)


def _validate_doc_segment(label: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise DomainValidationError(f"{label} cannot be empty.")
    if "/" in cleaned or cleaned in {".", ".."}:
        raise DomainValidationError(f"{label} contains an invalid Firestore path segment.")
    if len(cleaned) >= 4 and cleaned.startswith("__") and cleaned.endswith("__"):
        raise DomainValidationError(f"{label} uses a reserved Firestore identifier pattern.")
    return cleaned


def _to_firestore_value(value: Any) -> Any:
    """Convert Pydantic values to native Firestore primitives while preserving UTC datetimes."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _to_firestore_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_firestore_value(item) for item in value]
    return value


def _serialize_domain_model(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="python")
    return {str(k): _to_firestore_value(v) for k, v in raw.items()}


async def _run_firestore_op[T](
    span_name: str,
    coro: Awaitable[T],
    *,
    timeout_seconds: float,
) -> T:
    """Execute an async Firestore operation with an OTel span and explicit timeout."""
    with _tracer.start_as_current_span(span_name):
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except BrewDomainError:
            raise
        except TimeoutError as exc:
            raise PersistenceOperationError(
                f"Firestore operation '{span_name}' timed out after {timeout_seconds:.1f}s."
            ) from exc
        except GoogleAPICallError as exc:
            raise PersistenceOperationError(f"Firestore operation '{span_name}' failed.") from exc


async def _save_versioned_document(
    *,
    client: firestore.AsyncClient,
    doc_ref: firestore.AsyncDocumentReference,
    payload: dict[str, Any],
    entity_name: str,
    entity_id: str,
    expected_version: int | None,
    timeout_seconds: float,
    span_name: str,
    snapshot_doc_ref: firestore.AsyncDocumentReference | None = None,
) -> None:
    @firestore.async_transactional
    async def _txn(transaction: firestore.AsyncTransaction) -> None:
        snapshot = await doc_ref.get(transaction=transaction)
        if expected_version is None:
            if snapshot.exists:
                raise ConflictError(
                    f"{entity_name} '{entity_id}' already exists.",
                    code="ALREADY_EXISTS",
                )
        else:
            if not snapshot.exists:
                raise EntityNotFoundError(entity_name=entity_name, entity_id=entity_id)
            existing = snapshot.to_dict() or {}
            actual_version = int(existing.get("version", 0))
            if actual_version != expected_version:
                raise VersionConflictError(
                    entity_name=entity_name,
                    entity_id=entity_id,
                    expected_version=expected_version,
                    actual_version=actual_version,
                )
        transaction.set(doc_ref, payload)
        if snapshot_doc_ref is not None:
            transaction.set(snapshot_doc_ref, payload)

    await _run_firestore_op(
        span_name,
        _txn(client.transaction()),
        timeout_seconds=timeout_seconds,
    )


async def _exists_in_collection_group(
    *,
    client: firestore.AsyncClient,
    subcollection: str,
    entity_id: str,
    timeout_seconds: float,
) -> bool:
    safe_id = _validate_doc_segment("entity_id", entity_id)
    query = (
        client.collection_group(subcollection)
        .where(filter=FieldFilter("id", "==", safe_id))
        .select(["id"])
        .limit(1)
    )
    docs = await _run_firestore_op(
        f"firestore.{subcollection}.exists_any_owner",
        query.get(),
        timeout_seconds=timeout_seconds,
    )
    return len(docs) > 0


class FirestoreUserPreferencesRepository:
    """Firestore adapter persisting ``UserPreferences`` at ``users/{uid}/preferences/default``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _doc_ref(self, owner_user_id: str) -> firestore.AsyncDocumentReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncDocumentReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(PREFERENCES_SUBCOLLECTION)
            .document(DEFAULT_PREFERENCES_DOC_ID),
        )

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.preferences.get",
            self._doc_ref(uid).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return UserPreferences.model_validate(data)

    async def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        doc_ref = self._doc_ref(preferences.owner_user_id)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(preferences),
            entity_name="UserPreferences",
            entity_id=preferences.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.preferences.save",
        )
        return preferences


class FirestoreContactRepository:
    """Firestore adapter persisting ``Contact`` at ``users/{uid}/contacts/{contactId}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _collection_ref(self, owner_user_id: str) -> firestore.AsyncCollectionReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(CONTACTS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, contact_id: str) -> firestore.AsyncDocumentReference:
        cid = _validate_doc_segment("contact_id", contact_id)
        return self._collection_ref(owner_user_id).document(cid)

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.contacts.get",
            self._doc_ref(uid, contact_id).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Contact.model_validate(data)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        return await _exists_in_collection_group(
            client=self._client,
            subcollection=CONTACTS_SUBCOLLECTION,
            entity_id=contact_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        docs = await _run_firestore_op(
            "firestore.contacts.list",
            self._collection_ref(uid).get(),
            timeout_seconds=self._timeout_seconds,
        )
        contacts = [
            Contact.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(contacts, key=lambda item: (item.created_at, item.id))

    async def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        doc_ref = self._doc_ref(contact.owner_user_id, contact.id)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(contact),
            entity_name="Contact",
            entity_id=contact.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.contacts.save",
        )
        return contact


class FirestoreMeetingRepository:
    """Firestore adapter persisting ``Meeting`` at ``users/{uid}/meetings/{meetingId}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _collection_ref(self, owner_user_id: str) -> firestore.AsyncCollectionReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEETINGS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, meeting_id: str) -> firestore.AsyncDocumentReference:
        mid = _validate_doc_segment("meeting_id", meeting_id)
        return self._collection_ref(owner_user_id).document(mid)

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.meetings.get",
            self._doc_ref(uid, meeting_id).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Meeting.model_validate(data)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        return await _exists_in_collection_group(
            client=self._client,
            subcollection=MEETINGS_SUBCOLLECTION,
            entity_id=meeting_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref
        if contact_id is not None:
            cid = _validate_doc_segment("contact_id", contact_id)
            query = coll_ref.where(filter=FieldFilter("contact_id", "==", cid))

        docs = await _run_firestore_op(
            "firestore.meetings.list",
            query.get(),
            timeout_seconds=self._timeout_seconds,
        )
        meetings = [
            Meeting.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(meetings, key=lambda item: (item.created_at, item.id))

    async def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        doc_ref = self._doc_ref(meeting.owner_user_id, meeting.id)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(meeting),
            entity_name="Meeting",
            entity_id=meeting.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.meetings.save",
        )
        return meeting


class FirestoreBriefRepository:
    """Firestore adapter persisting ``PreparationBrief`` at ``users/{uid}/briefs/{briefId}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _collection_ref(self, owner_user_id: str) -> firestore.AsyncCollectionReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(BRIEFS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, brief_id: str) -> firestore.AsyncDocumentReference:
        bid = _validate_doc_segment("brief_id", brief_id)
        return self._collection_ref(owner_user_id).document(bid)

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.briefs.get",
            self._doc_ref(uid, brief_id).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return PreparationBrief.model_validate(data)

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        return await _exists_in_collection_group(
            client=self._client,
            subcollection=BRIEFS_SUBCOLLECTION,
            entity_id=brief_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_meeting(
        self,
        owner_user_id: str,
        meeting_id: str,
    ) -> list[PreparationBrief]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        mid = _validate_doc_segment("meeting_id", meeting_id)
        query = self._collection_ref(uid).where(filter=FieldFilter("meeting_id", "==", mid))
        docs = await _run_firestore_op(
            "firestore.briefs.list_by_meeting",
            query.get(),
            timeout_seconds=self._timeout_seconds,
        )
        briefs = [
            PreparationBrief.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(briefs, key=lambda item: (item.version, item.id))

    def _revisions_collection_ref(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> firestore.AsyncCollectionReference:
        return cast(
            firestore.AsyncCollectionReference,
            self._doc_ref(owner_user_id, brief_id).collection(BRIEF_REVISIONS_SUBCOLLECTION),
        )

    def _revision_doc_ref(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> firestore.AsyncDocumentReference:
        return self._revisions_collection_ref(owner_user_id, brief_id).document(f"v{version}")

    async def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        doc_ref = self._doc_ref(brief.owner_user_id, brief.id)
        rev_ref = self._revision_doc_ref(brief.owner_user_id, brief.id, brief.version)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(brief),
            entity_name="PreparationBrief",
            entity_id=brief.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.briefs.save",
            snapshot_doc_ref=rev_ref,
        )
        return brief

    async def list_revisions(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> list[PreparationBrief]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        bid = _validate_doc_segment("brief_id", brief_id)
        docs = await _run_firestore_op(
            "firestore.briefs.list_revisions",
            self._revisions_collection_ref(uid, bid).get(),
            timeout_seconds=self._timeout_seconds,
        )
        revisions = [
            PreparationBrief.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(revisions, key=lambda item: item.version)

    async def get_revision(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> PreparationBrief | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        bid = _validate_doc_segment("brief_id", brief_id)
        snap = await _run_firestore_op(
            "firestore.briefs.get_revision",
            self._revision_doc_ref(uid, bid, version).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return PreparationBrief.model_validate(data)


class FirestoreMemoryProposalRepository:
    """Firestore adapter for ``users/{uid}/memoryProposals/{proposalId}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _collection_ref(self, owner_user_id: str) -> firestore.AsyncCollectionReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEMORY_PROPOSALS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, proposal_id: str) -> firestore.AsyncDocumentReference:
        pid = _validate_doc_segment("proposal_id", proposal_id)
        return self._collection_ref(owner_user_id).document(pid)

    async def get_for_owner(
        self,
        owner_user_id: str,
        proposal_id: str,
    ) -> MemoryProposal | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.memory_proposals.get",
            self._doc_ref(uid, proposal_id).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return MemoryProposal.model_validate(data)

    async def exists_for_any_owner(self, proposal_id: str) -> bool:
        return await _exists_in_collection_group(
            client=self._client,
            subcollection=MEMORY_PROPOSALS_SUBCOLLECTION,
            entity_id=proposal_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
    ) -> list[MemoryProposal]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref
        if status is not None:
            query = coll_ref.where(filter=FieldFilter("status", "==", status.value))

        docs = await _run_firestore_op(
            "firestore.memory_proposals.list",
            query.get(),
            timeout_seconds=self._timeout_seconds,
        )
        proposals = [
            MemoryProposal.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(proposals, key=lambda item: (item.created_at, item.id))

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        doc_ref = self._doc_ref(proposal.owner_user_id, proposal.id)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(proposal),
            entity_name="MemoryProposal",
            entity_id=proposal.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.memory_proposals.save",
        )
        return proposal


class FirestoreMemoryRepository:
    """Firestore adapter for approved ``Memory`` records at ``users/{uid}/memories/{memoryId}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _collection_ref(self, owner_user_id: str) -> firestore.AsyncCollectionReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEMORIES_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, memory_id: str) -> firestore.AsyncDocumentReference:
        mid = _validate_doc_segment("memory_id", memory_id)
        return self._collection_ref(owner_user_id).document(mid)

    async def get_for_owner(self, owner_user_id: str, memory_id: str) -> Memory | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.memories.get",
            self._doc_ref(uid, memory_id).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Memory.model_validate(data)

    async def exists_for_any_owner(self, memory_id: str) -> bool:
        return await _exists_in_collection_group(
            client=self._client,
            subcollection=MEMORIES_SUBCOLLECTION,
            entity_id=memory_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref

        # Use a single high-selectivity Firestore equality filter on the user's own
        # subcollection, then apply remaining attribute predicates deterministically.
        if contact_id is not None:
            cid = _validate_doc_segment("contact_id", contact_id)
            query = coll_ref.where(filter=FieldFilter("contact_id", "==", cid))
        elif scope is not None:
            query = coll_ref.where(filter=FieldFilter("scope", "==", scope.value))

        docs = await _run_firestore_op(
            "firestore.memories.list",
            query.get(),
            timeout_seconds=self._timeout_seconds,
        )

        memories: list[Memory] = []
        for doc in docs:
            data = doc.to_dict()
            if not data or data.get("owner_user_id") != uid:
                continue
            memory = Memory.model_validate(data)
            if not include_revoked and memory.consent_status is not ConsentStatus.APPROVED:
                continue
            if scope is not None and memory.scope is not scope:
                continue
            if contact_id is not None and memory.contact_id != contact_id:
                continue
            if memory_type is not None and memory.memory_type is not memory_type:
                continue
            memories.append(memory)

        return sorted(memories, key=lambda item: (item.created_at, item.id))

    async def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        doc_ref = self._doc_ref(memory.owner_user_id, memory.id)
        await _save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=_serialize_domain_model(memory),
            entity_name="Memory",
            entity_id=memory.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.memories.save",
        )
        return memory

    async def delete(
        self,
        owner_user_id: str,
        memory_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        doc_ref = self._doc_ref(owner_user_id, memory_id)

        @firestore.async_transactional
        async def _delete_txn(transaction: firestore.AsyncTransaction) -> None:
            snap = await doc_ref.get(transaction=transaction)
            if not snap.exists:
                raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
            if expected_version is not None:
                existing = snap.to_dict() or {}
                actual_version = int(existing.get("version", 0))
                if actual_version != expected_version:
                    raise VersionConflictError(
                        entity_name="Memory",
                        entity_id=memory_id,
                        expected_version=expected_version,
                        actual_version=actual_version,
                    )
            transaction.delete(doc_ref)

        await _run_firestore_op(
            "firestore.memories.delete",
            _delete_txn(self._client.transaction()),
            timeout_seconds=self._timeout_seconds,
        )


class FirestoreWorkflowIdempotencyRepository:
    """Firestore adapter for ``users/{uid}/workflowIdempotency/{operation}:{key}``."""

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _doc_ref(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> firestore.AsyncDocumentReference:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        safe_key = _validate_doc_segment("idempotency_key", idempotency_key)
        doc_id = f"{operation.value}:{safe_key}"
        return cast(
            firestore.AsyncDocumentReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(WORKFLOW_IDEMPOTENCY_SUBCOLLECTION)
            .document(doc_id),
        )

    async def get(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> WorkflowIdempotencyRecord | None:
        uid = _validate_doc_segment("owner_user_id", owner_user_id)
        snap = await _run_firestore_op(
            "firestore.workflow_idempotency.get",
            self._doc_ref(uid, operation, idempotency_key).get(),
            timeout_seconds=self._timeout_seconds,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return WorkflowIdempotencyRecord.model_validate(data)

    async def save(
        self,
        record: WorkflowIdempotencyRecord,
    ) -> WorkflowIdempotencyRecord:
        doc_ref = self._doc_ref(record.owner_user_id, record.operation, record.idempotency_key)
        await _run_firestore_op(
            "firestore.workflow_idempotency.save",
            doc_ref.set(_serialize_domain_model(record)),
            timeout_seconds=self._timeout_seconds,
        )
        return record
