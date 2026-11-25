"""Shared Firestore plumbing: path checks, serialization, traced operations, versioned saves."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable
from datetime import datetime
from enum import Enum
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.auth.credentials import AnonymousCredentials, Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel

from app.application.shared.telemetry import ATTR_MEMORY_SAVED_COUNT, brew_span
from app.domain.shared.errors import (
    BrewDomainError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
    PersistenceOperationError,
    VersionConflictError,
)


def validate_doc_segment(label: str, value: str) -> str:
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


def serialize_domain_model(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="python")
    return {str(k): _to_firestore_value(v) for k, v in raw.items()}


def _close_unawaited(coro: Awaitable[Any]) -> None:
    if inspect.iscoroutine(coro):
        coro.close()


def _format_firestore_auth_error(exc: GoogleAuthError) -> str:
    detail = str(exc).lower()
    if "reauthentication" in detail or "application-default login" in detail:
        return (
            "Cloud Firestore credentials require reauthentication. "
            "Run 'gcloud auth application-default login' in your terminal and refresh, "
            "or set BREW_PERSISTENCE_BACKEND=in_memory in .env for offline local mode."
        )
    return (
        "Cloud Firestore credentials are unavailable or invalid. "
        "Run 'gcloud auth application-default login' or set "
        "BREW_PERSISTENCE_BACKEND=in_memory in .env for offline local mode."
    )


async def _ensure_client_credentials_valid(
    client: firestore.AsyncClient | None,
    *,
    timeout_seconds: float,
) -> None:
    if client is None or os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return
    creds = getattr(client, "_credentials", None)
    if not isinstance(creds, Credentials) or isinstance(creds, AnonymousCredentials) or creds.valid:
        return
    await asyncio.wait_for(
        asyncio.to_thread(creds.refresh, GoogleAuthRequest()),
        timeout=min(timeout_seconds, 4.0),
    )


def _infer_collection_from_span_name(span_name: str) -> str:
    parts = span_name.split(".")
    return parts[1] if len(parts) >= 2 else "unknown"


async def run_firestore_op[T](
    span_name: str,
    coro: Awaitable[T],
    *,
    timeout_seconds: float,
    client: firestore.AsyncClient | None = None,
    extra_attributes: dict[str, object] | None = None,
) -> T:
    """Execute an async Firestore operation with a correlated OTel span and explicit timeout."""
    collection = _infer_collection_from_span_name(span_name)
    attrs: dict[str, object] = {
        "db.system": "firestore",
        "brew.persistence.collection": collection,
    }
    if extra_attributes:
        attrs.update(extra_attributes)

    with brew_span(
        span_name,
        operation_name=span_name,
        tracer_name=__name__,
        is_persistence=True,
        attributes=attrs,
    ) as tracker:
        try:
            await _ensure_client_credentials_valid(client, timeout_seconds=timeout_seconds)
        except GoogleAuthError as exc:
            _close_unawaited(coro)
            tracker.mark_error(
                "PERSISTENCE_AUTH_ERROR",
                error_code="PERSISTENCE_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            raise PersistenceOperationError(_format_firestore_auth_error(exc)) from exc
        except TimeoutError as exc:
            _close_unawaited(coro)
            tracker.mark_error(
                "PERSISTENCE_TIMEOUT",
                error_code="PERSISTENCE_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            raise PersistenceOperationError(
                f"Firestore credential refresh for '{span_name}' timed out."
            ) from exc

        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except BrewDomainError:
            raise
        except GoogleAuthError as exc:
            tracker.mark_error(
                "PERSISTENCE_AUTH_ERROR",
                error_code="PERSISTENCE_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            raise PersistenceOperationError(_format_firestore_auth_error(exc)) from exc
        except TimeoutError as exc:
            tracker.mark_error(
                "PERSISTENCE_TIMEOUT",
                error_code="PERSISTENCE_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            raise PersistenceOperationError(
                f"Firestore operation '{span_name}' timed out after {timeout_seconds:.1f}s."
            ) from exc
        except GoogleAPICallError as exc:
            tracker.mark_error(
                "PERSISTENCE_UNAVAILABLE",
                error_code="PERSISTENCE_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            raise PersistenceOperationError(f"Firestore operation '{span_name}' failed.") from exc


async def save_versioned_document(
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

    await run_firestore_op(
        span_name,
        _txn(client.transaction()),
        timeout_seconds=timeout_seconds,
        client=client,
        extra_attributes=(
            {ATTR_MEMORY_SAVED_COUNT: 1}
            if span_name in {"firestore.memories.save", "firestore.memory_proposals.save"}
            else None
        ),
    )


async def exists_in_collection_group(
    *,
    client: firestore.AsyncClient,
    subcollection: str,
    entity_id: str,
    timeout_seconds: float,
) -> bool:
    safe_id = validate_doc_segment("entity_id", entity_id)
    query = (
        client.collection_group(subcollection)
        .where(filter=FieldFilter("id", "==", safe_id))
        .select(["id"])
        .limit(1)
    )
    docs = await run_firestore_op(
        f"firestore.{subcollection}.exists_any_owner",
        query.get(),
        timeout_seconds=timeout_seconds,
        client=client,
    )
    return len(docs) > 0
