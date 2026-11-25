"""Firestore adapter for contacts at users/{uid}/contacts/{contactId}."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore

from app.domain.contacts.models import Contact
from app.infrastructure.firestore.collections import CONTACTS_SUBCOLLECTION, USERS_COLLECTION
from app.infrastructure.firestore.operations import (
    exists_in_collection_group,
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(CONTACTS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, contact_id: str) -> firestore.AsyncDocumentReference:
        cid = validate_doc_segment("contact_id", contact_id)
        return self._collection_ref(owner_user_id).document(cid)

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.contacts.get",
            self._doc_ref(uid, contact_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return Contact.model_validate(data)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        return await exists_in_collection_group(
            client=self._client,
            subcollection=CONTACTS_SUBCOLLECTION,
            entity_id=contact_id,
            timeout_seconds=self._timeout_seconds,
        )

    async def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        docs = await run_firestore_op(
            "firestore.contacts.list",
            self._collection_ref(uid).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        contacts = [
            Contact.model_validate(data)
            for doc in docs
            if (data := doc.to_dict()) and data.get("owner_user_id") == uid
        ]
        return sorted(contacts, key=lambda item: (item.created_at, item.id))

    async def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        doc_ref = self._doc_ref(contact.owner_user_id, contact.id)
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(contact),
            entity_name="Contact",
            entity_id=contact.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.contacts.save",
        )
        return contact
