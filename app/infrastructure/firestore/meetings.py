"""Firestore adapter for meetings at users/{uid}/meetings/{meetingId}."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.domain.meetings.models import Meeting
from app.infrastructure.firestore.collections import MEETINGS_SUBCOLLECTION, USERS_COLLECTION
from app.infrastructure.firestore.operations import (
    exists_in_collection_group,
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEETINGS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, meeting_id: str) -> firestore.AsyncDocumentReference:
        mid = validate_doc_segment("meeting_id", meeting_id)
        return self._collection_ref(owner_user_id).document(mid)

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.meetings.get",
            self._doc_ref(uid, meeting_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Meeting.model_validate(data)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        return await exists_in_collection_group(
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref
        if contact_id is not None:
            cid = validate_doc_segment("contact_id", contact_id)
            query = coll_ref.where(filter=FieldFilter("contact_id", "==", cid))

        docs = await run_firestore_op(
            "firestore.meetings.list",
            query.get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        meetings = [
            Meeting.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(meetings, key=lambda item: (item.created_at, item.id))

    async def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        doc_ref = self._doc_ref(meeting.owner_user_id, meeting.id)
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(meeting),
            entity_name="Meeting",
            entity_id=meeting.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.meetings.save",
        )
        return meeting

    async def delete(self, owner_user_id: str, meeting_id: str) -> None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        doc_ref = self._doc_ref(uid, meeting_id)
        await run_firestore_op(
            "firestore.meetings.delete",
            doc_ref.delete(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
