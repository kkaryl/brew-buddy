"""Authorization for the ADK and A2A surfaces: HTTP route checks and the WebSocket gate."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, unquote

from fastapi import FastAPI, Request, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.dependencies import (
    get_service_container,
    resolve_authenticated_principal_off_event_loop,
)
from app.api.errors import (
    build_domain_error_json_response,
)
from app.api.health import get_app_settings
from app.domain.shared.errors import AuthorizationError, BrewDomainError, DomainValidationError

_ADK_APPS_USER_PATH_RE = re.compile(r"^/apps/[^/]+/users/([^/]+)(?:/|$)")


_ADK_APPS_MEMORY_PATH_RE = re.compile(r"^/apps/[^/]+/users/[^/]+/memory/?$")


_ADK_RUN_INVOCATION_PATHS = frozenset({"/run", "/run_sse"})


async def enforce_adk_and_memory_route_security(request: Request) -> Response | None:
    """Enforce authenticated user identity on ADK/A2A routes and block ungoverned memory writes."""
    path = request.url.path
    method = request.method.upper()

    # 1. Never allow direct ungoverned memory writes through ADK's built-in /memory endpoint.
    #    Durable cross-session memories in Brew strictly require HITL proposal and approval.
    if _ADK_APPS_MEMORY_PATH_RE.match(path) and method in {"PATCH", "POST", "PUT", "DELETE"}:
        try:
            container = get_service_container(request)
            await resolve_authenticated_principal_off_event_loop(request, container)
            raise AuthorizationError(
                "Direct unreviewed memory writes are disabled. Submit candidates via "
                "POST /api/v1/memories/propose and approve via POST /api/v1/memories/{id}/approve.",
                code="UNGOVERNED_MEMORY_WRITE_DISABLED",
            )
        except BrewDomainError as exc:
            return build_domain_error_json_response(request, exc)

    active_settings = get_app_settings(request)
    if active_settings.local_mock_auth_enabled:
        return None

    is_protected_adk_surface = (
        path.startswith("/apps/")
        or path in {"/run", "/run_sse", "/list-apps", "/agent-identity/finalize"}
        or (path.startswith("/a2a/") and method != "GET")
    )
    if not is_protected_adk_surface:
        return None

    try:
        container = get_service_container(request)
        principal = await resolve_authenticated_principal_off_event_loop(request, container)

        user_match = _ADK_APPS_USER_PATH_RE.match(path)
        if user_match:
            target_user_id = unquote(user_match.group(1)).strip()
            if target_user_id != principal.user_id:
                raise AuthorizationError(
                    "Authenticated user cannot access or modify another user's agent sessions.",
                    code="FORBIDDEN",
                )

        if path in _ADK_RUN_INVOCATION_PATHS and method == "POST":
            _require_run_request_targets_principal(await request.body(), principal.user_id)
    except BrewDomainError as exc:
        return build_domain_error_json_response(request, exc)

    return None


def _is_user_identity_key(key: str) -> bool:
    """Return True for every spelling of the ADK caller-identity field.

    ADK request models declare ``user_id`` and also accept its camelCase alias ``userId``
    (``populate_by_name=True``), and the alias wins when both are supplied. Matching on the
    normalized key keeps this check aligned with whichever spelling ADK ends up honoring.
    """
    return key.replace("_", "").replace("-", "").lower() == "userid"


def _require_run_request_targets_principal(raw_body: bytes, principal_user_id: str) -> None:
    """Reject ``/run`` and ``/run_sse`` bodies that do not name exactly the authenticated user.

    Fails closed: a body that is not a JSON object, names no user, or names any user other
    than the verified principal under any accepted spelling never reaches the ADK runner.
    """
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except ValueError:
        parsed_body = None
    if not isinstance(parsed_body, dict):
        raise DomainValidationError(
            "Agent run requests must be a JSON object naming the caller's own user_id."
        )

    # Compared exactly, without trimming: ADK uses the value verbatim as the session owner.
    requested_user_ids = [
        value if isinstance(value, str) else None
        for key, value in parsed_body.items()
        if _is_user_identity_key(key)
    ]
    if not requested_user_ids:
        raise DomainValidationError("Agent run requests must include the caller's own user_id.")
    if any(requested != principal_user_id for requested in requested_user_ids):
        raise AuthorizationError(
            "Authenticated user cannot invoke the agent as another user_id.",
            code="FORBIDDEN",
        )


def _websocket_targets_principal(query_string: bytes, principal_user_id: str) -> bool:
    """Return True only when every ``user_id`` query value equals the authenticated user."""
    requested_user_ids = [
        value
        for key, value in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
        if _is_user_identity_key(key)
    ]
    return bool(requested_user_ids) and all(
        requested == principal_user_id for requested in requested_user_ids
    )


class DeployedWebSocketAuthMiddleware:
    """Bind ADK ``/run_live`` WebSocket upgrades to the authenticated user when deployed."""

    def __init__(self, app: ASGIApp, fastapi_app: FastAPI) -> None:
        self._app = app
        self._fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "websocket" and scope.get("path") == "/run_live":
            query_string: bytes = scope.get("query_string", b"")
            pseudo_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/run_live",
                    "headers": scope.get("headers", []),
                    "query_string": query_string,
                    "app": self._fastapi_app,
                }
            )
            active_settings = get_app_settings(pseudo_request)
            if not active_settings.local_mock_auth_enabled:
                try:
                    container = get_service_container(pseudo_request)
                    principal = await resolve_authenticated_principal_off_event_loop(
                        pseudo_request,
                        container,
                    )
                except BrewDomainError:
                    await send({"type": "websocket.close", "code": 1008})
                    return
                if not _websocket_targets_principal(query_string, principal.user_id):
                    await send({"type": "websocket.close", "code": 1008})
                    return
        await self._app(scope, receive, send)
