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
- **Status:** Accepted. Implemented on 2026-11-25 as described in ADR-021, which records the actual models and routes.
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
- **Status:** Accepted. Implemented on 2026-11-25 as described in ADR-022, which records the actual API and its limits.
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
  1. Partition all domain entities under `users/{uid}/{preferences/default | contacts | meetings | briefs | memories | memoryProposals}` via async `firestore.AsyncClient` repositories (`app/infrastructure/firestore/`) with `@firestore.async_transactional` optimistic locking, OpenTelemetry spans, and explicit timeouts.
  2. Persist ADK session events via the official `google.adk.integrations.firestore.firestore_session_service.FirestoreSessionService` instantiated through `SessionServiceFactory` (`app/infrastructure/sessions.py`) under an isolated root collection (`adk-session`), validating at startup that session collections never overlap `users/{uid}/...`.
  3. Centralize pre-brief recall in `MemoryRetrievalService` (`app/application/memory/retrieval.py`) executing a strict 5-step user-scoped pipeline (preferences, contact profile, recent relevant meetings, approved contact memories, and bounded `BriefPreparationContext` with provenance) paired with `MemoryPersistenceService` (`app/application/memory/persistence.py`). *Amended by ADR-025: pre-brief context is now assembled only by `ResilientBriefContextAssembler`.*
- **Consequences:**
  - *Positive:* End-to-end non-blocking async I/O; physical per-user document isolation verified against the Cloud Firestore Emulator (`tests/integration/test_firestore_persistence.py`); bounded prompt context with full `MemorySource` provenance.
  - *Trade-off:* Integration tests exercising real Firestore transactions and session events require a running Cloud Firestore Emulator.

---

## ADR-012: Least-Privilege `conversation_coach` ADK Tools, Caller-ID Isolation, and Untrusted-Note Sanitization

- **Date:** 2026-11-22
- **Status:** Accepted
- **Context:** Exposing persistence-backed tools (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`) to an LLM introduces three security risks: (1) horizontal privilege escalation if the model can specify or override `user_id` in tool parameters, (2) accidental or adversarial mutation/deletion of durable records if tools hold full repository objects, and (3) indirect prompt injection embedded inside saved meeting notes or contact notes steering subsequent tool calls or responses.
- **Decision:**
  1. Resolve authenticated caller identity exclusively from `ToolContext.user_id` (`resolve_authenticated_principal` in `app/agents/tools/registry.py`), omitting all user-identity fields from tool schemas and blocking any injected identity keys at the runner level in `ConversationCoachGuardrailPlugin` (`IDENTITY_OVERRIDE_FORBIDDEN`).
  2. Wrap injected repositories in capability-restricted facades (`ReadOnlyPreferencesFacade`, `ReadOnlyContactFacade`, `ReadOnlyMeetingFacade`, `ReadOnlyApprovedMemoryFacade`, `PendingProposalOnlyFacade` in `app/application/coaching/queries.py`) so `conversation_coach` cannot write/delete contacts, meetings, preferences, or approved memories, and `suggest_memory_candidates` can only insert `PENDING` proposals.
  3. Run deterministic PII scrubbing and prompt-injection clause neutralization (`app/application/safety/`) across all retrieved notes/memories and candidate extractions, tag tool outputs with `data_trust_level="untrusted_user_data"`, and append untrusted-data boundary reminders in `ConversationCoachGuardrailPlugin.before_model_callback`.
- **Consequences:**
  - *Positive:* Defense-in-depth isolation against cross-user lookups, caller-ID spoofing, silent memory promotion, and stored prompt injection inside meeting notes—all deterministically verified in `tests/unit/test_conversation_coach.py`.
  - *Trade-off:* Every new coaching tool must define explicit Pydantic input/output contracts, narrow port facades, and `TypedDict` return annotations compatible with Vertex AI JSON schemas.

---

## ADR-013: Bounded 9-Step Meeting Preparation Workflow, Single Corrective Regeneration, and Immutable Brief Revisions

- **Date:** 2026-11-23
- **Status:** Accepted
- **Context:** End-to-end brief synthesis and conversational refinement must ground outputs in user preferences and approved memories, enforce strict quality invariants (2-3 openers, 5-8 non-redundant questions, realistic time-boxed agenda, goal-linked rationales, zero unsupported biographical claims), support natural-language refinement without losing prior revisions, and guard against unbounded critique loops, runaway tool retries, model timeouts, and duplicate submissions.
- **Decision:**
  1. Implement `MeetingPreparationWorkflow` (`app/application/briefs/`) executing a deterministic 9-step pipeline over `AdkConversationCoachBriefAdapter` (`app/agents/brief_specialists.py`), which runs Brew's ADK `conversation_coach` agent with read-only coaching tools (`get_user_preferences`, `get_contact_context`, `get_meeting_history`), `ConversationCoachGuardrailPlugin`, and `WorkflowSafeguardPlugin` (`app/agents/plugins/workflow_safeguards.py`).
  2. Validate candidate briefs through strict Pydantic schemas (`GeneratedBriefContent`) plus pure domain checks (`evaluate_brief_quality` in `app/domain/briefs/quality/`), permitting **at most one** corrective regeneration (`max_corrective_regenerations = 1`) and classifying `ModelTimeoutError` (HTTP 504), `ModelExecutionError` (HTTP 502), and `ModelOutputValidationError` (HTTP 422) into distinct domain errors and explicit `BriefWorkflowTerminalState` values.
  3. Propagate unified `request_id` and `trace_id` via `WorkflowCorrelation` (`app/application/shared/correlation.py`) across HTTP handlers, workflow logs, OpenTelemetry spans, and ADK plugins; deduplicate repeated submissions via `WorkflowIdempotencyRepository`; and archive immutable revision snapshots (`v1`, `v2`, ...) on every `BriefRepository.save` transaction.
- **Consequences:**
  - *Positive:* Predictable upper bounds on LLM calls and tool retries per request, zero silent revision overwrites, graceful degradation when optional enrichment tools fail, and deterministic table-driven testability with `DeterministicMockCoachLlm` (`tests/unit/test_meeting_preparation_workflow.py`).
  - *Trade-off:* Unrecoverable model schema/quality failures fail closed after at most two synthesis attempts rather than retrying indefinitely.

---

## ADR-014: Five-State Long-Term Memory Lifecycle, Epistemic Attribution, Contradiction Supersession, and Tombstone Deletion

- **Date:** 2026-11-23
- **Status:** Accepted
- **Context:** Long-term relationship coaching requires extracting counterpart takeaways and user communication preferences from free-form post-meeting notes without (1) treating subjective session notes as verified objective facts about the wider world, (2) silently committing memories via agent callbacks, (3) memorizing sensitive personal or third-party rumors, (4) accumulating duplicate or contradictory memories over time, or (5) leaving deleted memories retrievable in future sessions while losing audit provenance.
- **Decision:**
  1. Model an explicit 5-state lifecycle (`MemoryLifecycleState`: `proposed`, `approved`, `rejected`, `superseded`, `deleted`) paired with `MemoryEpistemicStatus` (`user_reported_observation`, `user_stated_preference`) in `app/domain/memory/types.py`, `app/domain/memory/models.py`, and `app/domain/memory/`.
  2. Implement Gemini-backed extraction in `AdkMemoryProposalAdapter` (`app/agents/memory_extractor.py`) running ADK `Agent(name="memory_candidate_extractor", tools=[])` with zero repository handles and zero automatic write callbacks; enforce deterministic PII redaction, sensitive third-party assumption filtering (`detect_sensitive_or_third_party_assumption`), epistemic attribution (`ensure_attributed_epistemic_text`), semantic deduplication, and contradiction detection (`classify_candidate_against_existing`) inside `MemoryPersistenceService` (`app/application/memory/persistence.py`).
  3. Expose full human review endpoints (`POST /api/v1/memories/propose`, `GET /api/v1/memories/proposals`, `POST /api/v1/memories/{id}/approve`, `POST /api/v1/memories/{id}/reject`, `GET /api/v1/memories`, `PATCH /api/v1/memories/{id}`, `DELETE /api/v1/memories/{id}`). Approving a contradicting/updating proposal atomically marks the prior active memory `superseded` (`superseded_by_memory_id`, `superseded_at`); rejecting keeps the proposal in `memoryProposals` (`rejected`) with zero writes to `memories`; deleting executes an atomic transaction removing the document from `users/{uid}/memories/{id}` while writing a `deleted` audit tombstone to `users/{uid}/deletedMemories/{id}`.
- **Consequences:**
  - *Positive:* Strict human-in-the-loop memory governance, preserved meeting/note provenance and timestamps across all 5 states, automatic exclusion of rejected/superseded/deleted memories from future session retrieval, and end-to-end verification across two distinct Firestore-persisted ADK sessions (`tests/unit/test_memory_lifecycle.py` and `tests/integration/test_firestore_persistence.py`).
  - *Trade-off:* Maintaining immutable `deletedMemories` tombstones adds one subcollection write per deletion transaction in exchange for complete lifecycle provenance and verifiable non-retrieval from `users/{uid}/memories`.
- **Amendment (2026-11-25):** Two rules were tightened after code review:
  1. Approval supersedes only a memory the user was shown as the target: the `supersedes_memory_id` staged on the proposal at review time, or the one named in the approval request. A contradiction the classifier detects only at approval time is no longer applied, so both memories stay active and the user resolves it. Previously a one-word overlap with an opposing word could archive an unrelated approved memory.
  2. A candidate that repeats an active memory with a different figure (for example "12 engineers" and "40 engineers") is classified as an update for review, not a duplicate to skip.

---

## ADR-015: Responsive Material Design 3 SPA, Verified Firebase/Google Authentication, and Deployment Mock Lockout

- **Date:** 2026-11-23
- **Status:** Accepted
- **Context:** Brew's browser experience requires a cohesive Material Design interface in a warm cream and soft espresso palette across desktop and mobile viewports, strict 1:1 alignment with existing OpenAPI v1 contracts, same-origin API execution when deployed, zero credentials stored in frontend source code, automatic token-expiry / `401` session recovery, and verified Google/Firebase authentication in deployed environments while preserving isolated local test personas during offline development.
- **Decision:**
  1. Implement `FirebaseGoogleTokenAuthenticator` and `RuntimeAuthenticator` (`app/infrastructure/identity/`), verifying Firebase ID tokens (`verify_firebase_token`) and Google OIDC ID tokens (`verify_oauth2_token`) with bounded network timeouts, mapping expired tokens to HTTP `401` (`TOKEN_EXPIRED`), exposing non-secret client auth bootstrap metadata via `GET /api/auth/config` and caller verification via `GET /api/v1/auth/me`, and enforcing a hard startup/runtime lockout (`MOCK_AUTH_DISABLED`) blocking local mock sessions in `staging`, `production`, and Cloud Run (`K_SERVICE`).
  2. Build the React 19 + Vite + TypeScript + Tailwind v4 SPA (`web/src/`) using Material Design 3 tokens (`#FAF6F0` warm cream surfaces, `#4A2E1B` soft espresso primary, WCAG AA+ contrast), desktop persistent navigation rail + mobile sticky app bar & 4-tab bottom navigation bar, 1:1 OpenAPI interfaces (`web/src/api/types.ts`), and `BrewApiClient` (`web/src/api/client.ts`) with same-origin `/api/*` paths, `AbortController` deadlines, `Idempotency-Key` headers, silent Firebase refresh when available, and automatic `401` / `TOKEN_EXPIRED` sign-out recovery.
- **Consequences:**
  - *Positive:* Zero secrets or developer tokens in `web/src/`, impossible to accidentally enable mock identities in production, full keyboard/screen-reader accessibility (`0` axe/a11y violations), and deterministic coverage via `tests/unit/test_auth_security.py`, `Vitest` + React Testing Library (`web/src/App.test.tsx`), and live headless Chrome desktop/mobile verification.
  - *Trade-off:* Browser Google Sign-In requires `GOOGLE_OAUTH_CLIENT_ID` (and optional `FIREBASE_PROJECT_ID` / `FIREBASE_WEB_API_KEY`) environment variables injected at deployment time.

---

## ADR-016: Four-Layer Test Pyramid & 120-Scenario ADK / `agents-cli eval` Harness

- **Date:** 2026-11-23
- **Status:** Accepted
- **Context:** Evaluating an agentic relationship coach requires separating deterministic software invariants (schemas, PII redaction ordering, optimistic locking, per-user authorization boundaries, Firestore session persistence, and UI state transitions) from non-deterministic LLM coaching quality across diverse interpersonal archetypes, conflicting memories, prompt-injection attacks, and downstream tool failures.
- **Decision:**
  1. Enforce deterministic unit (`tests/unit/`) and integration (`tests/integration/`) suites covering all 5 ADK tool schemas, exception translations, `ConversationCoachGuardrailPlugin` / `WorkflowSafeguardPlugin` caps, 13 `/api/v1/*` OpenAPI contracts, cross-tenant `401`/`403`/`422` authorization bounds (`test_authorization_boundaries.py`), and multi-turn ADK `FirestoreSessionService` persistence on the live Cloud Firestore Emulator (`test_firestore_persistence.py`), paired with 11 Vitest + React Testing Library user-journey, loading/error, memory governance, and revision tests (`web/src/App.test.tsx`, `web/src/TestPyramidJourneys.test.tsx`).
  2. Author a canonical **120-scenario** `EvaluationDataset` (`tests/eval/datasets/brew-comprehensive-dataset.json`, 8 scenarios x 15 categories, mixing single-turn Shape A `prompt` and multi-turn Shape B `agent_data.turns` continuation cases) plus a 15-scenario stratified subset (`brew-stratified-smoke-dataset.json`), backed by isolated non-production evaluation fixtures and simulated `TIMEOUT`/`SERVICE_UNAVAILABLE`/`FORBIDDEN` repository wrappers (`app/infrastructure/stubs/eval_fixtures.py`, hard-blocked in staging/production/Cloud Run via `AppSettings`).
  3. Grade traces through `agents-cli eval` (`tests/eval/eval_config.yaml` and `tests/eval/run_eval_suite.py`) combining self-contained deterministic `CodeExecutionMetric`s (`guardrail_compliance.py`, `trajectory_contract.py`) with thread-safe Gemini LLM-as-judge evaluators (`brew_coaching_judge.py`, `response_quality.py`).
- **Consequences:**
  - *Positive:* Zero brittle raw-LLM-prose assertions in `pytest`, fast (<15s) offline deterministic trajectory/guardrail verification across all 120 scenarios, and reproducible live Gemini rubric scoring via `make eval-smoke` and `make eval`.
  - *Trade-off:* `custom_function_file` evaluators executed by `agents-cli eval grade` run in isolated `exec()` module namespaces and therefore remain self-contained stdlib/`google-genai` modules without relative package imports.

---

## ADR-017: Playful Social Club Pastel Editorial Design System, Filled-Vector SVG Illustration Family, and 5-Tab + Focused-Flow Shell

- **Date:** 2026-11-23
- **Status:** Accepted *(supersedes the visual palette and navigation chrome of ADR-015 while retaining all verified Google/Firebase authentication, `BrewApiClient`, and deployment lockout guarantees)*
- **Context:** Brew is a warm, human-centered AI relationship and conversation preparation companion—not a cafe ordering app or a generic enterprise dashboard. The UI needed a cohesive pastel editorial identity ("Playful Social Club"), custom character illustrations from a single visual family, a mobile-first 5-tab browsing shell (`Home`, `Chats`, `People`, `Memory`, `Me`) that scales up to `1200px` desktop side-by-side layouts without looking like a stretched mobile screenshot, and focused creation flows where bottom navigation never competes with primary call-to-action buttons.
- **Decision:**
  1. Centralize all color, gradient, ambient shadow, radius, spacing, and typography tokens (`Fraunces` bold headlines + `DM Sans` UI and `"brew."` wordmark with `#EF8B70` coral dot) in `web/src/index.css` via `:root` CSS custom properties and Tailwind v4 `@theme` variables, documented in [`docs/DESIGN.md`](DESIGN.md) and enforced via `AGENTS.md`.
  2. Generate the primary `chat-setup-hero.png` asset via Gemini image generation (`gemini-2.5-flash-image`) with alpha sticker-cutout transparency (`898×571`), paired with three cohesive filled-path `.svg` companion scenes (`home-club-welcome.svg`, `memory-bloom-journal.svg`, `people-circle-club.svg`) sharing the same character palette, layered peach/lavender/mint circles, and three-dot white speech bubbles.
  3. Build 18 reusable, keyboard-accessible primitives and domain cards (`BrewLogo`, `AppHeader`, `BottomNavigation`, `PastelHero`, `Illustration`, `SectionHeader`, `IconTile`, `PastelCard`, `PillButton`, `PrimaryButton`, `SegmentedChoice`, `FormField`, `ContactAvatar`, `MemoryCard`, `QuestionCard`, `MeetingCard`, `EmptyState`, `LoadingSkeleton`) powering the 5 browsing screens and unmounting `BottomNavigation` in favor of `← Back` during focused creation flows.
- **Consequences:**
  - *Positive:* Distinct, approachable lifestyle-editorial visual identity; zero duplicate navigation buttons in the DOM; crisp side-by-side form + live blueprint previews at desktop widths; and 100% preservation of OpenAPI v1 contracts and auth security.
  - *Trade-off:* All new frontend features must consume tokens and primitives from `web/src/components/ui/` and keep `docs/DESIGN.md` synchronized.

---

## ADR-018: Brew V2 Calendar-Aware 3-Space Architecture, Read-Only GCal / `.ics` Sync, and Pocket Glance Rituals

- **Date:** 2026-11-24
- **Status:** Accepted *(evolves ADR-017's 5-tab shell into the approved v2 3-space + focused-ritual UX while preserving 100% of FastAPI v1 contracts)*
- **Context:** While ADR-017 established Brew's Playful Social Club visual language, splitting interpersonal preparation across 5 equal tabs (`Home`, `Chats`, `People`, `Memory`, `Me`) separated people from their memories and lacked calendar-aware coffee chat detection, proportional time-boxing (`15m` vs `30m` vs `45m`), and a distraction-free mobile deck during live conversations.
- **Decision:**
  1. Collapse primary browsing into **3 cohesive spaces** (`Clubhouse`, `Cue Studio`, `Relationship Journal`) via `TopBarShell` and `MobileDock`, paired with **3 focused rituals** (`QuickSparkSetupScreen`, `PocketCueCardsScreen`, `DebriefKeepsakesScreen`) rendered inside `FocusedTopBar` with primary navigation unmounted.
  2. Implement client-side read-only Google Calendar sync (`https://www.googleapis.com/auth/calendar.events.readonly` via GIS token client in `web/src/calendar/googleCalendarClient.ts`) alongside an RFC 5545 `.ics` parser (`web/src/calendar/icsParser.ts`) and deterministic local mock fixtures (`web/src/calendar/calendarStore.ts`), filtering strictly for explicit coffee/mentorship/1:1/discovery events `<= 180` minutes with at most 2 human attendees (excluding group/team meetings and >2 human attendees unless `#brew` is explicitly present) and displaying concise `from GCal` attribution badges.
  3. Persist Pocket Glance starred cue-card IDs per `(userId, briefId)` and default coaching preferences per `userId` in `localStorage` (`web/src/state/`), keeping `/api/v1/*` backend schemas completely unchanged while eliminating all 10 obsolete v1 screen/shell/card files.
  4. Enforce visual fidelity, responsive layout integrity (`1440px`, `834px`, `430px`), zero em-dashes, and live Chrome WCAG 2.1 AA contrast (`--brew-text-secondary: #6F5E6A`) through Vitest + `@playwright/test` + `@axe-core/playwright` (`web/e2e/`) and automated side-by-side mockup comparisons (`tests/visual/`).
- **Consequences:**
  - *Positive:* One-click preparation from calendar slots, calm 2-card Pocket Glance during live chats, unified counterpart + keepsake folios, zero backend breaking changes, and `93.7%` to `96.4%` desktop visual similarity against approved v2 mockups.
  - *Trade-off:* Client-side starred question selections and imported `.ics` events are scoped to browser `localStorage` per user rather than synced across devices via Firestore.

---

## ADR-019: Production OpenTelemetry + Google Cloud Trace Hierarchy, Non-Duplicating ADK Enrichment, and Telemetry Privacy Lockdown

- **Date:** 2026-11-24
- **Status:** Accepted
- **Context:** Production troubleshooting across multi-step agentic preparation workflows requires correlated end-to-end traces (HTTP request -> workflow -> context/memory retrieval -> ADK agent -> tool calls -> Gemini calls -> output validation -> optional corrective regeneration -> Firestore persistence) and Cloud Logging trace-linked JSON logs, without duplicating spans already emitted by `google-adk` or leaking raw contact notes, private biographies, credentials, or prompts into telemetry backends.
- **Decision:**
  1. Preserve `get_fast_api_app(..., otel_to_cloud=resolved_settings.otel_enabled)` from the `agents-cli` scaffold while installing an outer HTTP `SpanKind.SERVER` middleware (`app/fast_api_app.py`) extracting W3C `traceparent` and `X-Cloud-Trace-Context` headers, propagating `WorkflowCorrelation`, and returning `X-Request-ID` + `X-Trace-ID`.
  2. Enrich ADK's native `invoke_agent`, `generate_content`, and `execute_tool` spans in place via `ConversationCoachGuardrailPlugin`, `WorkflowSafeguardPlugin`, and `tool_telemetry_scope` (avoiding duplicate custom `coach.tool.*` child spans inside ADK `Runner` turns while explicitly marking operational tool errors `StatusCode.ERROR` with `brew.error.classification`), and add Brew spans for workflow orchestration (`brew.workflow.*`), context/memory retrieval (`brew.context.retrieve`, `brew.memory.retrieve`), validation (`brew.output.validate`), single repair (`brew.workflow.corrective_regeneration`), HITL memory approval (`brew.memory.propose`, `brew.memory.approve`), and Firestore operations (`firestore.*`).
  3. Enforce fail-closed telemetry privacy (`enforce_telemetry_privacy_defaults` and `build_adk_telemetry_config` in `app/infrastructure/observability.py`, plus `FORBIDDEN_TELEMETRY_KEYS` and `scrub_sensitive_telemetry_text` in `app/application/shared/telemetry.py`), defaulting `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`, and stripping `OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK` unless explicitly authorized via `BREW_TELEMETRY_CAPTURE_CONTENT` / `BREW_TELEMETRY_UPLOAD_COMPLETIONS`.
  4. Stamp `logging.googleapis.com/trace`, `logging.googleapis.com/spanId`, `logging.googleapis.com/trace_sampled`, `trace_id`, `span_id`, and typed error classifications onto structured JSON logs via `TraceContextLogFilter` + `StructuredJsonFormatter`, documented in [`docs/OBSERVABILITY.md`](OBSERVABILITY.md) and verified in `tests/unit/test_observability_tracing.py`.
- **Consequences:**
  - *Positive:* Complete single-trace waterfall visibility in Google Cloud Trace, one-click Trace-to-Logs correlation in Cloud Logging, immediate visibility into expensive token usage and recovered tool timeouts, and verifiable zero-leakage privacy defaults.
  - *Trade-off:* Engineers needing full prompt/response inspection during controlled staging audits must explicitly opt in via `BREW_TELEMETRY_CAPTURE_CONTENT=true`.

---

## ADR-020: Minimal-Footprint Private-by-Default Cloud Run Deployment, Keyless WIF CI/CD, and Defense-in-Depth ADK Route Hardening

- **Date:** 2026-11-24
- **Status:** Accepted
- **Context:** Brew requires a production-grade Google Cloud deployment with the smallest reasonable operational and billing footprint, preserving the unified FastAPI + static React SPA + Google ADK `conversation_coach` architecture while enforcing zero service account JSON keys, private-by-default access, authenticated browser sign-in, strict HITL memory governance on every HTTP surface, emulator-backed PR validation, and cost-controlled live-model evaluations.
- **Decision:**
  1. Target a **single Cloud Run service** (`agents-cli-manifest.yaml` `deployment_target: "cloud_run"`, `cicd_runner: "github_actions"`) sized at `1 vCPU`, `1Gi` RAM, concurrency `8`, `min-instances=0` (scale-to-zero), `max-instances=5`, and `120s` timeout, provisioned in dependency order by [`gcloud_setup.sh`](../gcloud_setup.sh) with Native-mode Firestore, all 6 required `COLLECTION_GROUP` field exemptions (`contacts`, `meetings`, `briefs`, `memoryProposals`, `memories` on `id`; `sessions` on `appName`), and composite indexes.
  2. Eliminate all static credentials: runtime uses a dedicated least-privilege `brew-runtime` service account via Cloud Run Application Default Credentials (`roles/aiplatform.user`, `roles/datastore.user`, `roles/logging.logWriter`, `roles/cloudtrace.agent`, `roles/monitoring.metricWriter`, plus secret-level `roles/secretmanager.secretAccessor`); GitHub Actions authenticates exclusively via OIDC Workload Identity Federation (`brew-github-pool` -> `brew-cicd` SA).
  3. Keep Cloud Run **private by default** (`--no-allow-unauthenticated`), support Cloud Run Identity-Aware Proxy (`--iap` + cryptographic `X-Goog-IAP-JWT-Assertion` verification in `app/infrastructure/identity/`, paired with [`iap_setup.sh`](../iap_setup.sh) to bind a dedicated `brew-iap-edge` custom OAuth Web Client separate from `brew-web-spa` in managed GCP organizations enforcing `iam.allowedPolicyMemberDomains` or blocking default unlisted IAP clients) and Google OAuth / Firebase ID tokens for browser users, permanently block ADK's ungoverned `PATCH /apps/{app}/users/{uid}/memory` route (`403 UNGOVERNED_MEMORY_WRITE_DISABLED`), enforce authenticated caller ownership on `/apps/*`, `/run`, `/run_sse`, `/run_live`, and `POST /a2a/*` in deployed mode (`app/fast_api_app.py`), and expose `/readyz` + `/healthz` probes (`app/api/health.py`).
  4. Split GitHub Actions into fast deterministic PR gates including local Cloud Firestore Emulator & container smoke validation (`.github/workflows/ci.yml`), authorized `main` deployment + WIF OIDC smoke verification (`.github/workflows/deploy.yml`), and a manual-only `workflow_dispatch` evaluation job (`.github/workflows/eval-controlled.yml`), documented in [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).
- **Consequences:**
  - *Positive:* Near-zero idle cost (`$0` compute when idle, no VPC/NAT/Cloud SQL/GCLB overhead), zero downloadable JSON keys, defense-in-depth protection even if ingress settings are changed, and deterministic CI gates without unexpected PR LLM spend.
  - *Trade-off:* `min-instances=0` incurs a ~2–4s cold start on the first request after idle periods (operators can set `CLOUD_RUN_MIN_INSTANCES=1` when warm capacity is preferred).

---

## ADR-021: Per-Stage Model Routing and Brief Specialist Agents

- **Date:** 2026-11-25
- **Status:** Accepted
- **Context:** ADR-003 called for routing by task, but every agent used the single `GEMINI_MODEL`, and the brief workflow reused the conversational coach's instruction, which told the model to call a memory-staging tool that the workflow had removed. Initial brief synthesis is the one step that weighs every constraint together (objective, counterpart context, preferences, time budget). Refinement is one targeted edit, and memory extraction is short structured output.
- **Decision:**
  1. Route by stage in one place, [`app/agents/model_routing.py`](../app/agents/model_routing.py). `ModelStage.BRIEF_SYNTHESIS` uses `BREW_SYNTHESIS_MODEL` (default `gemini-4-hydrogen`, chosen by the project owner on 2026-11-25). `BRIEF_REFINEMENT` and `MEMORY_EXTRACTION` use `BREW_REFINEMENT_MODEL` and `BREW_MEMORY_EXTRACTION_MODEL`, each falling back to `GEMINI_MODEL` (default `gemini-3.8-flash`). Conversation and history summarization stay on `GEMINI_MODEL`.
  2. Replace the single workflow agent with two specialists built by `AdkConversationCoachBriefAdapter`: `brief_synthesizer` for generation and `brief_refiner` for revision. Each has its own instruction in [`app/agents/prompts.py`](../app/agents/prompts.py), shares the grounding, security and privacy principles with the coach, keeps the three read-only tools, and is never told about memory staging.
  3. Keep `conversation_coach` unchanged for the raw ADK chat and A2A surface. Its instruction text is preserved byte for byte.
  4. Orchestration stays in the deterministic Python `MeetingPreparationWorkflow`. This is specialist agents behind a deterministic orchestrator, not an ADK `SequentialAgent` or workflow graph.
- **Consequences:**
  - *Positive:* The advanced model is used for at most the initial draft and its single corrective regeneration. Routes are settings, so an environment can change a model without a code change. The prompt and the toolset now agree on the brief path.
  - *Trade-off:* Synthesis now depends on a second model being served in the configured location. `gemini-4-hydrogen` could not be verified from the development environment, and no evaluation has been run on it yet, so the first live call and a smoke eval are required before relying on it. Setting `BREW_SYNTHESIS_MODEL` to the base model restores the previous behaviour.

---

## ADR-022: Background Memory Extraction Jobs

- **Date:** 2026-11-25
- **Status:** Accepted
- **Context:** ADR-004 called for asynchronous extraction, but `POST /api/v1/memories/propose` ran the extraction model inside the request. A slow model held the HTTP request and the debrief screen open.
- **Decision:**
  1. Add `POST /api/v1/memories/extraction-jobs` (202 Accepted with a job) and `GET /api/v1/memories/extraction-jobs/{id}` for polling. Ownership of the referenced contact, meeting and brief is checked before the job is accepted, so 403, 404 and 422 are still returned immediately.
  2. `MemoryExtractionJobService` ([`app/application/memory/jobs.py`](../app/application/memory/jobs.py)) records a job under `users/{uid}/memoryJobs/{jobId}` and hands the model call to a `BackgroundJobRunnerPort`. The job record never stores the notes. A finished job only references `pending` proposals, so human approval is unchanged.
  3. The default runner, `InProcessBackgroundJobRunner`, runs the job as an asyncio task on the serving loop with bounded concurrency (`BREW_MEMORY_JOB_MAX_CONCURRENCY`, default 4) and a short drain at shutdown.
  4. A job that is still `queued` or `running` after `BREW_MEMORY_JOB_STALE_AFTER_SECONDS` (default 300) is closed as `failed` with `MEMORY_EXTRACTION_STALLED` when it is next read, so a client never polls forever after an instance is lost.
  5. The SPA uses the job API. The synchronous `POST /api/v1/memories/propose` stays for compatibility.
- **Consequences:**
  - *Positive:* The request returns in milliseconds, failures are reported on the job with a client-safe code, and the UI is no longer tied to one long request.
  - *Trade-off:* An in-process task is lost if its instance stops, and on Cloud Run with request-based billing (the default when `min-instances=0`) CPU is throttled between requests, so a job only progresses while another request, such as the client's poll, is in flight. Run with `CLOUD_RUN_MIN_INSTANCES=1` or `--no-cpu-throttling` for dependable background work, or replace the runner with a queue such as Cloud Tasks behind the same port. Job records have no TTL yet.

---

## ADR-023: Readiness Fails Closed on Ephemeral Storage in Deployed Environments

- **Date:** 2026-11-25
- **Status:** Accepted
- **Context:** `BREW_PERSISTENCE_BACKEND` defaults to `in_memory`. A staging, production or Cloud Run service started without it accepted writes, reported ready, and lost every contact, brief and memory on restart.
- **Decision:** `/readyz` reports `persistence_ready=false` (HTTP 503) when the environment is deployed and the backend is not Firestore, unless `BREW_ALLOW_EPHEMERAL_PERSISTENCE=true` is set on purpose. The CI container smoke test sets that flag because it boots a production image on in-memory stores.
- **Consequences:**
  - *Positive:* A misconfigured deployment fails its startup probe instead of silently discarding user data.
  - *Trade-off:* Any deliberate in-memory deployment (for example a throwaway demo) must set the flag explicitly.

---

## ADR-024: Backend Packages by Layer and Bounded Context, One Agents Package, Explicit Composition Root

- **Date:** 2026-11-25
- **Status:** Accepted
- **Context:** Four backend modules had grown past 1,000 lines (`brief_workflow.py`, `coaching_tools.py`, `fakes.py`, `firestore_repositories.py`), `domain/models.py` and `domain/ports.py` mixed every entity, ADK code was spread over `app/agent.py`, `app/tools`, `app/plugins` and two `infrastructure/adk_*` adapters, production wiring imported from a module named `fakes`, and private helpers were imported across modules.
- **Decision:**
  1. Keep the four layers and split each by bounded context: `shared`, `identity`, `contacts`, `meetings`, `memory`, `briefs`. A domain context may import only contexts earlier in that order.
  2. Put everything that imports `google.adk` or `google.genai` in `app/agents/` (agents, prompts, model routing, tools, plugins). `app/agent.py` stays as the entry point ADK tooling expects.
  3. Split infrastructure by technology: `firestore/`, `inmemory/`, `stubs/`, `identity/`. Wiring lives in `app/composition/`.
  4. Split the API into `routers/`, `schemas/` and `middleware/` with an app factory. `app/fast_api_app.py` stays as the entry point the server and Dockerfile expect.
  5. Enforce the rules in `tests/unit/test_architecture_boundaries.py`: layer direction, domain context order, one home per framework, stubs wired only by the composition root, no cross-module import of an underscore name, and the retired flat modules must not return.
  6. The change is move-only. `MeetingPreparationWorkflow` and `MemoryPersistenceService` keep their public methods and delegate to one collaborator class per responsibility.
- **Deliberately not done:**
  - The two context assemblers (`application/briefs/context_assembly.py` and `MemoryRetrievalService.build_brief_context`) and the two memory proposal pipelines (`application/coaching/queries.py` and `application/memory/proposals.py`) were not merged. They have drifted, so merging changes behaviour and needs an owner decision. *Done in ADR-025.*
  - `ConversationCoachGuardrailPlugin` was not split, the shared ADK turn runner was not extracted, and the triple tool contract definitions were not collapsed.
  - `BriefWorkflowDiagnostics` sits in `domain/shared/` because `BrewDomainError` carries it. *Moved to `domain/briefs/` in ADR-025.*
- **Consequences:**
  - *Positive:* The largest backend module fell from 1,503 to 630 lines. Import rules are tested instead of described. In-memory adapters and scripted stubs are separate packages, and only the composition root can wire a stub.
  - *Trade-off:* Logger and tracer names derived from module paths changed, so log filters keyed on the old names need updating. Three known cross-layer imports remain and are listed in `docs/ARCHITECTURE.md` section 2. Firestore adapter behaviour after the move is covered only by the emulator tests, which have not run.

---

## ADR-025: One Context Assembler, One Proposal Staging Pipeline, Context-Neutral Error Base

- **Date:** 2026-11-25
- **Status:** Accepted. Amends ADR-011 (decision 3) and closes the first and third items ADR-024 left open.
- **Context:** Two pieces of business logic existed twice and had drifted. Pre-brief context was assembled by the brief workflow and again by `MemoryRetrievalService.build_brief_context`, which only tests called and which skipped the timeouts, degradation handling and text scrubbing of the production copy. Notes were turned into pending proposals by the HTTP path and again by the `suggest_memory_candidates` tool, with different counters, different ownership checks and no telemetry on the tool path. Separately, `BrewDomainError` in the shared domain context named a brief type, which forced `BriefWorkflowDiagnostics` to live in `domain/shared`.
- **Decision:**
  1. Pre-brief context is assembled only by `ResilientBriefContextAssembler` (`app/application/briefs/context_assembly.py`). `MemoryRetrievalService.build_brief_context` is removed. Tests that need a context build it through that assembler (`tests/support/brief_context.py`), and fail if any source degraded.
  2. The staging rules live only in `app/application/memory/candidate_staging.py`: `resolve_proposal_references`, `MemoryCandidateStagingPipeline` and `record_staging_outcome`. The pipeline holds a read-only memory port and a pending-only write port.
  3. Each caller keeps its own reporting policy. The HTTP and background-job path raises `VALIDATION_ERROR` when notes yield no candidate and nothing was withheld as sensitive, and stages every surviving candidate. The tool returns an empty result in that case, so the model can carry on, and stages at most `max_candidates` (default 5) per call.
  4. The pipeline counts each reason separately: duplicates, sensitive items, directive items. The HTTP response and the tool result are unchanged. The tool still reports one number, the sum of directive and sensitive items.
  5. Every path re-checks the owner of a record its adapter returns (`app/application/shared/ownership.py`).
  6. Both paths open the `brew.memory.propose` span and record the same counters, now including `brew.memory.filtered_directive_count`.
  7. `BriefWorkflowDiagnostics`, `BriefWorkflowOperation` and `BriefWorkflowTerminalState` move to `domain/briefs`. `BrewDomainError.workflow_diagnostics` is typed as the shared base model, and `brief_workflow_diagnostics(error)` in `domain/briefs/diagnostics.py` is the typed reader.
- **Behaviour that changed:**
  - Tool path: gains the span and the outcome log event.
  - HTTP path: gains the owner re-check and one span attribute. When every note segment is withheld as sensitive the log message is reworded. The event type is the same.
  - No HTTP contract, tool declaration or agent instruction changed.
- **Consequences:**
  - *Positive:* A change to what may be staged, or to what context a brief sees, is made once. Tests of context now exercise the code production runs.
  - *Trade-off:* The two staging callers still differ on purpose (decision 3), so a reader has to know that the difference is policy and not drift. `tests/unit/test_memory_candidate_staging.py` pins both the shared rules and the intended differences.

---

## ADR-026: User-Configurable Custom Display Name Persisted in `UserPreferences`

- **Date:** 2026-11-25
- **Status:** Accepted
- **Context:** Authenticated users previously had to use the default `name` (or email local-part) claim extracted from their Google OAuth / Firebase / IAP token across the Clubhouse header, avatar, Relationship Journal folio, and calendar invite matching. Users often go by a preferred first name or nickname in coffee chats rather than their formal Google corporate directory name.
- **Decision:**
  1. Persist an optional `preferred_display_name: ShortLabelText | None` on `UserPreferences` (`users/{uid}/preferences/default`), enforcing PII scrubbing, prompt-injection rejection, em-dash normalization, and optimistic version checks via `MemoryMaintenance.update_preferred_display_name`.
  2. Expose `PATCH /api/v1/auth/me` (`UpdateAuthenticatedProfileRequest`) alongside `GET /api/v1/auth/me`, returning `display_name` (the effective name), `custom_display_name` (when overridden), and `account_display_name` (the underlying identity-provider name so users can reset cleanly with `{"display_name": null}`). If reading preferences degrades during `GET /api/v1/auth/me`, fall back gracefully to the token's `display_name`.
  3. Match both `display_name` and `account_display_name` as self-identifiers during Google Calendar and `.ics` counterpart parsing so invites titled with the user's Google account name still identify the counterpart after a custom Brew name is set.
- **Consequences:**
  - *Positive:* Custom display names persist across sessions and devices in Firestore without introducing a new collection, preserve full backwards compatibility with existing `UserPreferences` documents, and allow one-click reversion to the Google account name.
  - *Trade-off:* `GET /api/v1/auth/me` performs one bounded per-user preference lookup (`users/{uid}/preferences/default`) to resolve any custom override.
