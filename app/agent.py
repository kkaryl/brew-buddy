"""Root ADK agent definition for Brew (foundation prototype)."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.config import AppSettings, get_settings
from app.tools.system_tools import check_brew_service_health

FOUNDATION_SYSTEM_INSTRUCTION = """You are Brew, an AI-powered Coffee Chat Buddy.
In this foundational build, only system readiness inspection is enabled; meeting preparation
and memory features are not yet active. Be concise, accurate, and never fabricate facts.
Use `check_brew_service_health` when asked about service readiness or runtime configuration.
"""


def build_root_agent(settings: AppSettings | None = None) -> Agent:
    """Construct the configured root ADK agent."""
    resolved = settings or get_settings()
    timeout_ms = int(resolved.http_timeout_seconds * 1000)

    return Agent(
        # Keep in sync with create_params.root_agent_name in agents-cli-manifest.yaml.
        name="brew",
        description="Brew — AI-powered Coffee Chat Buddy foundation agent.",
        model=Gemini(
            model=resolved.gemini_model,
            retry_options=types.HttpRetryOptions(attempts=resolved.http_retry_attempts),
        ),
        generate_content_config=types.GenerateContentConfig(
            http_options=types.HttpOptions(timeout=timeout_ms),
        ),
        instruction=FOUNDATION_SYSTEM_INSTRUCTION,
        tools=[check_brew_service_health],
    )


root_agent: Agent = build_root_agent()

app = App(
    root_agent=root_agent,
    name="app",
)
