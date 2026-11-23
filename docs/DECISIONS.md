# Architectural Decision Records (ADRs) — Brew

This document records significant architectural and technical decisions for **Brew**, following a lightweight ADR format (`Status`, `Context`, `Decision`, `Consequences`).

---

## ADR-001: Hexagonal Boundary Isolating Domain Logic from ADK and Firestore

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Agent frameworks (`google-adk`) and cloud persistence SDKs (`google-cloud-firestore`) evolve rapidly and carry runtime/network concerns. Mixing framework decorators, SDK document references, and domain business rules (such as meeting timebox validation or memory approval state transitions) creates tight coupling and brittle tests.
- **Decision:** Enforce a strict Ports-and-Adapters boundary. `brew.domain` contains pure Python 3.12 entities, value objects, structured domain errors, and `typing.Protocol` repository/service interfaces with zero imports from ADK, FastAPI, or Firestore. Infrastructure adapters and ADK tools depend inward on `brew.domain`.
- **Consequences:**
  - *Positive:* Domain logic is 100% unit-testable in milliseconds without mocks of cloud SDK internals; persistence or agent SDK upgrades stay localized to adapter packages.
  - *Trade-off:* Requires explicit DTO/entity mapping at the Firestore and API boundaries.

---

## ADR-002: Multi-Agent Workflow Orchestration via Google ADK 2.x and `agents-cli`

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Brew handles distinct cognitive workflows—initial multi-constraint brief generation, iterative conversational refinement, and background post-meeting memory extraction—plus cross-cutting safety, logging, and approval hooks. A single monolithic prompt degrades instruction adherence and complicates schema enforcement.
- **Decision:** Use **Google ADK 2.x** (`Workflow` graph + specialist `LlmAgent` stages and `BasePlugin` runner-wide guardrails) paired with **`google-agents-cli`** (`agents-cli`) for scaffolding conventions, local smoke runs, and golden-dataset behavioral evaluations (`agents-cli eval`).
- **Consequences:**
  - *Positive:* Clean separation of prompts and Pydantic `output_schema` contracts per task; runner-wide safety/observability hooks via `BasePlugin`; standardized offline evaluation workflow.
  - *Trade-off:* Team and CI environments must maintain `uv` and `google-agents-cli` versions cleanly pinned.

---

## ADR-003: Strategic Gemini Model Routing (Pro vs. Flash)

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Not every LLM call in Brew has the same reasoning depth, latency sensitivity, or cost profile. Initial brief generation synthesizes counterpart background, meeting archetype nuances, strict duration budgets, and historical memories, whereas conversational tweaks and note extraction require fast turnaround and structured extraction.
- **Decision:** Route workloads explicitly by stage via injected model configuration:
  - **Gemini Pro** for `BriefSynthesizerAgent` (initial multi-constraint conversation preparation).
  - **Gemini Flash** for `BriefRefinerAgent` (interactive low-latency chat refinements) and `MemoryExtractorAgent` (asynchronous candidate memory extraction).
- **Consequences:**
  - *Positive:* Optimizes user-perceived latency during interactive refinement while preserving high synthesis quality on the initial brief; reduces token spend.
  - *Trade-off:* Both routed models must be covered by `agents-cli eval` suites and regional availability checks.

---

## ADR-004: Asynchronous Memory Extraction with Mandatory Human-in-the-Loop (HITL) Approval

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Extracting candidate memories from post-meeting notes involves PII scrubbing and LLM inference, which would stall the UI if run synchronously. Worse, silently committing LLM-inferred personal facts or user preferences into durable cross-session memory risks hallucination propagation and erodes user trust.
- **Decision:**
  1. Persist PII-scrubbed notes immediately and execute memory extraction asynchronously in the background (`202 Accepted` + status polling/SSE).
  2. Store extracted items exclusively as `CandidateMemory` records in `PENDING_REVIEW` state.
  3. Enforce an explicit Human-in-the-Loop (HITL) approval gate: only items explicitly approved (or edited and approved) by the user transition into `approved_memories` and become eligible for future session retrieval.
- **Consequences:**
  - *Positive:* Sub-second note-saving UX; zero unreviewed memories ever pollute future meeting briefs; transparent user control.
  - *Trade-off:* Requires explicit candidate queue state management and review UI components.

---

## ADR-005: Firestore for Session State, Meeting Artifacts, and Approved Memories

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Brew stores hierarchical, user-scoped, semi-structured documents (meetings, versioned preparation briefs, compacted session histories, notes, and memory records) requiring low-latency reads by `user_id` and `counterpart_key` with serverless operational simplicity on Google Cloud.
- **Decision:** Use **Google Cloud Firestore** (Native mode) behind typed repository protocols (`MeetingRepository`, `SessionRepository`, `MemoryRepository`), paired with history compaction before persisting multi-turn session state.
- **Consequences:**
  - *Positive:* Serverless scaling, native IAM integration, straightforward document hierarchy per user, and local emulator support for integration testing.
  - *Trade-off:* Composite queries require explicit Terraform-managed Firestore index definitions.

---

## ADR-006: Active Fail-Closed PII Redaction Across Logs and Memory Pipelines

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Users paste real meeting notes that may inadvertently include email addresses, phone numbers, or sensitive personal identifiers. Storing or logging raw PII creates compliance and security liabilities.
- **Decision:** Introduce a `PiiRedactor` domain port invoked inside both the logging/tracing guardrail plugin and the note/memory persistence pipeline. In Google Cloud environments, use Cloud Sensitive Data Protection (DLP) with bounded timeouts layered over a deterministic local regex/pattern scrubber so redaction never fails open if a remote API times out.
- **Consequences:**
  - *Positive:* Defense-in-depth protection preventing raw PII from reaching Cloud Logging, Cloud Trace attributes, or Firestore memory collections.
  - *Trade-off:* Slight processing overhead on note ingestion, mitigated by async background execution and tight DLP timeouts.

---

## ADR-007: Dual-Track Validation (`pytest`/`Vitest` + `agents-cli eval`)

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Traditional unit tests excel at deterministic code contracts (schemas, timebox math, state transitions, error recovery, UI state) but become flaky anti-patterns when asserting non-deterministic LLM prose. Conversely, skipping automated agent evaluation allows prompt or routing regressions to slip into production.
- **Decision:** Enforce two complementary, mandatory test tracks:
  1. **Deterministic Suite (`pytest`, `Vitest`, `ruff`, `mypy`/`tsc`)**: Tests all domain rules, adapter mappings, tool error recovery contracts, API endpoints, and React components using deterministic fixtures/fakes.
  2. **Behavioral Evaluation Suite (`agents-cli eval`)**: Evaluates end-to-end ADK agent trajectories, grounding faithfulness, tone/duration adherence, and cross-session memory recall against a versioned golden dataset.
- **Consequences:**
  - *Positive:* Zero flaky unit tests while maintaining measurable, automated quality gates on agent behavior in CI/CD.
  - *Trade-off:* Maintaining golden evaluation datasets is a first-class engineering responsibility alongside unit tests.

---

## ADR-008: Terraform IaC and Google Cloud Secret Manager

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Manual cloud console setup and plaintext API keys in `.env` files cause configuration drift and credential exposure risks.
- **Decision:** Provision all cloud resources (Firestore database and indexes, Cloud Run / Agent Runtime compute, least-privilege service accounts, Secret Manager secrets, telemetry sinks) declaratively via **Terraform** under `infra/terraform/`, and inject all sensitive configuration at runtime via **Google Cloud Secret Manager** and Workload Identity / ADC.
- **Consequences:**
  - *Positive:* Reproducible environments, auditable IAM posture, and zero secrets stored in source control.
  - *Trade-off:* Infrastructure changes follow PR review and `terraform plan` validation in CI.

---

## ADR-009: Root-Level Official ADK Python Scaffold Paired with `web/` SPA and Single-Container Serving

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** `google-agents-cli` (`agents-cli`) expects `agents-cli-manifest.yaml`, `pyproject.toml`, `app/` (`agent.py`, `fast_api_app.py`), and `tests/eval/` at the project root for `agents-cli info`, `playground`, `eval run`, and `scaffold enhance`. Meanwhile, Cloud Run deployments are simplest and avoid cross-origin deployment complexity when a single container serves both `/api/*` + ADK/A2A endpoints and the compiled React SPA.
- **Decision:** Keep the Python/ADK project at the repository root (`app/`, `tests/`), house the React + Vite + TypeScript + Tailwind frontend in `web/`, default the configurable `GEMINI_MODEL` setting to `gemini-3.8-flash`, and build `web/dist` in Stage 1 of a multistage `Dockerfile` served by FastAPI on `$PORT` in Stage 2.
- **Consequences:**
  - *Positive:* Full native compatibility with `agents-cli` commands, zero nested backend subproject indirection, single-command local startup (`uv run brew-dev`), and single-artifact Cloud Run container deployment.
  - *Trade-off:* SPA fallback routing in FastAPI must explicitly preserve `/api/*`, `/apps/*`, `/a2a/*`, and ADK streaming routes (enforced by integration tests).

---

## ADR-010: Domain-Specific Repository Ports, Optimistic Versioning, and Separated Proposal Storage

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Brew's v1 HTTP contract covers contacts, meetings, versioned preparation briefs, and user-consented memories. Concurrent brief revisions or duplicate memory approvals can overwrite state if unchecked, client-supplied `user_id` payloads risk horizontal privilege escalation, and co-mingling proposed and approved memories in one table risks accidental recall of unconsented facts.
- **Decision:**
  1. Model all eight domain entities (`UserPreferences`, `Contact`, `Meeting`, `PreparationBrief`, `ConversationQuestion`, `Memory`, `MemoryProposal`, `MemorySource`) as immutable Pydantic v2 objects enforcing timezone-aware UTC timestamps, validated IDs, text length bounds, and exact time-boxed agenda sums.
  2. Define aggregate-specific `typing.Protocol` repository and agent ports (`ContactRepository`, `MeetingRepository`, `BriefRepository`, `MemoryProposalRepository`, `MemoryRepository`, `UserPreferencesRepository`, `BriefCoachAgentPort`, `MemoryProposalAgentPort`)—explicitly avoiding generic `Repository[T]` frameworks.
  3. Store `MemoryProposal` records strictly inside `MemoryProposalRepository`, promoting items into `MemoryRepository` only through `POST /api/v1/memories/{id}/approve`.
  4. Resolve caller identity exclusively from Bearer authentication (`AuthenticatorPort`) while setting `extra="forbid"` on all request schemas, and enforce `expected_version` optimistic concurrency checks (`409 VERSION_CONFLICT`) on mutable resources.
- **Consequences:**
  - *Positive:* Unapproved proposals are structurally unreachable by `GET /api/v1/memories` or brief grounding; full HTTP contract and OpenAPI 3.1 specification (`docs/openapi.json`) are deterministically verified using injected in-memory fakes before cloud adapter integration.
  - *Trade-off:* Clients mutating briefs, proposals, or memories must supply `expected_version` to prevent lost updates.

---

## ADR-011: Per-User Async Firestore Hierarchy, Bounded Provenance Retrieval, and Isolated ADK `FirestoreSessionService`

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Brew requires durable multi-tenant storage for preferences, contacts, meetings, briefs, approved memories, and pending proposals alongside persistent ADK conversational session events, without blocking the Python `asyncio` event loop or mixing raw ADK session transcripts into curated domain memory collections.
- **Decision:**
  1. Partition all domain entities under `users/{uid}/{preferences/default | contacts | meetings | briefs | memories | memoryProposals}` via async `firestore.AsyncClient` repositories (`app/infrastructure/firestore_repositories.py`) with `@firestore.async_transactional` optimistic locking, OpenTelemetry spans, and explicit timeouts.
  2. Persist ADK session events via the official `google.adk.integrations.firestore.firestore_session_service.FirestoreSessionService` instantiated through `SessionServiceFactory` (`app/infrastructure/session_service_factory.py`) under an isolated root collection (`adk-session`), validating at startup that session collections never overlap `users/{uid}/...`.
  3. Centralize pre-brief recall in `MemoryRetrievalService` (`app/application/memory_retrieval_service.py`) executing a strict 5-step user-scoped pipeline (preferences, contact profile, recent relevant meetings, approved contact memories, and bounded `BriefPreparationContext` with provenance) paired with `MemoryPersistenceService` (`app/application/memory_persistence_service.py`).
- **Consequences:**
  - *Positive:* End-to-end non-blocking async I/O; physical per-user document isolation verified against the Cloud Firestore Emulator (`tests/integration/test_firestore_persistence.py`); bounded prompt context with full `MemorySource` provenance.
  - *Trade-off:* Integration tests exercising real Firestore transactions and session events require a running Cloud Firestore Emulator.

---

## ADR-012: Least-Privilege `conversation_coach` ADK Tools, Caller-ID Isolation, and Untrusted-Note Sanitization

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Exposing persistence-backed tools (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`) to an LLM introduces three security risks: (1) horizontal privilege escalation if the model can specify or override `user_id` in tool parameters, (2) accidental or adversarial mutation/deletion of durable records if tools hold full repository objects, and (3) indirect prompt injection embedded inside saved meeting notes or contact notes steering subsequent tool calls or responses.
- **Decision:**
  1. Resolve authenticated caller identity exclusively from `ToolContext.user_id` (`resolve_authenticated_principal` in `app/tools/coaching_tools.py`), omitting all user-identity fields from tool schemas and blocking any injected identity keys at the runner level in `ConversationCoachGuardrailPlugin` (`IDENTITY_OVERRIDE_FORBIDDEN`).
  2. Wrap injected repositories in capability-restricted facades (`ReadOnlyPreferencesFacade`, `ReadOnlyContactFacade`, `ReadOnlyMeetingFacade`, `ReadOnlyApprovedMemoryFacade`, `PendingProposalOnlyFacade` in `app/application/coaching_service.py`) so `conversation_coach` cannot write/delete contacts, meetings, preferences, or approved memories, and `suggest_memory_candidates` can only insert `PENDING` proposals.
  3. Run deterministic PII scrubbing and prompt-injection clause neutralization (`app/application/untrusted_data.py`) across all retrieved notes/memories and candidate extractions, tag tool outputs with `data_trust_level="untrusted_user_data"`, and append untrusted-data boundary reminders in `ConversationCoachGuardrailPlugin.before_model_callback`.
- **Consequences:**
  - *Positive:* Defense-in-depth isolation against cross-user lookups, caller-ID spoofing, silent memory promotion, and stored prompt injection inside meeting notes—all deterministically verified in `tests/unit/test_conversation_coach.py`.
  - *Trade-off:* Every new coaching tool must define explicit Pydantic input/output contracts, narrow port facades, and `TypedDict` return annotations compatible with Vertex AI JSON schemas.

