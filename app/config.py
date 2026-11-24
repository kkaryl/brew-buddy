"""Validated runtime configuration for Brew."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

EnvironmentName = Literal["local", "development", "staging", "production", "test"]
LogLevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
PersistenceBackendName = Literal["in_memory", "firestore"]
SessionBackendName = Literal["auto", "in_memory", "firestore", "vertex_ai"]
BriefCoachBackendName = Literal["auto", "adk", "fake"]
MemoryExtractorBackendName = Literal["auto", "adk", "fake"]
AuthModeName = Literal["auto", "verified", "local_mock"]

_RESERVED_DOMAIN_COLLECTIONS = frozenset(
    {
        "users",
        "preferences",
        "contacts",
        "meetings",
        "briefs",
        "revisions",
        "memories",
        "deletedMemories",
        "memoryProposals",
        "workflowIdempotency",
    }
)


class AppSettings(BaseSettings):
    """Typed, validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default="brew", min_length=1, validation_alias="APP_NAME")
    app_version: str = Field(default="0.1.0", min_length=1, validation_alias="AGENT_VERSION")
    environment: EnvironmentName = Field(default="local", validation_alias="APP_ENV")
    host: str = Field(default="0.0.0.0", min_length=1, validation_alias="HOST")
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="PORT")
    log_level: LogLevelName = Field(default="INFO", validation_alias="LOG_LEVEL")

    gemini_model: str = Field(
        default="gemini-3.8-flash",
        min_length=1,
        validation_alias="GEMINI_MODEL",
    )
    google_genai_use_enterprise: bool = Field(
        default=True,
        validation_alias="GOOGLE_GENAI_USE_ENTERPRISE",
    )
    google_cloud_project: str | None = Field(
        default=None,
        validation_alias="GOOGLE_CLOUD_PROJECT",
    )
    google_cloud_location: str = Field(
        default="global",
        min_length=1,
        validation_alias="GOOGLE_CLOUD_LOCATION",
    )

    allow_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="ALLOW_ORIGINS",
    )
    otel_to_cloud: bool | None = Field(default=None, validation_alias="OTEL_TO_CLOUD")
    cloud_trace_enabled: bool | None = Field(
        default=None,
        validation_alias="BREW_CLOUD_TRACE_ENABLED",
    )
    telemetry_capture_content: bool = Field(
        default=False,
        validation_alias="BREW_TELEMETRY_CAPTURE_CONTENT",
    )
    telemetry_upload_completions: bool = Field(
        default=False,
        validation_alias="BREW_TELEMETRY_UPLOAD_COMPLETIONS",
    )
    enable_adk_web_ui: bool = Field(default=False, validation_alias="ENABLE_ADK_WEB_UI")

    http_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        le=120.0,
        validation_alias="HTTP_TIMEOUT_SECONDS",
    )
    model_workflow_timeout_seconds: float = Field(
        default=60.0,
        gt=0.0,
        le=180.0,
        validation_alias="BREW_MODEL_WORKFLOW_TIMEOUT_SECONDS",
    )
    http_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias="HTTP_RETRY_ATTEMPTS",
    )
    brief_coach_backend: BriefCoachBackendName = Field(
        default="auto",
        validation_alias="BREW_BRIEF_COACH_BACKEND",
    )
    memory_extractor_backend: MemoryExtractorBackendName = Field(
        default="auto",
        validation_alias="BREW_MEMORY_EXTRACTOR_BACKEND",
    )
    workflow_max_model_invocations: int = Field(
        default=6,
        ge=1,
        le=12,
        validation_alias="BREW_WORKFLOW_MAX_MODEL_INVOCATIONS",
    )
    workflow_max_tool_retries: int = Field(
        default=1,
        ge=0,
        le=3,
        validation_alias="BREW_WORKFLOW_MAX_TOOL_RETRIES",
    )

    persistence_backend: PersistenceBackendName = Field(
        default="in_memory",
        validation_alias="BREW_PERSISTENCE_BACKEND",
    )
    firestore_database: str = Field(
        default="(default)",
        min_length=1,
        validation_alias="FIRESTORE_DATABASE",
    )
    firestore_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        le=60.0,
        validation_alias="FIRESTORE_TIMEOUT_SECONDS",
    )
    session_backend: SessionBackendName = Field(
        default="auto",
        validation_alias="BREW_SESSION_BACKEND",
    )
    adk_firestore_root_collection: str = Field(
        default="adk-session",
        min_length=1,
        validation_alias="ADK_FIRESTORE_ROOT_COLLECTION",
    )

    web_dist_dir: Path = Field(
        default=REPO_ROOT / "web" / "dist",
        validation_alias="WEB_DIST_DIR",
    )

    auth_mode: AuthModeName = Field(
        default="auto",
        validation_alias="BREW_AUTH_MODE",
    )
    firebase_project_id: str | None = Field(
        default=None,
        validation_alias="FIREBASE_PROJECT_ID",
    )
    firebase_web_api_key: str | None = Field(
        default=None,
        validation_alias="FIREBASE_WEB_API_KEY",
    )
    firebase_auth_domain: str | None = Field(
        default=None,
        validation_alias="FIREBASE_AUTH_DOMAIN",
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_CLIENT_ID",
    )
    mock_session_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        validation_alias="BREW_MOCK_SESSION_TTL_SECONDS",
    )
    seed_eval_fixtures: bool = Field(
        default=False,
        validation_alias="BREW_SEED_EVAL_FIXTURES",
    )

    @field_validator(
        "firebase_project_id",
        "firebase_web_api_key",
        "firebase_auth_domain",
        "google_oauth_client_id",
        mode="before",
    )
    @classmethod
    def _clean_optional_auth_setting(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()
        if not text:
            return None
        placeholder_prefixes = (
            "your-google-oauth-web-client-id",
            "your-public-firebase-web-api-key",
            "your-gcp-project-id",
            "Google Cloud Console",
        )
        if text.startswith(placeholder_prefixes):
            return None
        return text

    @field_validator("gemini_model")
    @classmethod
    def _strip_and_validate_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "GEMINI_MODEL must not be blank."
            raise ValueError(msg)
        return cleaned

    @field_validator("adk_firestore_root_collection")
    @classmethod
    def _validate_adk_session_collection(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "/" in cleaned:
            msg = "ADK_FIRESTORE_ROOT_COLLECTION must be a single non-empty collection name."
            raise ValueError(msg)
        if cleaned in _RESERVED_DOMAIN_COLLECTIONS:
            msg = (
                f"ADK_FIRESTORE_ROOT_COLLECTION '{cleaned}' conflicts with Brew's "
                "domain collections; keep ADK session storage separate."
            )
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def _prevent_mock_auth_in_deployment(self) -> Self:
        if self.auth_mode == "local_mock" and self.is_deployed_environment:
            msg = (
                "BREW_AUTH_MODE='local_mock' cannot be enabled in staging, production, "
                "or Cloud Run deployments."
            )
            raise ValueError(msg)
        if self.seed_eval_fixtures and self.is_deployed_environment:
            msg = (
                "BREW_SEED_EVAL_FIXTURES cannot be enabled in staging, production, "
                "or Cloud Run deployments."
            )
            raise ValueError(msg)
        return self

    @property
    def is_deployed_environment(self) -> bool:
        """Return True when running in staging, production, or managed Cloud Run."""
        if self.environment in {"staging", "production"}:
            return True
        return bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"))

    @property
    def local_mock_auth_enabled(self) -> bool:
        """Return True only when local isolated mock authentication is safe to permit."""
        return not (self.is_deployed_environment or self.auth_mode == "verified")

    @property
    def resolved_firebase_project_id(self) -> str | None:
        """Resolve Firebase project ID for token verification when configured."""
        explicit = (self.firebase_project_id or "").strip()
        if explicit:
            return explicit
        gcp = (self.google_cloud_project or "").strip()
        if gcp and gcp != "your-gcp-project-id":
            return gcp
        return None

    @property
    def allow_origins(self) -> list[str]:
        """Return non-empty CORS origins parsed from comma-separated configuration."""
        return [origin.strip() for origin in self.allow_origins_raw.split(",") if origin.strip()]

    @property
    def otel_enabled(self) -> bool:
        """Enable Cloud Trace export when explicitly requested or running on Cloud Run."""
        if self.otel_to_cloud is not None:
            return self.otel_to_cloud
        return bool(
            os.environ.get("K_SERVICE")
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY")
        )

    @property
    def cloud_trace_export_enabled(self) -> bool:
        """Return True when Google Cloud Trace span export is enabled."""
        if self.cloud_trace_enabled is not None:
            return self.cloud_trace_enabled
        return self.otel_enabled

    @property
    def resolved_gcp_project_for_telemetry(self) -> str | None:
        """Return configured GCP project ID when set to a non-placeholder value."""
        gcp = (self.google_cloud_project or "").strip()
        if gcp and gcp != "your-gcp-project-id":
            return gcp
        return None


@functools.lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached process settings."""
    return AppSettings()


def clear_settings_cache() -> None:
    """Reset cached settings (primarily for isolated tests)."""
    get_settings.cache_clear()
