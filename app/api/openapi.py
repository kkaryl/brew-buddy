"""OpenAPI 3.1 contract generator for the Brew HTTP API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.config import REPO_ROOT, AppSettings

DEFAULT_OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.json"


def build_openapi_contract(settings: AppSettings | None = None) -> dict[str, Any]:
    """Generate the canonical OpenAPI 3.1 contract for Brew's public HTTP API."""
    resolved = settings or AppSettings(environment="local", otel_to_cloud=False)
    contract_app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description=(
            "Brew — AI-powered Coffee Chat Buddy API contract covering preparation briefs, "
            "contacts, meetings, and human-in-the-loop memory governance."
        ),
    )
    contract_app.include_router(health_router)
    contract_app.include_router(v1_router)

    schema = get_openapi(
        title=contract_app.title,
        version=contract_app.version,
        description=contract_app.description,
        routes=contract_app.routes,
    )
    return schema


def export_openapi_contract(output_path: Path = DEFAULT_OPENAPI_PATH) -> Path:
    """Write the formatted OpenAPI JSON contract to ``output_path``."""
    schema = build_openapi_contract()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    export_openapi_contract()
