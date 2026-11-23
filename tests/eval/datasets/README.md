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

## Running Evaluations

```bash
# 1. Deterministic ADK Runner + official `agents-cli eval grade` across all 120 scenarios (no live LLM quota required)
make eval-deterministic
# or:
uv run python -m tests.eval.run_eval_suite --mode deterministic-adk --subset comprehensive --grade-via-cli

# 2. Live Gemini (`gemini-3.8-flash`) inference + LLM-as-judge across the 15-category stratified suite
make eval-smoke
# or:
uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset smoke --concurrency 4 --qps 4

# 3. Live Gemini (`gemini-3.8-flash`) inference + LLM-as-judge across all 120 scenarios
make eval
# or:
uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset comprehensive --concurrency 8 --qps 8
```
