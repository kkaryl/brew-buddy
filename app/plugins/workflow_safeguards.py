"""ADK safeguard plugin enforcing model invocation budgets, tool retry caps, and trace logging."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from app.application.correlation import get_workflow_correlation
from app.domain.ports import BriefAttemptMetrics

logger = logging.getLogger(__name__)


def _canonical_tool_signature(tool_name: str, tool_args: dict[str, Any]) -> str:
    serialized = json.dumps(tool_args, sort_keys=True, default=str, separators=(",", ":"))
    return f"{tool_name}:{serialized}"


class WorkflowSafeguardPlugin(BasePlugin):
    """Per-attempt ADK safeguard plugin capping LLM calls and repeated tool retries."""

    def __init__(
        self,
        *,
        attempt_metrics: BriefAttemptMetrics,
        max_total_tool_calls: int = 8,
        name: str = "workflow_safeguards",
    ) -> None:
        super().__init__(name=name)
        self._metrics = attempt_metrics
        self._max_total_tool_calls = max_total_tool_calls
        self._failed_tool_counts: dict[str, int] = {}
        self._model_start_time: float | None = None
        self.budget_exceeded: bool = False

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """Enforce hard per-request LLM invocation limit and log model intent."""
        del llm_request
        corr = get_workflow_correlation()
        agent_name = getattr(callback_context, "agent_name", "conversation_coach")

        if self._metrics.model_invocations >= self._metrics.remaining_model_budget:
            self.budget_exceeded = True
            logger.error(
                "Blocked model call exceeding per-request invocation budget",
                extra={
                    "event_type": "workflow.model.budget_exceeded",
                    "agent_name": agent_name,
                    "request_id": corr.request_id if corr else None,
                    "trace_id": corr.trace_id if corr else None,
                },
            )
            return LlmResponse(
                error_code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                error_message=(
                    "Exceeded maximum allowed model invocations for this workflow request "
                    f"({self._metrics.remaining_model_budget})."
                ),
            )

        self._metrics.model_invocations += 1
        self._model_start_time = time.monotonic()
        logger.info(
            f"Workflow model intent: invocation {self._metrics.model_invocations}/"
            f"{self._metrics.remaining_model_budget}",
            extra={
                "event_type": "workflow.model.intent",
                "agent_name": agent_name,
                "request_id": corr.request_id if corr else None,
                "trace_id": corr.trace_id if corr else None,
            },
        )
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Log structured model outcome latency under the unified request/trace ID."""
        del llm_response
        corr = get_workflow_correlation()
        agent_name = getattr(callback_context, "agent_name", "conversation_coach")
        elapsed_ms = (
            round((time.monotonic() - self._model_start_time) * 1000, 2)
            if self._model_start_time is not None
            else 0.0
        )
        self._model_start_time = None
        logger.info(
            f"Workflow model outcome completed in {elapsed_ms}ms",
            extra={
                "event_type": "workflow.model.outcome",
                "agent_name": agent_name,
                "request_id": corr.request_id if corr else None,
                "trace_id": corr.trace_id if corr else None,
            },
        )
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        """Cap retries on failing tools and total tool calls per attempt."""
        corr = get_workflow_correlation()
        agent_name = getattr(tool_context, "agent_name", "conversation_coach")
        sig = _canonical_tool_signature(tool.name, tool_args)
        prior_failures = self._failed_tool_counts.get(sig, 0)

        if (
            prior_failures > self._metrics.max_tool_retries
            or self._metrics.tool_invocations >= self._max_total_tool_calls
        ):
            if tool.name not in self._metrics.degraded_tools:
                self._metrics.degraded_tools.append(tool.name)
            logger.warning(
                f"Capped retry for tool {tool.name} (prior_failures={prior_failures}, "
                f"max_retries={self._metrics.max_tool_retries})",
                extra={
                    "event_type": "workflow.tool.retry_capped",
                    "agent_name": agent_name,
                    "tool_name": tool.name,
                    "request_id": corr.request_id if corr else None,
                    "trace_id": corr.trace_id if corr else None,
                },
            )
            return {
                "status": "error",
                "data": None,
                "error": {
                    "code": "TOOL_RETRY_LIMIT_EXCEEDED",
                    "message": (
                        f"Tool `{tool.name}` reached the retry limit "
                        f"({self._metrics.max_tool_retries}) for this workflow turn."
                    ),
                    "retryable": False,
                    "recovery_instruction": (
                        f"Stop calling `{tool.name}`. Synthesize the JSON preparation brief "
                        "using only verified context already provided in the prompt without "
                        "claiming unavailable records succeeded."
                    ),
                },
            }

        self._metrics.tool_invocations += 1
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Track structured tool failures so retry budgets are enforced deterministically."""
        del tool_context
        if isinstance(result, dict) and result.get("status") == "error":
            sig = _canonical_tool_signature(tool.name, tool_args)
            self._failed_tool_counts[sig] = self._failed_tool_counts.get(sig, 0) + 1
            if tool.name not in self._metrics.degraded_tools:
                self._metrics.degraded_tools.append(tool.name)
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, Any] | None:
        """Record unexpected tool exceptions against the tool retry cap."""
        del tool_context
        if isinstance(error, asyncio.CancelledError):
            return None
        sig = _canonical_tool_signature(tool.name, tool_args)
        self._failed_tool_counts[sig] = self._failed_tool_counts.get(sig, 0) + 1
        if tool.name not in self._metrics.degraded_tools:
            self._metrics.degraded_tools.append(tool.name)
        return None
