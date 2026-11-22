"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml)."""

from __future__ import annotations

import os
import threading
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
DEFAULT_EVAL_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    """Return one cached GenAI client per grading worker thread."""
    client: genai.Client | None = getattr(_local, "client", None)
    if client is None:
        client = genai.Client()
        _local.client = client
    return client


def evaluate(instance: dict[str, Any]) -> dict[str, Any]:
    """Grade an agent response on a 1-5 scale for accuracy, relevance, and clarity."""
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, and clarity."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    response = _client().models.generate_content(
        model=DEFAULT_EVAL_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    verdict = response.parsed
    if not isinstance(verdict, _Verdict):
        return {"score": 0, "explanation": response.text or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
