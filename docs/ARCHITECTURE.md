# System Architecture — Brew

**Status:** Baseline Architecture v1.0  
**Last Updated:** 2026-11-22

---

## 1. Architectural Goals & Principles

Brew is engineered around clean, explicit dependency boundaries so domain behavior remains easy to reason about, fast to unit-test, and resilient to SDK or infrastructure evolution:

1. **Domain Independence (Ports & Adapters)**: Core domain entities, value objects, invariants, and repository/service protocols (`domain/`) have **zero imports** from `google.adk`, `google.cloud.firestore`, `fastapi`, or `google.genai`.
2. **High Cohesion, Low Coupling**: Each module owns a single, well-defined responsibility—prep brief domain rules, ADK orchestration workflows, Firestore persistence adapters, and HTTP transport live in separate layers connected via typed interfaces.
3. **Explicit Dependency Injection**: External collaborators (repositories, ADK runner, PII redactor, secret provider, clock, tracer) are wired at integration boundaries (`api/dependencies.py` and CLI entrypoints), never instantiated as hidden module-level singletons inside business logic.
4. **Fail-Safe External Boundaries**: All calls to Gemini, Firestore, Secret Manager, and redaction services enforce explicit timeouts, structured error translation, and graceful degradation.

---

## 2. Layered Dependency Rules

```mermaid
flowchart TB
    subgraph Client["Frontend SPA (React + Vite + TS + Tailwind)"]
        UI["Prep Wizard, Refinement Chat, Notes & Memory Review UI"]
    end

    subgraph Transport["API Layer (FastAPI + Pydantic)"]
        Routes["REST / SSE Endpoints & Request Validation"]
        DI["Dependency Wiring (api/dependencies.py)"]
    end

    subgraph AppLayer["Application & Orchestration Layer"]
        UseCases["Application Services / Use Cases"]
        ADKAgents["ADK 2.x Workflows, Specialist Agents, Tools & Guardrail Plugins"]
    end

    subgraph Core["Domain Layer (Pure Python 3.12)"]
        Entities["Entities & Value Objects (Meeting, Counterpart, Brief, Memory)"]
        Ports["Typed Protocols / Ports (Repositories, MemoryExtractor, PiiRedactor)"]
        Errors["Structured Domain Errors"]
    end

    subgraph Infra["Infrastructure Layer (Adapters)"]
        FirestoreRepo["Firestore Repositories"]
        GeminiModels["Gemini / Vertex AI Model Routing Config"]
        Security["PII Redaction Adapter & Secret Manager Loader"]
        Telemetry["OpenTelemetry + Cloud Trace + JSON Logger"]
    end

    UI -->|HTTPS JSON| Routes
    Routes --> DI
    Routes --> UseCases
    UseCases --> Core
    UseCases --> ADKAgents
    ADKAgents --> Ports
    Infra -.->|Implements| Ports
    DI -->|Injects| Infra
```

**Strict Import Matrix:**

| Source Package | Allowed Internal Imports | Forbidden Imports |
| :--- | :--- | :--- |
| `app.domain` | Python stdlib, `pydantic` (pure value/schema types only) | `fastapi`, `google.adk`, `google.cloud.*`, `app.api`, `app.agent`, `app.tools`, `app.plugins`, `app.infrastructure` |
| `app.application` | `app.domain` | `fastapi`, `google.adk`, `google.cloud.*`, `app.api`, `app.agent`, `app.tools`, `app.plugins`, `app.infrastructure` |
| `app.tools` / `app.plugins` / `app.agent` | `app.domain`, `app.application`, `app.config`, `google.adk`, `google.genai`, `opentelemetry.*`, `pydantic` | `fastapi`, direct `google.cloud.*` client calls (tools invoke capability-restricted ports) |
| `app.infrastructure` | `app.domain`, `app.application`, `app.agent`, `app.tools`, `app.plugins`, `app.config`, `google.adk`, `google.genai`, `google.cloud.*`, `opentelemetry.*` | `fastapi` (`app/infrastructure/adk_brief_coach.py` additionally forbids `google.cloud.*`) |
| `app.api` / `app.fast_api_app` | `app.domain`, `app.application`, `app.agent`, `app.tools`, `app.plugins`, `app.infrastructure`, `app.config`, `fastapi` | None (composition root) |

---

## 3. Repository Layout

Brew keeps the project directly at the repository root (preserving `agents-cli-manifest.yaml` compatibility) with the React frontend in `web/`:

```text
brew/
├── AGENTS.md                        # Permanent engineering rules & working agreement
├── .agents/skills/                  # Project-scoped agent skills (e.g., generate-illustration)
├── agents-cli-manifest.yaml         # Official google-agents-cli project manifest
├── pyproject.toml                   # Python 3.12, uv, ruff, strict mypy, pytest config
├── uv.lock                          # Locked Python dependency graph
├── Dockerfile                       # Multistage Node 22 + Python 3.12 Cloud Run image ($PORT)
├── Makefile                         # Developer task shortcuts (make dev, make check, etc.)
├── .env.example                     # Safe placeholder environment variables
├── .editorconfig                    # Workspace formatting rules
├── docs/
│   ├── PRD.md                       # Product scope, user journey, non-goals
│   ├── ARCHITECTURE.md              # System architecture & boundaries
│   ├── DESIGN.md                    # Playful Social Club design tokens, components, & SVG art direction
│   ├── OBSERVABILITY.md             # OpenTelemetry, Cloud Trace, privacy, & log correlation runbooks
│   ├── DECISIONS.md                 # Architectural Decision Records (ADRs)
│   └── openapi.json                 # Generated OpenAPI 3.1 HTTP API contract
├── app/
│   ├── config.py                    # Validated AppSettings (default model: gemini-3.8-flash)
│   ├── agent.py                     # Root ADK agent & App registration
│   ├── fast_api_app.py              # FastAPI + ADK + A2A + OTel + SPA static serving
│   ├── server.py                    # Production uvicorn entrypoint honoring $PORT
│   ├── dev_runner.py                # Single-command local launcher (API + Vite)
│   ├── app_utils/                   # Scaffolded ADK shared session/artifact & A2A helpers
│   ├── domain/                      # Pure Pydantic v2 entities, UTC types, ports, domain errors
│   ├── application/                 # Use-case services (Contact, Meeting, Brief, Memory)
│   ├── tools/                       # Typed ADK tools with guided error recovery
│   ├── infrastructure/              # Clocks, JSON logging, OTel, injected fake adapters
│   └── api/                         # FastAPI v1 routes, schemas, auth DI, error handlers, OpenAPI
├── tests/
│   ├── unit/                        # Fast isolated unit & architectural boundary tests
│   ├── integration/                 # Deterministic FastAPI, A2A card, & SPA serving tests
│   └── eval/                        # google-agents-cli evaluation config, judge, & datasets
└── web/
    ├── package.json                 # React 19, Vite, strict TypeScript, Tailwind CSS v4, Lucide, Vitest
    ├── package-lock.json            # Locked frontend dependency graph
    └── src/
        ├── index.css                # Centralized Playful Social Club CSS variables & Tailwind @theme tokens
        ├── assets/illustrations/    # Cohesive flat-vector character illustrations (chat-setup-hero.png + companion SVGs)
        ├── api/                     # 1:1 OpenAPI types & same-origin BrewApiClient with timeouts
        ├── auth/                    # Session storage, expiry detection, & Firebase/Google OIDC
        ├── components/
        │   ├── ui/                  # 15 reusable accessible UI primitives (BrewLogo, AppHeader, BottomNavigation, etc.)
        │   ├── domain/              # Domain cards (MeetingCard, QuestionCard, MemoryCard)
        │   └── screens/             # 5 responsive main screens (Home, Chats, People, Memory, Me)
        ├── test/                    # Vitest + React Testing Library setup
        ├── App.tsx                  # Shared shell, 5-tab BottomNavigation, & focused creation flows
        ├── App.test.tsx             # End-to-end UX, validation, API error, & auth expiry tests
        ├── DesignSystemAndShell.test.tsx # Wordmark, SVG illustration, focused flow, & profile default tests
        └── TestPyramidJourneys.test.tsx  # Multi-counterpart, timeout, memory governance, & revision tests
```

---

## 4. ADK 2.x Multi-Agent & Workflow Architecture

Rather than using a monolithic single-agent prompt, Brew decomposes agentic responsibilities across specialized ADK 2.x components with **strategic model routing**, **explicit JSON schemas**, **runner-wide safety plugins**, and **Human-in-the-Loop memory approval**.

### 4.1 Agent Roster & Model Routing

| Agent / Node | ADK Pattern | Model Tier | Responsibility |
| :--- | :--- | :--- | :--- |
| `BrewCoordinatorWorkflow` | ADK 2.x `Workflow` / Coordinator | Deterministic router + stage edges | Routes session actions (`generate_brief`, `refine_brief`, `extract_memories`) across validated typed state. |
| `ContextAssemblerNode` | Function / Tool stage | Deterministic + Firestore Port | Executes `retrieve_counterpart_memories` and `retrieve_user_preferences`, applying token budget & history compaction before LLM invocation. |
| `BriefSynthesizerAgent` | `LlmAgent` (`output_schema=PreparationBriefSchema`) | **Gemini Pro** | High-reasoning initial synthesis combining counterpart profile, purpose/duration/tone constraints, and prior approved memories into a structured time-boxed brief. |
| `BriefRefinerAgent` | `LlmAgent` (`output_schema=PreparationBriefSchema`) | **Gemini Flash** | Low-latency conversational refinement updating targeted sections of the current brief while preserving invariants. |
| `MemoryExtractorAgent` (`memory_candidate_extractor`) | ADK `Agent` (`AdkMemoryProposalAdapter` in `app/infrastructure/adk_memory_extractor.py`, zero tools / zero DB write handles) | **Configured Gemini Model** | Analyzes PII-scrubbed user meeting notes, preserves epistemic attribution (`user_reported_observation` / `user_stated_preference`) and source excerpts, filters sensitive third-party assumptions, skips duplicates, and tags contradictions (`supersedes_memory_id`) for human review. |
| `BrewGuardrailPlugin` | ADK `BasePlugin` (Runner-wide) | Policy + PII + Audit hooks | Intercepts `before_model`, `after_model`, `before_tool`, and `after_tool` across every sub-agent for PII redaction, prompt-injection defense, and Intent-vs-Outcome structured logging. |

### 4.2 Core Sequence: Preparation, Refinement, Async Memory & HITL Approval

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant SPA as React SPA
    participant API as FastAPI Backend
    participant WF as ADK 2.x Workflow & Guardrail Plugin
    participant Pro as BriefSynthesizer (Gemini Pro)
    participant Flash as Refiner / Extractor (Gemini Flash)
    participant DB as Firestore (via Ports)

    User->>SPA: Create counterpart + enter purpose, duration, tone
    SPA->>API: POST /api/v1/contacts & POST /api/v1/briefs/generate
    API->>DB: Fetch approved counterpart & user preference memories
    API->>WF: Run generate_brief stage (compacted context)
    WF->>Pro: Generate structured brief (strict JSON schema)
    Pro-->>WF: PreparationBrief payload
    WF->>DB: Persist Meeting & PreparationBrief (v1)
    API-->>SPA: 201 Created (PreparationBrief)

    User->>SPA: "Make openers warmer and trim to 20 mins"
    SPA->>API: POST /api/v1/briefs/{id}/revise (expected_version)
    API->>WF: Run refine_brief stage (compacted history + active brief)
    WF->>Flash: Refine brief (Gemini Flash)
    Flash-->>WF: Updated PreparationBrief
    WF->>DB: Save updated brief (v2) with optimistic concurrency check
    API-->>SPA: 200 OK (Updated PreparationBrief)

    User->>SPA: Submit post-meeting notes for memory extraction
    SPA->>API: POST /api/v1/memories/propose
    API->>WF: Scrub PII & extract MemoryProposal candidates
    WF->>Flash: Propose MemoryProposal list
    Flash-->>WF: ProposedMemoryCandidate list
    WF->>DB: Store MemoryProposal items in separate proposal store (status = pending)
    API-->>SPA: 201 Created (MemoryProposalBatchResponse)

    User->>SPA: Review, optionally edit, and approve proposal
    SPA->>API: POST /api/v1/memories/{id}/approve (expected_version)
    API->>DB: Mark proposal approved; create durable Memory in approved store
    API-->>SPA: 200 OK (MemoryResponse)
```

### 4.3 Context Management & History Compaction
- **Sliding Window + Structured Summary Compaction**: During multi-turn natural-language brief refinement, Brew retains the active `PreparationBrief` state plus the most recent $N$ verbatim turns, compacting older refinement turns into a concise `RefinementHistorySummary` once token or turn thresholds are exceeded.
- **Bounded Memory Injection**: When starting a new session, only top-ranked approved memories for the target counterpart and active global user preferences (bounded by a strict token budget) are injected into the prompt context.

### 4.4 Tool Interface, Security Isolation, & Guided Error Contract
Every ADK tool exposed to `conversation_coach` (`app/tools/coaching_tools.py`):
1. Uses a specific action name (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`).
2. Resolves caller identity strictly from `ToolContext.user_id`—no tool schema accepts `user_id` or `owner_user_id`, and `ConversationCoachGuardrailPlugin` (`app/plugins/coach_guardrails.py`) blocks any injected identity-override keys with `IDENTITY_OVERRIDE_FORBIDDEN`.
3. Operates strictly through capability-restricted read/staging facades (`ReadOnlyPreferencesFacade`, `ReadOnlyContactFacade`, `ReadOnlyMeetingFacade`, `ReadOnlyApprovedMemoryFacade`, `PendingProposalOnlyFacade` in `app/application/coaching_service.py`) so the agent never holds unrestricted database write, delete, or approval handles.
4. Enforces `asyncio.wait_for` I/O timeouts, OpenTelemetry spans (`coach.tool.*`), PII redaction, and prompt-injection clause stripping (`app/application/untrusted_data.py`), tagging all returned payloads with `data_trust_level="untrusted_user_data"`.
5. Never raises unhandled operational exceptions into the LLM loop; on recoverable failures (validation error, missing entity, cross-user `FORBIDDEN`, timeout, or backend outage), returns a typed response with `status="error"`, `error.code`, `error.retryable`, and `error.recovery_instruction`.

---

## 5. Domain & Persistence Data Model (Firestore)

All domain Firestore documents are strictly partitioned per authenticated user (`users/{uid}/...`) and mapped to pure Pydantic v2 domain models inside `app/infrastructure/firestore_repositories.py` using non-blocking `firestore.AsyncClient` and `@firestore.async_transactional`:

- **`users/{uid}/preferences/default`**: User coaching defaults (`default_tone`, `default_duration_minutes`, `preferred_question_count`, `communication_style_notes`, `focus_areas`, `version`).
- **`users/{uid}/contacts/{contactId}`**: Counterpart metadata (`name`, `title`, `role`, `organization`, `context_notes`, `version`).
- **`users/{uid}/meetings/{meetingId}`**: Meeting configuration (`contact_id`, `purpose`, `tone`, `objective`, `duration_minutes`, `scheduled_at`, `notes`, `status`, `latest_brief_id`, `version`).
- **`users/{uid}/briefs/{briefId}`**: Versioned `PreparationBrief` entities (`meeting_id`, `contact_id`, `contact_context`, `meeting_objective`, `conversation_openers`, `time_boxed_agenda`, `suggested_questions`, `suggested_follow_up_topics`, `referenced_memory_ids`, `version`), paired with atomic immutable revision snapshots at **`users/{uid}/briefs/{briefId}/revisions/v{version}`** so prior versions are never silently overwritten.
- **`users/{uid}/workflowIdempotency/{operation}:{key}`**: Per-user workflow deduplication records binding `Idempotency-Key` values and canonical payload fingerprints to persisted brief versions.
- **`users/{uid}/memories/{memoryId}`**: Consented, durable `Memory` entities (`scope`, `contact_id`, `memory_type`, `text`, `source` provenance, `consent_status`, `lifecycle_state` in `approved`/`superseded`, `epistemic_status`, `supersedes_memory_id`, `superseded_by_memory_id`, `superseded_at`, `version`). Only active (`lifecycle_state == "approved"`) records participate in prompt/tool recall unless `include_superseded=true` is requested explicitly for audit inspection.
- **`users/{uid}/deletedMemories/{memoryId}`**: Immutable `deleted` lifecycle tombstones (`lifecycle_state="deleted"`, `deleted_at`, preserved `source` provenance and timestamps) written atomically in the same `@firestore.async_transactional` batch that removes the active document from `users/{uid}/memories/{memoryId}`.
- **`users/{uid}/memoryProposals/{proposalId}`**: Separate staged/reviewed `MemoryProposal` entities (`status`, `lifecycle_state` in `proposed`/`approved`/`rejected`, `epistemic_status`, `supersedes_memory_id`, `conflict_summary`, `rejection_reason`, `approved_memory_id`, `source`, `version`) strictly isolated from `memories`.
- **Isolated ADK Session Storage (`adk-session`, `app_states`, `user_states`)**: Managed via the official `google.adk.integrations.firestore.firestore_session_service.FirestoreSessionService` constructed by `SessionServiceFactory` (`app/infrastructure/session_service_factory.py`), strictly separated from `users/{uid}/...` domain collections.

---

## 6. Observability, Tracing, and Privacy Pipeline

See [`docs/OBSERVABILITY.md`](OBSERVABILITY.md) for complete operational runbooks, span hierarchies, Cloud Trace filters, and log correlation queries.

1. **Distributed Tracing (OpenTelemetry + Cloud Trace)**:
   - Incoming HTTP requests extract W3C `traceparent` or Google Cloud `X-Cloud-Trace-Context` headers, open a root `SpanKind.SERVER` span (`{METHOD} {ROUTE}`), and return `X-Request-ID` + `X-Trace-ID` headers.
   - Non-duplicating child spans cover workflow orchestration (`brew.workflow.*`), pre-brief context & memory retrieval (`brew.context.retrieve`, `brew.memory.retrieve`), ADK built-in spans (`invoke_workflow`, `invoke_agent`, `generate_content` with token usage, `execute_tool` enriched with Brew error classifications), deterministic schema/quality validation (`brew.output.validate`), single corrective regeneration (`brew.workflow.corrective_regeneration`), HITL memory approval (`brew.memory.propose`, `brew.memory.approve`), and Firestore operations (`firestore.<collection>.<op>`).
2. **Privacy-by-Default Telemetry Lockdown**:
   - Prompt/response content capture (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`, `TelemetryConfig(capture_message_content=ContentCapturingMode.NO_CONTENT)`) and completion upload hooks (`OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK`) are disabled by default unless explicitly authorized via `BREW_TELEMETRY_CAPTURE_CONTENT=true` / `BREW_TELEMETRY_UPLOAD_COMPLETIONS=true`.
   - `FORBIDDEN_TELEMETRY_KEYS` and `scrub_sensitive_telemetry_text` (`app/application/telemetry.py`) prevent raw contact notes, private biographies, prompts, credentials, JWTs, API keys, emails, SSNs, and phone numbers from entering span attributes or logs.
3. **Structured JSON Logging & Intent-vs-Outcome Capture**:
   - All `app.*` and `google_adk.*` logs emit single-line JSON structured for Cloud Logging (`severity`, `message`, `logging.googleapis.com/trace`, `logging.googleapis.com/spanId`, `logging.googleapis.com/trace_sampled`, `trace_id`, `span_id`, `request_id`, `event_type`, `error_type`, `error_code`, `error_classification`).
   - `ConversationCoachGuardrailPlugin` and `WorkflowSafeguardPlugin` emit paired `*.intent` and `*.outcome` events across agent invocations, Gemini calls (including token counts), and tool calls.

---

## 7. Security, Infrastructure as Code, and CI/CD

- **Secrets Management**: Zero hardcoded API keys or credentials. Runtime configuration resolves secrets exclusively via Google Cloud Secret Manager and Workload Identity / Application Default Credentials (ADC).
- **Infrastructure as Code (`infra/terraform/`)**: Declaratively provisions Firestore database & composite indexes, Cloud Run / Agent Runtime services, least-privilege IAM service accounts, Secret Manager secret containers, and Cloud Trace/Logging sinks.
- **CI/CD Pipeline (GitHub Actions / Cloud Build)**:
  1. **Static & Lint Checks**: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests/unit tests/integration`, `uv run codespell`, frontend `eslint` + `tsc --noEmit`, `terraform fmt -check` & `terraform validate`.
  2. **Deterministic Tests**: `uv run pytest` (107 unit, integration, authorization-boundary, and Cloud Firestore Emulator tests) and frontend `Vitest` (14 tests across `web/src/App.test.tsx`, `web/src/TestPyramidJourneys.test.tsx`, and `web/src/DesignSystemAndShell.test.tsx`).
  3. **Agent Behavioral & Trajectory Evaluation**: `make eval-deterministic`, `make eval-smoke`, and `make eval` (`tests/eval/run_eval_suite.py` + `agents-cli eval`) grading the 120-scenario `brew-comprehensive-dataset.json` across all 15 coaching, personalization, memory, grounding, prompt-injection, and tool-failure categories.
