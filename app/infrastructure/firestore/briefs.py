"""Firestore adapter for preparation briefs and their immutable revision snapshots."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.domain.briefs.models import PreparationBrief
from app.domain.shared.errors import EntityNotFoundError, VersionConflictError
from app.infrastructure.firestore.collections import (
    BRIEF_REVISIONS_SUBCOLLECTION,
    BRIEFS_SUBCOLLECTION,
    USERS_COLLECTION,
)
from app.infrastructure.firestore.operations import (
    exists_in_collection_group,
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(BRIEFS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, brief_id: str) -> firestore.AsyncDocumentReference:
        bid = validate_doc_segment("brief_id", brief_id)
        return self._collection_ref(owner_user_id).document(bid)

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.briefs.get",
            self._doc_ref(uid, brief_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return PreparationBrief.model_validate(data)

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        return await exists_in_collection_group(
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        mid = validate_doc_segment("meeting_id", meeting_id)
        query = self._collection_ref(uid).where(filter=FieldFilter("meeting_id", "==", mid))
        docs = await run_firestore_op(
            "firestore.briefs.list_by_meeting",
            query.get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        briefs = [
            PreparationBrief.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(briefs, key=lambda item: (item.version, item.id))

    async def list_by_contact(
        self,
        owner_user_id: str,
        contact_id: str,
    ) -> list[PreparationBrief]:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        cid = validate_doc_segment("contact_id", contact_id)
        query = self._collection_ref(uid).where(filter=FieldFilter("contact_id", "==", cid))
        docs = await run_firestore_op(
            "firestore.briefs.list_by_contact",
            query.get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        briefs = [
            PreparationBrief.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(briefs, key=lambda item: (item.created_at, item.id))

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
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(brief),
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        bid = validate_doc_segment("brief_id", brief_id)
        docs = await run_firestore_op(
            "firestore.briefs.list_revisions",
            self._revisions_collection_ref(uid, bid).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        bid = validate_doc_segment("brief_id", brief_id)
        snap = await run_firestore_op(
            "firestore.briefs.get_revision",
            self._revision_doc_ref(uid, bid, version).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return PreparationBrief.model_validate(data)

    async def delete(
        self,
        owner_user_id: str,
        brief_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        bid = validate_doc_segment("brief_id", brief_id)
        doc_ref = self._doc_ref(uid, bid)
        rev_coll_ref = self._revisions_collection_ref(uid, bid)

        @firestore.async_transactional
        async def _delete_txn(transaction: firestore.AsyncTransaction) -> None:
            snap = await doc_ref.get(transaction=transaction)
            if not snap.exists:
                raise EntityNotFoundError(entity_name="PreparationBrief", entity_id=bid)
            existing_dict = snap.to_dict() or {}
            if existing_dict.get("owner_user_id") != uid:
                raise EntityNotFoundError(entity_name="PreparationBrief", entity_id=bid)
            if expected_version is not None:
                actual_version = int(existing_dict.get("version", 0))
                if actual_version != expected_version:
                    raise VersionConflictError(
                        entity_name="PreparationBrief",
                        entity_id=bid,
                        expected_version=expected_version,
                        actual_version=actual_version,
                    )
            transaction.delete(doc_ref)

        await run_firestore_op(
            "firestore.briefs.delete",
            _delete_txn(self._client.transaction()),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )

        async def _purge_revisions() -> None:
            rev_docs = await rev_coll_ref.get()
            if not rev_docs:
                return
            batch = self._client.batch()
            for rev_doc in rev_docs:
                batch.delete(rev_doc.reference)
            await batch.commit()

        await run_firestore_op(
            "firestore.brief_revisions.delete",
            _purge_revisions(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
