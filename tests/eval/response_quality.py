"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml).

Live mode only. The judge model comes from `BREW_EVAL_JUDGE_MODEL` (default
`gemini-4-hydrogen`), never from the agent's `GEMINI_MODEL`.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
# The judge has its own model setting so it does not grade the agent under test with the
# agent's own model. `GEMINI_MODEL` (the agent's model) is deliberately not consulted.
JUDGE_MODEL_ENV_VAR = "BREW_EVAL_JUDGE_MODEL"
DEFAULT_JUDGE_MODEL = "gemini-4-hydrogen"


def resolve_judge_model() -> str:
    """Return the judge model id: `BREW_EVAL_JUDGE_MODEL` when set, else the default."""
    return (os.getenv(JUDGE_MODEL_ENV_VAR) or "").strip() or DEFAULT_JUDGE_MODEL


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    """Return one cached GenAI client per grading worker thread."""
    client: genai.Client | None = getattr(_local, "client", None)
    if client is None:
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        use_enterprise = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not api_key and (use_enterprise or use_vertex or os.getenv("GOOGLE_CLOUD_PROJECT")):
            kwargs: dict[str, Any] = {
                "vertexai": True,
                "location": os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            }
            project = (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
            if project:
                kwargs["project"] = project
            client = genai.Client(**kwargs)
        else:
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
        model=resolve_judge_model(),
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
