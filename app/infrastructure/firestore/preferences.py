"""Firestore adapter for user preferences at users/{uid}/preferences/default."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore

from app.domain.memory.models import UserPreferences
from app.infrastructure.firestore.collections import (
    DEFAULT_PREFERENCES_DOC_ID,
    PREFERENCES_SUBCOLLECTION,
    USERS_COLLECTION,
)
from app.infrastructure.firestore.operations import (
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncDocumentReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(PREFERENCES_SUBCOLLECTION)
            .document(DEFAULT_PREFERENCES_DOC_ID),
        )

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.preferences.get",
            self._doc_ref(uid).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
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
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(preferences),
            entity_name="UserPreferences",
            entity_id=preferences.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.preferences.save",
        )
        return preferences
