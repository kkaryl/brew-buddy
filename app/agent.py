"""Root ADK ``conversation_coach`` agent and ``App`` definition for Brew."""

from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.apps.app import App

from app.agents.coach import (
    CONVERSATION_COACH_NAME,
    CONVERSATION_COACH_VERSION,
    build_adk_app,
    build_conversation_coach_agent,
    build_root_agent,
)
from app.agents.model_routing import build_gemini_model
from app.agents.prompts import CONVERSATION_COACH_INSTRUCTION

__all__ = [
    "CONVERSATION_COACH_INSTRUCTION",
    "CONVERSATION_COACH_NAME",
    "CONVERSATION_COACH_VERSION",
    "app",
    "build_adk_app",
    "build_conversation_coach_agent",
    "build_gemini_model",
    "build_root_agent",
    "conversation_coach",
    "root_agent",
]

conversation_coach: Agent = build_conversation_coach_agent()
root_agent: Agent = conversation_coach

app: App = build_adk_app(root_agent_override=root_agent)
