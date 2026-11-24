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
from opentelemetry import trace

from app.application.correlation import get_workflow_correlation
from app.application.telemetry import mark_span_error, stamp_correlation_attributes
from app.domain.ports import BriefAttemptMetrics

logger = logging.getLogger(__name__)


def _canonical_tool_signature(tool_name: str, tool_args: dict[str, Any]) -> str:
    serialized = json.dumps(tool_args, sort_keys=True, default=str, separators=(",", ":"))
    return f"{tool_name}:{serialized}"


class WorkflowSafeguardPlugin(BasePlugin):
    """Per-attempt ADK safeguard plugin capping LLM calls, tool retries, and token accounting."""

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
        self._active_model_name: str | None = None
        self.budget_exceeded: bool = False

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """Enforce hard per-request LLM invocation limit and log model intent."""
        corr = get_workflow_correlation()
        agent_name = getattr(callback_context, "agent_name", "conversation_coach")
        model_name = getattr(llm_request, "model", None)
        self._active_model_name = model_name

        if self._metrics.model_invocations >= self._metrics.remaining_model_budget:
            self.budget_exceeded = True
            current_span = trace.get_current_span()
            stamp_correlation_attributes(current_span)
            mark_span_error(
                current_span,
                classification="MODEL_INVOCATION_LIMIT_EXCEEDED",
                error_code="MODEL_INVOCATION_LIMIT_EXCEEDED",
            )
            logger.error(
                "Blocked model call exceeding per-request invocation budget",
                extra={
                    "event_type": "workflow.model.budget_exceeded",
                    "operation_name": "model.generate_content",
                    "agent_name": agent_name,
                    "model_name": model_name,
                    "request_id": corr.request_id if corr else None,
                    "trace_id": corr.trace_id if corr else None,
                    "result_status": "error",
                    "error_code": "MODEL_INVOCATION_LIMIT_EXCEEDED",
                    "error_classification": "MODEL_INVOCATION_LIMIT_EXCEEDED",
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
        self._model_start_time = time.perf_counter()
        logger.info(
            f"Workflow model intent: invocation {self._metrics.model_invocations}/"
            f"{self._metrics.remaining_model_budget}",
            extra={
                "event_type": "workflow.model.intent",
                "operation_name": "model.generate_content",
                "agent_name": agent_name,
                "model_name": model_name,
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
        """Accumulate token usage and log structured model outcome latency."""
        corr = get_workflow_correlation()
        agent_name = getattr(callback_context, "agent_name", "conversation_coach")
        elapsed_ms = (
            round((time.perf_counter() - self._model_start_time) * 1000.0, 2)
            if self._model_start_time is not None
            else 0.0
        )
        self._model_start_time = None
        model_name = getattr(llm_response, "model_version", None) or self._active_model_name

        usage = getattr(llm_response, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", None) if usage is not None else None
        out_tok = getattr(usage, "candidates_token_count", None) if usage is not None else None
        tot_tok = getattr(usage, "total_token_count", None) if usage is not None else None
        if isinstance(in_tok, int):
            self._metrics.input_tokens += in_tok
        if isinstance(out_tok, int):
            self._metrics.output_tokens += out_tok
        if isinstance(tot_tok, int):
            self._metrics.total_tokens += tot_tok
        elif isinstance(in_tok, int) and isinstance(out_tok, int):
            tot_tok = in_tok + out_tok
            self._metrics.total_tokens += tot_tok

        logger.info(
            f"Workflow model outcome completed in {elapsed_ms}ms",
            extra={
                "event_type": "workflow.model.outcome",
                "operation_name": "model.generate_content",
                "agent_name": agent_name,
                "model_name": model_name,
                "request_id": corr.request_id if corr else None,
                "trace_id": corr.trace_id if corr else None,
                "duration_ms": elapsed_ms,
                "result_status": "ok",
                "input_tokens": in_tok if isinstance(in_tok, int) else None,
                "output_tokens": out_tok if isinstance(out_tok, int) else None,
                "total_tokens": tot_tok if isinstance(tot_tok, int) else None,
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
            current_span = trace.get_current_span()
            stamp_correlation_attributes(current_span)
            mark_span_error(
                current_span,
                classification="TOOL_RETRY_LIMIT_EXCEEDED",
                error_code="TOOL_RETRY_LIMIT_EXCEEDED",
            )
            logger.warning(
                f"Capped retry for tool {tool.name} (prior_failures={prior_failures}, "
                f"max_retries={self._metrics.max_tool_retries})",
                extra={
                    "event_type": "workflow.tool.retry_capped",
                    "operation_name": f"tool.{tool.name}",
                    "agent_name": agent_name,
                    "tool_name": tool.name,
                    "request_id": corr.request_id if corr else None,
                    "trace_id": corr.trace_id if corr else None,
                    "result_status": "error",
                    "error_code": "TOOL_RETRY_LIMIT_EXCEEDED",
                    "error_classification": "TOOL_RETRY_LIMIT_EXCEEDED",
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
