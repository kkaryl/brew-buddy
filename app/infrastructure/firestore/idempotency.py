"""Firestore adapter for workflow idempotency records."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore

from app.domain.briefs.models import WorkflowIdempotencyRecord
from app.domain.briefs.types import BriefWorkflowOperation
from app.infrastructure.firestore.collections import (
    USERS_COLLECTION,
    WORKFLOW_IDEMPOTENCY_SUBCOLLECTION,
)
from app.infrastructure.firestore.operations import (
    run_firestore_op,
    serialize_domain_model,
    validate_doc_segment,
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        safe_key = validate_doc_segment("idempotency_key", idempotency_key)
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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.workflow_idempotency.get",
            self._doc_ref(uid, operation, idempotency_key).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
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
        await run_firestore_op(
            "firestore.workflow_idempotency.save",
            doc_ref.set(serialize_domain_model(record)),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        return record
