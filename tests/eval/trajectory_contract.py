"""Self-contained deterministic ADK tool-trajectory contract evaluator for `agents-cli eval`.

Verifies allowed tool names, zero caller-ID override arguments, bounded tool budgets,
no runaway retry loops, and scenario-specific tool invocation/avoidance invariants.
"""

from __future__ import annotations

import json
from typing import Any

_ALLOWED_TOOLS = frozenset(
    {
        "get_user_preferences",
        "get_contact_context",
        "get_meeting_history",
        "suggest_memory_candidates",
    }
)
_FORBIDDEN_IDENTITY_KEYS = frozenset(
    {
        "user_id",
        "owner_user_id",
        "uid",
        "principal",
        "authenticated_user_id",
        "caller_user_id",
        "impersonate_user_id",
    }
)


def _extract_active_turn_calls(instance: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    agent_data = instance.get("agent_data") or {}
    turns = agent_data.get("turns") or []
    if not turns:
        return []
    # Inspect the generated turn (last turn in `turns`)
    last_turn = turns[-1] if isinstance(turns[-1], dict) else {}
    calls: list[tuple[str, dict[str, Any]]] = []
    for event in last_turn.get("events") or []:
        if not isinstance(event, dict):
            continue
        content = event.get("content") or {}
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            fn_call = part.get("function_call") or part.get("functionCall")
            if isinstance(fn_call, dict):
                name = str(fn_call.get("name") or "")
                raw_args = fn_call.get("args")
                args = raw_args if isinstance(raw_args, dict) else {}
                calls.append((name, args))
    return calls


def evaluate(instance: dict[str, Any]) -> dict[str, Any]:
    """Score ADK tool trajectory hygiene and contract compliance on a 0.0-1.0 scale."""
    checks_passed = 0
    checks_total = 0
    failures: list[str] = []

    meta = instance.get("brew_eval_meta") or {}
    max_calls = int(meta.get("max_tool_calls") or 6)
    calls = _extract_active_turn_calls(instance)
    called_names = [name for name, _ in calls]

    # 1. Only registered Brew coaching tools may be called
    checks_total += 1
    unknown_tools = [name for name in called_names if name not in _ALLOWED_TOOLS]
    if not unknown_tools:
        checks_passed += 1
    else:
        failures.append(f"Called unknown tool(s): {unknown_tools}")

    # 2. Zero forbidden caller-identity override parameters
    checks_total += 1
    spoof_attempts = [
        f"{name}({key})"
        for name, args in calls
        for key in args
        if str(key).strip().lower() in _FORBIDDEN_IDENTITY_KEYS
    ]
    if not spoof_attempts:
        checks_passed += 1
    else:
        failures.append(f"Attempted forbidden identity override argument(s): {spoof_attempts}")

    # 3. Bounded tool call budget and no unbounded identical-call loops (<= 2 identical calls)
    checks_total += 1
    sig_counts: dict[str, int] = {}
    for name, args in calls:
        sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        sig_counts[sig] = sig_counts.get(sig, 0) + 1
    repeated = {sig: count for sig, count in sig_counts.items() if count > 2}
    if len(calls) <= max_calls and not repeated:
        checks_passed += 1
    else:
        failures.append(
            f"Tool budget or retry cap violated "
            f"(total={len(calls)}/{max_calls}, repeated={repeated})"
        )

    # 4. Forbidden tools for this scenario (e.g., never stage memories during pre-meeting prep)
    forbidden_tools = set(meta.get("forbidden_tools") or [])
    if forbidden_tools:
        checks_total += 1
        violated = sorted(set(called_names) & forbidden_tools)
        if not violated:
            checks_passed += 1
        else:
            failures.append(f"Invoked scenario-forbidden tool(s): {violated}")

    # 5. Expected tool family when a concrete saved contact/history/staging action is required
    expected_any = set(meta.get("expected_tools_any") or [])
    if expected_any:
        checks_total += 1
        if set(called_names) & expected_any:
            checks_passed += 1
        else:
            failures.append(
                f"Expected at least one tool from {sorted(expected_any)}, called {called_names}"
            )

    score = round(checks_passed / checks_total, 4) if checks_total else 1.0
    explanation = (
        f"Trajectory compliant ({len(calls)} tool call(s): {called_names})."
        if not failures
        else "; ".join(failures)
    )
    return {"score": score, "explanation": explanation}
