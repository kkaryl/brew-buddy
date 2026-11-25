"""Firestore adapter for background memory-extraction job records."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore

from app.domain.memory.jobs import MemoryExtractionJob
from app.infrastructure.firestore.collections import MEMORY_JOBS_SUBCOLLECTION, USERS_COLLECTION
from app.infrastructure.firestore.operations import (
    run_firestore_op,
    serialize_domain_model,
    validate_doc_segment,
)


class FirestoreMemoryExtractionJobRepository:
    """Firestore adapter for ``users/{uid}/memoryJobs/{jobId}``.

    A job record is written by one background task at a time and read by its owner, so plain
    ``set`` and ``get`` are enough. It holds no note text, only status and proposal ids.
    """

    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _doc_ref(self, owner_user_id: str, job_id: str) -> firestore.AsyncDocumentReference:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        jid = validate_doc_segment("job_id", job_id)
        return cast(
            firestore.AsyncDocumentReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEMORY_JOBS_SUBCOLLECTION)
            .document(jid),
        )

    async def get_for_owner(
        self,
        owner_user_id: str,
        job_id: str,
    ) -> MemoryExtractionJob | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.memory_jobs.get",
            self._doc_ref(uid, job_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return MemoryExtractionJob.model_validate(data)

    async def save(self, job: MemoryExtractionJob) -> MemoryExtractionJob:
        await run_firestore_op(
            "firestore.memory_jobs.save",
            self._doc_ref(job.owner_user_id, job.id).set(serialize_domain_model(job)),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        return job
