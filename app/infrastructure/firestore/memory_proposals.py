"""Firestore adapter for staged memory proposals at users/{uid}/memoryProposals/{proposalId}."""

from __future__ import annotations

from typing import cast

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.domain.memory.models import MemoryProposal
from app.domain.memory.types import ProposalStatus
from app.infrastructure.firestore.collections import (
    MEMORY_PROPOSALS_SUBCOLLECTION,
    USERS_COLLECTION,
)
from app.infrastructure.firestore.operations import (
    exists_in_collection_group,
    run_firestore_op,
    save_versioned_document,
    serialize_domain_model,
    validate_doc_segment,
)


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
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        return cast(
            firestore.AsyncCollectionReference,
            self._client.collection(USERS_COLLECTION)
            .document(uid)
            .collection(MEMORY_PROPOSALS_SUBCOLLECTION),
        )

    def _doc_ref(self, owner_user_id: str, proposal_id: str) -> firestore.AsyncDocumentReference:
        pid = validate_doc_segment("proposal_id", proposal_id)
        return self._collection_ref(owner_user_id).document(pid)

    async def get_for_owner(
        self,
        owner_user_id: str,
        proposal_id: str,
    ) -> MemoryProposal | None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        snap = await run_firestore_op(
            "firestore.memory_proposals.get",
            self._doc_ref(uid, proposal_id).get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data or data.get("owner_user_id") != uid:
            return None
        return MemoryProposal.model_validate(data)

    async def exists_for_any_owner(self, proposal_id: str) -> bool:
        return await exists_in_collection_group(
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
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        coll_ref = self._collection_ref(uid)
        query: firestore.AsyncCollectionReference | firestore.AsyncQuery = coll_ref
        if status is not None:
            query = coll_ref.where(filter=FieldFilter("status", "==", status.value))
        elif contact_id is not None:
            cid = validate_doc_segment("contact_id", contact_id)
            query = coll_ref.where(filter=FieldFilter("contact_id", "==", cid))

        docs = await run_firestore_op(
            "firestore.memory_proposals.list",
            query.get(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
        proposals = [
            proposal
            for doc in docs
            if (data := doc.to_dict())
            and data.get("owner_user_id") == uid
            and (proposal := MemoryProposal.model_validate(data))
            and (contact_id is None or proposal.contact_id == contact_id)
        ]
        return sorted(proposals, key=lambda item: (item.created_at, item.id))

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        doc_ref = self._doc_ref(proposal.owner_user_id, proposal.id)
        await save_versioned_document(
            client=self._client,
            doc_ref=doc_ref,
            payload=serialize_domain_model(proposal),
            entity_name="MemoryProposal",
            entity_id=proposal.id,
            expected_version=expected_version,
            timeout_seconds=self._timeout_seconds,
            span_name="firestore.memory_proposals.save",
        )
        return proposal

    async def delete(self, owner_user_id: str, proposal_id: str) -> None:
        uid = validate_doc_segment("owner_user_id", owner_user_id)
        doc_ref = self._doc_ref(uid, proposal_id)
        await run_firestore_op(
            "firestore.memory_proposals.delete",
            doc_ref.delete(),
            timeout_seconds=self._timeout_seconds,
            client=self._client,
        )
