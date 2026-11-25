"""Firestore adapter for approved memories and their deletion tombstones."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from opentelemetry import trace

from app.application.shared.telemetry import ATTR_MEMORY_RETRIEVED_COUNT, set_safe_span_attribute
from app.domain.memory.models import Memory
from app.domain.memory.types import ConsentStatus, MemoryLifecycleState, MemoryScope, MemoryType
from app.domain.shared.errors import EntityNotFoundError, VersionConflictError
from app.infrastructure.firestore.collections import (
    DELETED_MEMORIES_SUBCOLLECTION,
    MEMORIES_SUBCOLLECTION,
    USERS_COLLECTION,
)
from app.infrastructure.firestore.operations import (
    exists_in_collection_group,
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEMORIES_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, memory_id: str) -> firestore.AsyncDocumentReference:
        mid = validate_doc_segment("memory_id", memory_id)
        return self._collection_ref(owner_user_id).document(mid)

    def _deleted_doc_ref(
        self,
        owner_user_id: str,
        memory_id: str,
    ) -> firestore.AsyncDocumentReference:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        mid = validate_doc_segment("memory_id", memory_id)
        return cast(
            firestore.AsyncDocumentReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(DELETED_MEMORIES_SUBCOLLECTION)
            .document(mid),
        )

    async def get_for_owner(self, owner_user_id: str, memory_id: str) -> Memory | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.memories.get",
            self._doc_ref(uid, memory_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Memory.model_validate(data)

    async def exists_for_any_owner(self, memory_id: str) -> bool:
        return await exists_in_collection_group(
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
        include_superseded: bool = False,
    ) -> list[Memory]:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref

        # Use a single high-selectivity Firestore equality filter on the user's own
        # subcollection, then apply remaining attribute predicates deterministically.
        if contact_id is not None:
            cid = validate_doc_segment("contact_id", contact_id)
            query = coll_ref.where(filter=FieldFilter("contact_id", "==", cid))
        elif scope is not None:
            query = coll_ref.where(filter=FieldFilter("scope", "==", scope.value))

        async def _fetch_and_filter() -> list[Memory]:
            docs = await query.get()
            filtered: list[Memory] = []
            for doc in docs:
                data = doc.to_dict()
                if not data or data.get("owner_user_id") != uid:
                    continue
                memory = Memory.model_validate(data)
                if not include_revoked and memory.consent_status is not ConsentStatus.APPROVED:
                    continue
                if (
                    not include_superseded
                    and memory.lifecycle_state is not MemoryLifecycleState.APPROVED
                ):
                    continue
                if scope is not None and memory.scope is not scope:
                    continue
                if contact_id is not None and memory.contact_id != contact_id:
                    continue
                if memory_type is not None and memory.memory_type is not memory_type:
                    continue
                filtered.append(memory)
            set_safe_span_attribute(
                trace.get_current_span(),
                ATTR_MEMORY_RETRIEVED_COUNT,
                len(filtered),
            )
            return sorted(filtered, key=lambda item: (item.created_at, item.id))

        return await run_firestore_op(
            "firestore.memories.list",
            _fetch_and_filter(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )

    async def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        doc_ref = self._doc_ref(memory.owner_user_id, memory.id)
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(memory),
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
        deleted_snapshot: Memory | None = None,
    ) -> None:
        doc_ref = self._doc_ref(owner_user_id, memory_id)
        deleted_ref = self._deleted_doc_ref(owner_user_id, memory_id)

        @firestore.async_transactional
        async def _delete_txn(transaction: firestore.AsyncTransaction) -> None:
            snap = await doc_ref.get(transaction=transaction)
            if not snap.exists:
                raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
            existing_dict = snap.to_dict() or {}
            if expected_version is not None:
                actual_version = int(existing_dict.get("version", 0))
                if actual_version != expected_version:
                    raise VersionConflictError(
                        entity_name="Memory",
                        entity_id=memory_id,
                        expected_version=expected_version,
                        actual_version=actual_version,
                    )
            if deleted_snapshot is not None:
                tombstone = deleted_snapshot
            else:
                parsed = Memory.model_validate(existing_dict)
                tombstone = parsed.mark_deleted(deleted_at=parsed.updated_at)
            transaction.set(deleted_ref, serialize_domain_model(tombstone))
            transaction.delete(doc_ref)

        await run_firestore_op(
            "firestore.memories.delete",
            _delete_txn(self._client.transaction()),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )

    async def get_deleted_for_owner(
        self,
        owner_user_id: str,
        memory_id: str,
    ) -> Memory | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.deleted_memories.get",
            self._deleted_doc_ref(uid, memory_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Memory.model_validate(data)
