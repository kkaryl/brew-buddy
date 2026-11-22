"""Validated runtime configuration for Brew."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

EnvironmentName = Literal["local", "development", "staging", "production", "test"]
LogLevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppSettings(BaseSettings):
    """Typed, validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    enable_adk_web_ui: bool = Field(default=False, validation_alias="ENABLE_ADK_WEB_UI")

    http_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        le=120.0,
        validation_alias="HTTP_TIMEOUT_SECONDS",
    )
    http_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias="HTTP_RETRY_ATTEMPTS",
    )

    web_dist_dir: Path = Field(
        default=REPO_ROOT / "web" / "dist",
        validation_alias="WEB_DIST_DIR",
    )

    @field_validator("gemini_model")
    @classmethod
    def _strip_and_validate_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "GEMINI_MODEL must not be blank."
            raise ValueError(msg)
        return cleaned

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


@functools.lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached process settings."""
    return AppSettings()


def clear_settings_cache() -> None:
    """Reset cached settings (primarily for isolated tests)."""
    get_settings.cache_clear()
