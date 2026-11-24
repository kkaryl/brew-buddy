# AGENTS.md — Permanent Engineering Rules & Working Agreement

Welcome to **Brew**, an AI-powered Coffee Chat Buddy that helps professionals prepare for coffee chats, networking meetings, mentorship conversations, and customer discovery meetings while compounding relationship context across sessions through user-approved memory.

This document is the permanent engineering constitution for all human engineers and AI coding agents working in this repository. Every change MUST adhere to these rules.

---

## 1. Mandatory Working Agreement

Before implementing **any** feature, bug fix, or slice:

1. **Inspect existing code**: Examine relevant modules, tests, configuration, and ADK reference recipes before proposing or writing code.
2. **Explain the intended change briefly**: State the goal, affected boundaries, and design Trade-offs concisely before editing.
3. **Implement the smallest complete vertical slice**: Deliver end-to-end functionality across only the layers required for the current slice—avoid speculative scaffolding or dead code.
4. **Add appropriate tests**:
   - Deterministic unit and integration tests (`pytest` for backend, `Vitest` for frontend) covering domain invariants, schemas, error handling, and adapter contracts.
   - Behavioral agent evaluations (`agents-cli eval`) for non-deterministic LLM behavior, tool trajectories, and persona adherence. **Never assert raw LLM prose in `pytest`.**
5. **Execute tests, lint, and type checks**: Run all applicable validation suites locally in the workspace.
6. **Report actual results and any blockers**: Share exact command outcomes (pass counts, lint/type statuses, or concrete failure diagnostics).
7. **Update documentation when behavior changes**: Keep `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, `docs/OBSERVABILITY.md`, `docs/DEPLOYMENT.md`, and `docs/DECISIONS.md` synchronized with the codebase.

> **Hard Gate:** **Never mark a step complete if validation did not run.** If an environment issue prevents running a check, report the blocker explicitly and leave the step incomplete.

---

## 2. Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Language & Runtime** | Python 3.12 (managed via `uv`), TypeScript 5.x (Node LTS) |
| **Backend API** | FastAPI + Pydantic v2 |
| **Agent Framework & CLI** | Google ADK 2.x (`google-adk >= 2.0.0`) + `google-agents-cli` (`agents-cli`) |
| **LLM Provider** | Gemini via Google Cloud (`google-genai` / Vertex AI) |
| **Frontend** | React + Vite + TypeScript + Tailwind CSS |
| **Persistence** | Google Cloud Firestore |
| **Observability** | OpenTelemetry SDK + Google Cloud Trace + Structured JSON Logging |
| **Security & Secrets** | Google Cloud Secret Manager + Active PII Redaction |
| **Backend Quality Gates** | `pytest`, `ruff` (lint + format), `mypy` / `pyright` (strict static typing) |
| **Frontend Quality Gates** | `Vitest`, ESLint, `tsc --noEmit` |
| **Infrastructure & CI/CD** | Terraform (IaC) + GitHub Actions or Google Cloud Build |

---

## 3. Core Engineering Standards

### 3.1 Architecture, Cohesion, and Dependency Boundaries
- **Domain Independence**: Core domain models, value objects, business rules, domain errors, and repository/service ports (`domain/`) MUST have **zero dependencies** on `google-adk`, `google-cloud-firestore`, `fastapi`, or HTTP/LLM SDKs.
- **High Cohesion, Low Coupling**: Group code by cohesive responsibility. Apply SOLID principles pragmatically where they improve clarity and testability, not ceremonially.
- **No Unnecessary Frameworks or Design Patterns**: Do not introduce extra ORMs, DI frameworks, message buses, or abstract factory hierarchies when plain Python protocols, constructor injection, and Pydantic models suffice.
- **Dependency Injection at Integration Boundaries**: Pass repositories, LLM/agent runners, clock, secret providers, telemetry tracers, and PII redactors via explicit constructor/function injection at FastAPI route dependencies and application entrypoints.

### 3.2 Typing, Interfaces, and Error Handling
- **Typed Public Interfaces**: Every public function, method, FastAPI endpoint, ADK tool, and React component prop MUST carry explicit type annotations. Avoid `Any` and untyped `dict` payloads across module boundaries.
- **Structured Errors**: Define typed domain error hierarchies mapped cleanly at boundaries:
  - **API Boundary**: Translate domain/infrastructure errors into structured HTTP responses with correlation/trace IDs—never leak raw stack traces or internal resource names to clients.
  - **ADK Tool Boundary**: Catch expected operational errors inside tools and return structured, descriptive recovery guidance so the LLM can self-correct rather than crashing the turn.
- **Timeouts & Graceful Failure**: Every external network call (Gemini/Vertex AI, Firestore, Secret Manager, DLP/redaction, frontend `fetch`) MUST configure an explicit timeout, bounded retry policy where idempotent, and graceful fallback behavior.

### 3.3 Security, Privacy, and Secrets
- **Zero Secrets in Source Control**: Never commit API keys, service account JSON keys, tokens, or `.env` secrets. All sensitive credentials MUST be injected via Google Cloud Secret Manager (or Workload Identity / ADC in Google Cloud) and `.env.example` templates with placeholder values only.
- **PII Redaction by Default**: Scrub personally identifiable information (emails, phone numbers, government IDs, sensitive contact details) before emitting logs or persisting candidate/approved memories.
- **Human-in-the-Loop Memory Governance**: Durable cross-session memories MUST never be committed silently; candidate memories require explicit user review and approval.

### 3.4 Zero-Suppression Quality Policy
- **No Suppressing Test Failures or Type Errors**:
  - Do NOT add `@pytest.mark.skip`, `@pytest.mark.xfail`, `.skip` in Vitest, blanket `# type: ignore`, `@ts-ignore`, or blanket `# noqa` rules to force green builds.
  - Fix root causes immediately. Follow the **Stop-the-Line Rule**: if a change breaks an existing test, lint rule, or type check, fix the regression before proceeding with feature work.

### 3.5 Frontend Design System & Illustration Governance (`docs/DESIGN.md`)
- **Playful Social Club Aesthetic**: All UI screens, CSS tokens (`web/src/index.css`), components (`web/src/components/`), and illustrations (`web/src/assets/illustrations/`) MUST adhere to [`docs/DESIGN.md`](docs/DESIGN.md).
- **Token, Microcopy, & Component Discipline**: Use centralized pastel tokens (`#FFFAF8` app canvas, `#FFFFFF` paper surfaces, `#302731` dark plum text, `#6F5E6A` WCAG AA secondary text, `#EF8B70` coral accents, `Fraunces` headlines, `DM Sans` UI/wordmark), `44px` minimum touch targets, Lucide interface icons, and cohesive flat-vector illustrations. Never use em-dashes (`U+2014` / `&mdash;`) anywhere in the web portal (use periods, commas, colons, or `·` middle dots instead), keep attribution pills concise (`from GCal`), and avoid random emojis, coffee stock photos, noisy system status pills, fake mobile status bars, or harsh black shadows.
- **3-Space Navigation & Focused Rituals**: Use the v2 3-space navigation shell (`TopBarShell` on desktop/tablet and `MobileDock` on mobile across `Clubhouse`, `Cue Studio`, and `Relationship Journal`), and unmount primary navigation in favor of `FocusedTopBar` (`← Back`) during focused rituals (`QuickSparkSetupScreen`, `PocketCueCardsScreen`, and `DebriefKeepsakesScreen`).

---

## 4. ADK 2.x & AgentOps Standards

All agentic components in Brew MUST satisfy these AgentOps engineering standards:

1. **Tool & Interface Design**:
   - Give every ADK tool a specific, verb-noun action name (e.g., `retrieve_counterpart_memories`, `propose_meeting_memory_candidates`—never generic names like `handle_data` or `update_db`).
   - Write comprehensive human- and LLM-readable docstrings documenting purpose, preconditions, parameters, and return semantics.
   - Enforce strict Pydantic input and output JSON schemas on tools and workflow stages.
   - Return structured, actionable recovery instructions on tool validation or downstream failures.
2. **Context & Memory**:
   - Maintain a versioned, explicit system prompt "constitution" defining Brew's persona, coaching domain boundaries, tone constraints, and anti-fabrication rules.
   - Implement history compaction (token/turn sliding window + structured summary compaction) to prevent context bloat in multi-turn brief refinements.
   - Persist session state and approved memories in Firestore behind repository ports.
   - Execute post-meeting memory extraction and consolidation asynchronously so note submission never blocks the UI.
3. **Orchestration & Logic**:
   - Use ADK 2.x multi-agent patterns (`Workflow` graphs, `SequentialAgent`, or Coordinator + specialist sub-agents) rather than a single monolithic prompt.
   - Route tasks strategically by model capability and latency: fast/cost-efficient Gemini Flash for intake checks, conversational refinements, and candidate memory extraction; higher-reasoning Gemini Pro for initial multi-constraint brief synthesis.
   - Attach runner-wide ADK `BasePlugin` guardrails for policy enforcement, prompt-injection defense, and output validation.
   - Enforce explicit Human-in-the-Loop (HITL) pause/confirmation before promoting candidate memories to long-term storage.
4. **Observability & Tracing**:
   - Emit structured JSON logs (`structlog` or standard library JSON formatter) with `trace_id`, `span_id`, `session_id`, and `agent_name`—never bare `print()` statements in application code.
   - Log **Intent vs. Outcome** around every agent stage and tool invocation (recording intended action/arguments prior to execution and status/latency/outcome summary afterward).
   - Instrument FastAPI, ADK runners/tools, and Firestore adapters with OpenTelemetry spans exported to Google Cloud Trace.
   - Run active PII redaction across log payloads and memory pipelines.
5. **Operational Tooling (`uv` & `agents-cli`)**:
   - Always execute Python commands through `uv` (`uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run mypy src`).
   - Never silently swap configured Gemini model IDs without explicit requirement and ADR documentation.
   - Maintain reproducible offline evaluation suites executed via `agents-cli eval run`.
