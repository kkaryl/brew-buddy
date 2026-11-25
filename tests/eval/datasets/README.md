# Brew Agent Evaluation Datasets & Harness

This directory contains Brew's official `agents-cli eval` / Google ADK evaluation datasets:

- **`brew-comprehensive-dataset.json`** — **120 representative scenarios** (8 scenarios across each of the 15 required coaching, personalization, memory, grounding, security, and resilience categories), mixing single-turn (`prompt`) and multi-turn continuation (`agent_data.turns`) cases with per-case `rubric_groups`.
- **`brew-stratified-smoke-dataset.json`** — **15 stratified scenarios** (1 representative scenario per category across all 15 categories) for rapid iterative live Gemini regression checks.
- **`basic-dataset.json`** — Minimal 3-case quick-check scaffold dataset.

## 15 Covered Scenario Categories (8 Cases Each = 120 Total)

1. `first_time_networking_chat` — First-time networking chat
2. `senior_engineering_manager` — Senior engineering manager
3. `potential_mentor` — Potential mentor
4. `customer_discovery_meeting` — Customer discovery meeting
5. `returning_contact` — Returning contact
6. `casual_peer_conversation` — Casual peer conversation
7. `short_15_min_meeting` — Short 15-minute meeting
8. `preference_personalization` — Preference personalization
9. `cross_session_memory_recall` — Cross-session memory recall
10. `conflicting_memory` — Conflicting memory
11. `missing_information` — Missing information
12. `unsupported_person_claims` — Unsupported person-specific claims
13. `untrusted_profile_prompt_injection` — Untrusted profile text / prompt injection
14. `tool_failure` — Tool failure (`TIMEOUT`, `SERVICE_UNAVAILABLE`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`)
15. `follow_up_preparation` — Follow-up preparation

## What Each Mode Measures

| Mode | Model that answers | What a score tells you |
| :--- | :--- | :--- |
| `deterministic-adk` | A scripted `BaseLlm` (`ScenarioDeterministicCoachLlm`). No Gemini call. | Tools, guardrail plugin, fixtures, fault injection and trace format work end to end. |
| `live-agents-cli` | `conversation_coach` on `GEMINI_MODEL`. | How the agent actually behaves. |

Deterministic mode is a **tool, guardrail and fault-injection smoke test with a scripted model**. The scripted model plans its tool calls from the same scenario metadata the trajectory metric then checks, so its 120/120 result is expected by construction and says nothing about agent quality. **Only the live mode measures agent behaviour.** Do not quote a deterministic score as an agent quality number.

That the deterministic metrics can fail is proven separately. `tests/unit/test_eval_harness_contracts.py` runs a deliberately bad scripted agent (`ScenarioMisbehavingCoachLlm`) through the same ADK runner path and asserts that each misbehaviour scores below the configured threshold.

## Running Evaluations

```bash
# 1. Smoke test: scripted model through the real ADK Runner, tools and guardrails,
#    graded with `agents-cli eval grade`. No model quota needed. Not an agent quality score.
make eval-deterministic
# or:
uv run python -m tests.eval.run_eval_suite --mode deterministic-adk --subset comprehensive --grade-via-cli

# 2. Agent behaviour, 15-category stratified suite: live Gemini inference + LLM-as-judge
make eval-smoke
# or:
uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset smoke --concurrency 4 --qps 4

# 3. Agent behaviour, all 120 scenarios: live Gemini inference + LLM-as-judge
make eval
# or:
uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset comprehensive --concurrency 8 --qps 8
```

## Models

- **Agent under test:** `conversation_coach` on `GEMINI_MODEL` (default `gemini-3.8-flash`).
- **Judge:** `BREW_EVAL_JUDGE_MODEL` (default `gemini-4-hydrogen`), used by `brew_coaching_judge.py` and `response_quality.py`. The judge never reads `GEMINI_MODEL`, so by default it is a different model from the agent it grades. If you override both to the same model, the harness prints a warning and records `judge_differs_from_agent_model: false`.

## Outputs And Attribution

The harness writes to `artifacts/deterministic_eval/` or `artifacts/live_eval/` (traces, grade results and, in live mode, the eval server log). Each run also writes `run_metadata.json` into that directory with the UTC timestamp, git commit and dirty flag, mode and subset, dataset file name and SHA-256, `GEMINI_MODEL`, `BREW_SYNTHESIS_MODEL`, `BREW_EVAL_JUDGE_MODEL`, the installed `google-adk` version and the run's exit code. Git and package lookups that fail are recorded as `null`. The file describes the most recent run in that directory, so copy the directory if you need to keep an earlier run.

## Trajectory Expectations

Each case carries `brew_eval_meta`, read by `trajectory_contract.py`:

| Field | Meaning |
| :--- | :--- |
| `expected_tools_any` | At least one listed tool must be called. |
| `expected_tools_all` | Every listed tool must be called. |
| `allowed_tools` | No tool outside the list may be called. An empty list means no tool call is acceptable. Absent means no allow-list. |
| `expected_tool_args` | Per tool, argument key/value pairs that at least one call to that tool must carry. |
| `forbidden_tools` | None of the listed tools may be called. |
| `max_tool_calls` | Tool call budget for the turn. |

`expected_tools_all`, `allowed_tools` and `expected_tool_args` are optional and are emitted only when a scenario sets them. Set them in `scenario_catalog.py` only where the scenario's own rubric states the expectation, because they change live pass criteria.

## Editing Scenarios

`scenario_catalog.py` is the source of truth and the two `brew-*.json` files are generated from it. After editing the catalog, regenerate and commit them:

```bash
uv run python -m tests.eval.scenario_catalog
```

`tests/unit/test_eval_harness_contracts.py` fails when the committed JSON and the catalog differ. Tests never rewrite these files.
