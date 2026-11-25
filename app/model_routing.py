"""Per-stage Gemini model routing.

Each agent stage asks for a model by what it does, not by a model id. One table decides
which configured model serves which stage, so changing a route is a settings change and the
decision is visible in one place.

Routes (setting, default):

- Brief synthesis, the first draft that weighs every constraint:
  ``BREW_SYNTHESIS_MODEL``, default ``gemini-4-hydrogen``.
- Brief refinement, one targeted edit: ``BREW_REFINEMENT_MODEL``, default ``GEMINI_MODEL``.
- Memory extraction, short structured output:
  ``BREW_MEMORY_EXTRACTION_MODEL``, default ``GEMINI_MODEL``.
- History summarization (compaction): ``GEMINI_MODEL``.
- Conversation (raw ADK chat and A2A): ``GEMINI_MODEL``, default ``gemini-3.8-flash``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from google.adk.models.google_llm import Gemini
from google.genai import types

from app.config import AppSettings, get_settings


class ModelStage(StrEnum):
    """What a model call is for. Routing is decided per stage."""

    CONVERSATION = "conversation"
    BRIEF_SYNTHESIS = "brief_synthesis"
    BRIEF_REFINEMENT = "brief_refinement"
    MEMORY_EXTRACTION = "memory_extraction"
    HISTORY_SUMMARIZATION = "history_summarization"


def resolve_model_id(settings: AppSettings, stage: ModelStage) -> str:
    """Return the configured model id that serves ``stage``."""
    if stage is ModelStage.BRIEF_SYNTHESIS:
        return settings.synthesis_model
    if stage is ModelStage.BRIEF_REFINEMENT:
        return settings.refinement_model or settings.gemini_model
    if stage is ModelStage.MEMORY_EXTRACTION:
        return settings.memory_extraction_model or settings.gemini_model
    return settings.gemini_model


def build_gemini_model(
    settings: AppSettings | None = None,
    *,
    stage: ModelStage = ModelStage.CONVERSATION,
) -> Gemini:
    """Construct the ``Gemini`` LLM for ``stage``, routed through Google Cloud when enabled."""
    resolved = settings or get_settings()
    client_kwargs: dict[str, Any] = {}
    if resolved.google_genai_use_enterprise:
        client_kwargs["vertexai"] = True
        client_kwargs["location"] = resolved.google_cloud_location
        if resolved.google_cloud_project:
            client_kwargs["project"] = resolved.google_cloud_project

    return Gemini(
        model=resolve_model_id(resolved, stage),
        client_kwargs=client_kwargs or None,
        retry_options=types.HttpRetryOptions(attempts=resolved.http_retry_attempts),
    )
