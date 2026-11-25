"""Builders for Brew's ``conversation_coach`` agent and the ADK ``App`` around it."""

from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.base_llm import BaseLlm
from google.genai import types

from app.agents.model_routing import ModelStage, build_gemini_model
from app.agents.plugins.coach_guardrails import ConversationCoachGuardrailPlugin
from app.agents.prompts import CONVERSATION_COACH_INSTRUCTION
from app.agents.tools.dependencies import CoachingToolDependencies
from app.agents.tools.registry import build_coaching_tools
from app.config import AppSettings, get_settings

CONVERSATION_COACH_NAME = "conversation_coach"
CONVERSATION_COACH_VERSION = "1.0.0"


def build_conversation_coach_agent(
    settings: AppSettings | None = None,
    *,
    tool_dependencies: CoachingToolDependencies | None = None,
    model_override: BaseLlm | None = None,
) -> Agent:
    """Construct Brew's ``conversation_coach`` ADK agent."""
    resolved = settings or get_settings()
    timeout_ms = int(resolved.http_timeout_seconds * 1000)

    return Agent(
        # Keep in sync with create_params.root_agent_name in agents-cli-manifest.yaml.
        name=CONVERSATION_COACH_NAME,
        description=(
            "Brew Conversation Coach — prepares, tailors, and refines meeting briefs "
            "and open-ended questions grounded in user-approved context."
        ),
        model=model_override if model_override is not None else build_gemini_model(resolved),
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3,
            http_options=types.HttpOptions(timeout=timeout_ms),
        ),
        instruction=CONVERSATION_COACH_INSTRUCTION,
        tools=build_coaching_tools(tool_dependencies),
    )


# Backward-compatible factory alias for callers importing ``build_root_agent``.
build_root_agent = build_conversation_coach_agent


def build_adk_app(
    settings: AppSettings | None = None,
    *,
    tool_dependencies: CoachingToolDependencies | None = None,
    root_agent_override: Agent | None = None,
) -> App:
    """Construct the ADK ``App`` with runner-wide guardrails and history compaction."""
    resolved = settings or get_settings()
    coach_agent = (
        root_agent_override
        if root_agent_override is not None
        else build_conversation_coach_agent(
            resolved,
            tool_dependencies=tool_dependencies,
        )
    )
    return App(
        # Must remain "app" to match the `app/` package directory for ADK & agents-cli eval.
        name="app",
        root_agent=coach_agent,
        plugins=[
            ConversationCoachGuardrailPlugin(
                agent_version=CONVERSATION_COACH_VERSION,
                model_name=resolved.gemini_model,
            )
        ],
        events_compaction_config=EventsCompactionConfig(
            token_threshold=24000,
            event_retention_size=6,
            summarizer=LlmEventSummarizer(
                llm=build_gemini_model(resolved, stage=ModelStage.HISTORY_SUMMARIZATION)
            ),
        ),
    )
