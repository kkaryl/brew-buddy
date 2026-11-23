"""Official ADK + `agents-cli eval` execution harness for Brew's 120-scenario suite.

Supports two execution modes:
1. `deterministic-adk`: Drives all 120 scenarios (or 15-case smoke subset) through Brew's
   real ADK `Runner`, `ConversationCoachGuardrailPlugin`, `CoachingToolDependencies`, and
   `eval_fixtures` using a deterministic tool-driving `BaseLlm`, writes canonical
   `EvaluationDataset` traces, and grades them with `agents-cli eval grade` against
   `tests/eval/eval_deterministic_config.yaml`.
2. `live-agents-cli`: Boots a local `uvicorn` server hosting `app.fast_api_app:app` with
   `BREW_SEED_EVAL_FIXTURES=true`, runs `agents-cli eval generate --url ... --app-name app`
   against live Gemini, and grades the resulting traces with `agents-cli eval grade`
   against `tests/eval/eval_config.yaml` (deterministic + Gemini LLM-as-judge metrics).
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from google.adk.apps.app import App
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types as genai_types
from pydantic import ConfigDict

from app.agent import build_conversation_coach_agent
from app.config import AppSettings
from app.infrastructure.container import build_service_container
from app.infrastructure.eval_fixtures import EVAL_CLI_USER_ID
from app.plugins.coach_guardrails import ConversationCoachGuardrailPlugin
from app.tools.coaching_tools import CoachingToolDependencies
from tests.eval import guardrail_compliance, trajectory_contract
from tests.eval.scenario_catalog import (
    write_eval_datasets,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
DEFAULT_AGENTS_CLI = shutil.which("agents-cli") or str(
    Path.home() / ".local" / "bin" / "agents-cli"
)

_CONTACT_ID_RE = re.compile(r"\b(cnt_[A-Za-z0-9_-]+)\b")
_MEETING_ID_RE = re.compile(r"\b(mtg_[A-Za-z0-9_-]+)\b")
_SLASH_BAD_ID_RE = re.compile(r"contact_id\s+['\"]([^'\"]+)['\"]")

_active_eval_meta: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "brew_active_eval_meta",
    default=None,
)


class ScenarioDeterministicCoachLlm(BaseLlm):
    """Stateless deterministic `BaseLlm` driving real ADK tool calls across concurrent tasks."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self) -> None:
        super().__init__(model="deterministic-eval-coach")

    @property
    def _meta(self) -> dict[str, Any]:
        return _active_eval_meta.get() or {}

    def _extract_last_user_text(self, llm_request: LlmRequest) -> str:
        for content in reversed(llm_request.contents or []):
            if content.role == "user":
                texts = [p.text for p in (content.parts or []) if p.text]
                if texts:
                    return "\n".join(texts)
        return ""

    def _collect_tool_responses(self, llm_request: LlmRequest) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for content in llm_request.contents or []:
            for part in content.parts or []:
                if part.function_response and part.function_response.name:
                    resp = part.function_response.response
                    results[part.function_response.name] = (
                        dict(resp) if isinstance(resp, dict) else {}
                    )
        return results

    def _plan_tool_calls(self, user_text: str) -> list[genai_types.Part]:
        expected = set(self._meta.get("expected_tools_any") or [])
        forbidden = set(self._meta.get("forbidden_tools") or [])
        lowered = user_text.lower()
        parts: list[genai_types.Part] = []

        # Avoid matching untrusted embedded directives inside quotes/bios unless expected
        safe_head = user_text.split("--- BEGIN BIO ---")[0].split("P.S. Assistant:")[0]
        contact_matches = _CONTACT_ID_RE.findall(safe_head)
        primary_cid = contact_matches[0] if contact_matches else None

        if "get_user_preferences" in expected or (
            "saved preferences" in lowered and "get_user_preferences" not in forbidden
        ):
            parts.append(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        id="fc_eval_prefs",
                        name="get_user_preferences",
                        args={"max_preference_memories": 5},
                    )
                )
            )

        if "suggest_memory_candidates" in expected and "suggest_memory_candidates" not in forbidden:
            mtg_matches = _MEETING_ID_RE.findall(safe_head)
            args: dict[str, Any] = {
                "notes": user_text[:1500],
                "source_type": "meeting_notes",
                "max_candidates": 5,
            }
            if primary_cid:
                args["contact_id"] = primary_cid
            if mtg_matches:
                args["meeting_id"] = mtg_matches[0]
            parts.append(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        id="fc_eval_stage",
                        name="suggest_memory_candidates",
                        args=args,
                    )
                )
            )
            return parts

        if primary_cid and (
            "get_contact_context" in expected or "get_contact_context" not in forbidden
        ):
            parts.append(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        id="fc_eval_contact",
                        name="get_contact_context",
                        args={"contact_id": primary_cid, "max_memories": 5},
                    )
                )
            )
        elif self._meta.get("expects_error_acknowledgment") and not primary_cid:
            bad_match = _SLASH_BAD_ID_RE.search(safe_head)
            if bad_match:
                parts.append(
                    genai_types.Part(
                        function_call=genai_types.FunctionCall(
                            id="fc_eval_bad_contact",
                            name="get_contact_context",
                            args={"contact_id": bad_match.group(1), "max_memories": 5},
                        )
                    )
                )

        if primary_cid and (
            "get_meeting_history" in expected
            or ("meeting history" in lowered and "get_meeting_history" not in forbidden)
        ):
            parts.append(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        id="fc_eval_history",
                        name="get_meeting_history",
                        args={"contact_id": primary_cid, "limit": 5},
                    )
                )
            )

        return parts

    def _synthesize_grounded_reply(
        self,
        user_text: str,
        tool_outputs: dict[str, dict[str, Any]],
    ) -> str:
        category = str(self._meta.get("category") or "")
        sections: list[str] = []

        # Surface any tool errors honestly first
        for tool_name, payload in tool_outputs.items():
            if payload.get("status") == "error":
                err = payload.get("error") or {}
                code = err.get("code", "ERROR")
                msg = err.get("message", "Tool lookup failed.")
                sections.append(
                    f"**Tool Recovery Notice (`{tool_name}` — `{code}`):** Saved records were "
                    f"unavailable or could not be accessed ({msg}). I am proceeding strictly "
                    "with the details you provided directly in this conversation without "
                    "inventing any unverified contact records."
                )

        if category == "missing_information" and len(user_text.strip()) < 75:
            return (
                "To tailor a useful preparation brief, could you clarify three quick essentials?\n"
                "1. **Counterpart & Role:** Who are you meeting and how do you know them?\n"
                "2. **Primary Goal:** What is the #1 insight or outcome you want from the chat?\n"
                "3. **Timebox:** Do you have 15, 30, or 45 minutes?"
            )

        if "suggest_memory_candidates" in tool_outputs:
            staged_data = tool_outputs["suggest_memory_candidates"].get("data") or {}
            cands = staged_data.get("candidates") or []
            cand_lines = "\n".join(
                f"- **Pending Candidate (`{c.get('scope')}`):** {c.get('text')}" for c in cands
            )
            return (
                "### Staged Memory Proposals (Pending Human Review)\n"
                "All extracted takeaways remain `pending` and require your explicit approval "
                "before becoming durable active memories:\n"
                f"{cand_lines or '- No safe candidate memories met extraction criteria.'}"
            )

        contact_data = (tool_outputs.get("get_contact_context") or {}).get("data") or {}
        if contact_data:
            name = contact_data.get("name", "Counterpart")
            org = contact_data.get("organization") or "no organization recorded"
            title = contact_data.get("title") or "no title recorded"
            mems = contact_data.get("approved_memories") or []
            mem_summary = (
                "; ".join(m.get("text", "") for m in mems)
                if mems
                else "No approved prior session memories on file."
            )
            sections.append(
                f"### Known Facts & Session-Attributed Context\n"
                f"- **Saved Profile:** {name} ({title}, {org}).\n"
                f"- **Session-Recorded Notes (user-attributed, not universal world facts):** "
                f"{mem_summary}"
            )
        else:
            sections.append(
                "### Known Facts vs. Coaching Suggestions\n"
                "- **Known Facts:** Grounded strictly in the details shared in your prompt.\n"
                "- **Coaching Suggestions:** The agenda and open-ended questions below are "
                "proposed hypotheses to explore—never unverified biographical claims."
            )

        duration = "15-minute" if "15" in user_text else "25-to-30-minute"
        sections.append(
            f"### Suggested Openers & {duration} Time-Boxed Flow\n"
            "- **Opener 1:** Warm, context-setting greeting thanking them for making time and "
            "stating your core learning goal upfront.\n"
            "- **Opener 2:** Light check-in respecting the agreed hard stop.\n"
            "- **Agenda:** Brief framing (3 min) -> Prioritized open-ended trade-off questions "
            "(core block) -> Concrete follow-up takeaway & wrap-up (2-3 min)."
        )
        sections.append(
            "### Prioritized Open-Ended Questions\n"
            "1. **Concrete Trade-Offs:** Walk me through a recent architectural or workflow "
            "decision where your team had to balance competing constraints—what surprised you?\n"
            "   - *Rationale:* Invites grounded stories tied directly to your meeting objective.\n"
            "2. **Bottlenecks & Evolution:** Looking back at the last quarter, which friction "
            "point took the most iteration to untangle, and what actually moved the needle?\n"
            "   - *Rationale:* Surfaces candid, practical lessons without leading the witness.\n"
            "3. **Next-Step Perspective:** If someone were exploring this problem space fresh "
            "today, which pitfall or blind spot would you advise watching out for first?\n"
            "   - *Rationale:* Closes with actionable forward-looking signal."
        )
        return "\n\n".join(sections)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        user_text = self._extract_last_user_text(llm_request)
        tool_outputs = self._collect_tool_responses(llm_request)
        has_prior_tool_activity = bool(tool_outputs) or any(
            part.function_call is not None or part.function_response is not None
            for content in (llm_request.contents or [])
            for part in (content.parts or [])
        )

        if not has_prior_tool_activity:
            planned_calls = self._plan_tool_calls(user_text)
            if planned_calls:
                yield LlmResponse(content=genai_types.Content(role="model", parts=planned_calls))
                return

        reply = self._synthesize_grounded_reply(user_text, tool_outputs)
        yield LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=reply)],
            )
        )


def _adk_event_to_eval_dict(event: Event) -> dict[str, Any] | None:
    if event.content is None or not event.content.parts:
        return None
    parts_out: list[dict[str, Any]] = []
    for part in event.content.parts:
        if part.text:
            parts_out.append({"text": part.text})
        elif part.function_call:
            parts_out.append(
                {
                    "function_call": {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args or {}),
                    }
                }
            )
        elif part.function_response:
            parts_out.append(
                {
                    "function_response": {
                        "name": part.function_response.name,
                        "response": dict(part.function_response.response or {}),
                    }
                }
            )
    if not parts_out:
        return None
    return {
        "author": event.author or "conversation_coach",
        "content": {
            "role": event.content.role or "model",
            "parts": parts_out,
        },
    }


async def run_deterministic_adk_traces(dataset_path: Path, trace_out_path: Path) -> dict[str, Any]:
    """Execute every scenario through Brew's real ADK Runner + tools and write trace JSON."""
    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    eval_cases: list[dict[str, Any]] = raw_dataset["eval_cases"]
    populated_cases: list[dict[str, Any]] = []

    settings = AppSettings(
        environment="test",
        persistence_backend="in_memory",
        session_backend="in_memory",
        seed_eval_fixtures=True,
        brief_coach_backend="fake",
        memory_extractor_backend="fake",
        otel_to_cloud=False,
    )
    container = build_service_container(settings)
    deps = CoachingToolDependencies(
        preferences_reader=container.preferences_repo,
        contact_reader=container.contact_repo,
        meeting_reader=container.meeting_repo,
        memory_reader=container.memory_repo,
        proposal_stager=container.proposal_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
        io_timeout_seconds=5.0,
    )
    session_service = InMemorySessionService()
    shared_llm = ScenarioDeterministicCoachLlm()
    shared_agent = build_conversation_coach_agent(
        settings,
        tool_dependencies=deps,
        model_override=shared_llm,
    )
    shared_app = App(
        name="app",
        root_agent=shared_agent,
        plugins=[ConversationCoachGuardrailPlugin()],
    )
    shared_runner = Runner(app=shared_app, session_service=session_service)
    semaphore = asyncio.Semaphore(20)

    async def _execute_one(idx: int, case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            meta = case.get("brew_eval_meta") or {}
            token = _active_eval_meta.set(meta)
            try:
                session_id = f"ses_eval_{idx:03d}_{case['eval_case_id']}"
                session = await session_service.create_session(
                    app_name="app",
                    user_id=EVAL_CLI_USER_ID,
                    session_id=session_id,
                )

                prior_event_dicts: list[dict[str, Any]] = []
                if case.get("prompt"):
                    trailing_text = case["prompt"]["parts"][0]["text"]
                else:
                    raw_events = case["agent_data"]["turns"][0]["events"]
                    prior_event_dicts = list(raw_events[:-1])
                    trailing_text = raw_events[-1]["content"]["parts"][0]["text"]
                    for p_idx, p_ev in enumerate(prior_event_dicts):
                        await session_service.append_event(
                            session=session,
                            event=Event(
                                invocation_id=f"inv_seed_{p_idx}",
                                author=p_ev["author"],
                                content=genai_types.Content.model_validate(p_ev["content"]),
                            ),
                        )

                user_msg = genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=trailing_text)],
                )
                generated_events: list[dict[str, Any]] = [
                    {
                        "author": "user",
                        "content": {"role": "user", "parts": [{"text": trailing_text}]},
                    }
                ]
                final_text = ""
                async for ev in shared_runner.run_async(
                    user_id=EVAL_CLI_USER_ID,
                    session_id=session_id,
                    new_message=user_msg,
                ):
                    converted = _adk_event_to_eval_dict(ev)
                    if converted is not None:
                        generated_events.append(converted)
                        for p in converted["content"]["parts"]:
                            if "text" in p:
                                final_text = p["text"]

                merged_case = dict(case)
                merged_case["responses"] = [
                    {"response": {"role": "model", "parts": [{"text": final_text}]}}
                ]
                merged_case["response"] = {"role": "model", "parts": [{"text": final_text}]}
                merged_case["agent_data"] = {
                    "agents": {
                        "conversation_coach": {
                            "agent_id": "conversation_coach",
                            "agent_type": "LlmAgent",
                            "description": shared_agent.description,
                        }
                    },
                    "turns": [
                        {
                            "turn_index": 0,
                            "events": [*prior_event_dicts, *generated_events],
                        }
                    ],
                }
                return merged_case
            finally:
                _active_eval_meta.reset(token)

    populated_cases = list(
        await asyncio.gather(*(_execute_one(i, c) for i, c in enumerate(eval_cases)))
    )

    trace_payload = {"eval_cases": populated_cases}
    trace_out_path.parent.mkdir(parents=True, exist_ok=True)
    trace_out_path.write_text(
        json.dumps(trace_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Compute per-category breakdown with local deterministic evaluators
    by_category: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for item in populated_cases:
        g_res = guardrail_compliance.evaluate(item)
        t_res = trajectory_contract.evaluate(item)
        cat = str((item.get("brew_eval_meta") or {}).get("category", "unknown"))
        by_category[cat].append((float(g_res["score"]), float(t_res["score"])))

    category_summary = {
        cat: {
            "cases": len(scores),
            "guardrail_mean": round(sum(s[0] for s in scores) / len(scores), 4),
            "trajectory_mean": round(sum(s[1] for s in scores) / len(scores), 4),
        }
        for cat, scores in by_category.items()
    }
    return {
        "total_cases": len(populated_cases),
        "trace_path": str(trace_out_path),
        "categories": category_summary,
    }


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, proc: subprocess.Popen[str], timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            msg = f"Eval server exited prematurely with code {proc.returncode}"
            raise RuntimeError(msg)
        try:
            with urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return
        except URLError:
            time.sleep(0.25)
    msg = f"Timed out waiting for local Brew eval server at {url}"
    raise TimeoutError(msg)


def run_live_agents_cli_eval(
    *,
    dataset_path: Path,
    config_path: Path,
    traces_out: Path,
    results_dir: Path,
    concurrency: int,
    qps: float,
) -> int:
    """Launch fixture-seeded Brew server and execute `agents-cli eval generate` + `grade`."""
    port = _find_free_port()
    env = os.environ.copy()
    env["BREW_SEED_EVAL_FIXTURES"] = "true"
    env["BREW_PERSISTENCE_BACKEND"] = "in_memory"
    env["BREW_SESSION_BACKEND"] = "in_memory"
    env["OTEL_TO_CLOUD"] = "false"
    env.setdefault("HTTP_TIMEOUT_SECONDS", "60.0")
    env.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")

    server_log_path = ARTIFACTS_DIR / "live_eval" / "eval_server.log"
    server_log_path.parent.mkdir(parents=True, exist_ok=True)
    uvicorn_bin = str(REPO_ROOT / ".venv" / "bin" / "uvicorn")
    with server_log_path.open("w", encoding="utf-8") as server_log_file:
        server_proc = subprocess.Popen(
            [
                uvicorn_bin,
                "app.fast_api_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=server_log_file,
            stderr=server_log_file,
            text=True,
        )
        try:
            _wait_for_health(port, server_proc)
            gen_cmd = [
                DEFAULT_AGENTS_CLI,
                "eval",
                "generate",
                "--url",
                f"http://127.0.0.1:{port}",
                "--app-name",
                "app",
                "--dataset",
                str(dataset_path),
                "--output",
                str(traces_out),
                "--concurrency",
                str(concurrency),
            ]
            print(f"Running: {' '.join(gen_cmd)}", flush=True)
            gen_res = subprocess.run(gen_cmd, cwd=str(REPO_ROOT), env=env, check=False)
            if gen_res.returncode != 0:
                return gen_res.returncode
        finally:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    grade_cmd = [
        DEFAULT_AGENTS_CLI,
        "eval",
        "grade",
        "--traces",
        str(traces_out),
        "--config",
        str(config_path),
        "--output",
        str(results_dir),
        "--qps",
        str(qps),
    ]
    print(f"Running: {' '.join(grade_cmd)}", flush=True)
    grade_res = subprocess.run(grade_cmd, cwd=str(REPO_ROOT), env=env, check=False)
    return grade_res.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Brew ADK / Agents CLI evaluation suite.")
    parser.add_argument(
        "--mode",
        choices=("deterministic-adk", "live-agents-cli", "export-only"),
        default="deterministic-adk",
    )
    parser.add_argument(
        "--subset",
        choices=("comprehensive", "smoke"),
        default="comprehensive",
    )
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--qps", type=float, default=6.0)
    parser.add_argument(
        "--grade-via-cli",
        action="store_true",
        help="Invoke `agents-cli eval grade` on deterministic traces as well.",
    )
    args = parser.parse_args()

    comp_path, smoke_path = write_eval_datasets()
    target_dataset = comp_path if args.subset == "comprehensive" else smoke_path

    if args.mode == "export-only":
        print(f"Exported datasets:\n  - {comp_path}\n  - {smoke_path}")
        return 0

    if args.mode == "deterministic-adk":
        trace_file = ARTIFACTS_DIR / "deterministic_eval" / f"traces_{args.subset}_120.json"
        summary = asyncio.run(run_deterministic_adk_traces(target_dataset, trace_file))
        print(json.dumps(summary, indent=2))
        if args.grade_via_cli:
            det_cfg = REPO_ROOT / "tests" / "eval" / "eval_deterministic_config.yaml"
            out_dir = ARTIFACTS_DIR / "deterministic_eval" / "grade_results"
            grade_cmd = [
                DEFAULT_AGENTS_CLI,
                "eval",
                "grade",
                "--traces",
                str(trace_file),
                "--config",
                str(det_cfg),
                "--output",
                str(out_dir),
            ]
            res = subprocess.run(grade_cmd, cwd=str(REPO_ROOT), check=False)
            return res.returncode
        return 0

    traces_out = ARTIFACTS_DIR / "live_eval" / f"traces_{args.subset}.json"
    results_dir = ARTIFACTS_DIR / "live_eval" / f"grade_results_{args.subset}"
    cfg = REPO_ROOT / "tests" / "eval" / "eval_config.yaml"
    return run_live_agents_cli_eval(
        dataset_path=target_dataset,
        config_path=cfg,
        traces_out=traces_out,
        results_dir=results_dir,
        concurrency=args.concurrency,
        qps=args.qps,
    )


if __name__ == "__main__":
    sys.exit(main())
