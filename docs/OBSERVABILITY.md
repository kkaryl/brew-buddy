# Production Observability Guide — Brew (`docs/OBSERVABILITY.md`)

**Status:** Active Production Runbook  
**Stack:** OpenTelemetry SDK + Google Cloud Trace + Google ADK 2.x Telemetry + Cloud Logging Structured JSON

---

## 1. Architecture & Non-Duplicating Span Hierarchy

Brew combines the OpenTelemetry instrumentation scaffolded by `google-agents-cli` / Google ADK (`get_fast_api_app(..., otel_to_cloud=...)` in [`app/fast_api_app.py`](../app/fast_api_app.py)) with domain-aware application, validation, corrective regeneration, memory governance, and Firestore spans ([`app/application/shared/telemetry.py`](../app/application/shared/telemetry.py), [`app/infrastructure/observability.py`](../app/infrastructure/observability.py)).

To prevent noisy duplicate spans:
- **ADK-owned stages (`invoke_workflow`, `invoke_agent`, `generate_content`, `execute_tool`)** are **preserved and enriched in place** via [`ConversationCoachGuardrailPlugin`](../app/agents/plugins/coach_guardrails.py), [`WorkflowSafeguardPlugin`](../app/agents/plugins/workflow_safeguards.py), and `tool_telemetry_scope` in [`app/agents/tools/registry.py`](../app/agents/tools/registry.py).
- **Brew-owned stages** wrap HTTP ingress, 9-step workflow orchestration, pre-brief context/memory retrieval, deterministic schema + quality validation, single corrective regeneration, HITL memory approval, and async Firestore persistence.

### End-to-End Correlated Trace Tree

```text
POST /api/v1/briefs/generate  [SpanKind.SERVER — brew.operation.name="http.request"]
└── brew.workflow.generate_brief  [workflow.generate_brief]
    ├── firestore.contacts.get  [db.system="firestore"]
    ├── brew.context.retrieve  [context.retrieve — brew.memory.retrieved_count]
    │   ├── firestore.preferences.get
    │   ├── firestore.memories.list  [scope=user_preference]
    │   ├── firestore.meetings.list
    │   └── firestore.memories.list  [scope=contact, brew.memory.retrieved_count]
    ├── coach.workflow.generate_brief
    │   ├── invoke_workflow conversation_coach  [ADK built-in]
    │   │   └── invoke_agent conversation_coach  [ADK built-in + Brew agent metadata]
    │   │       ├── generate_content gemini-3.8-flash  [ADK built-in — input/output tokens]
    │   │       ├── execute_tool get_meeting_history  [ADK built-in + Brew tool status/error]
    │   │       │   └── firestore.meetings.list
    │   │       └── generate_content gemini-3.8-flash  [ADK built-in — input/output tokens]
    │   └── brew.output.validate  [brew.validation.stage="json_schema"]
    ├── brew.output.validate  [brew.validation.stage="domain_and_quality"]
    ├── brew.workflow.corrective_regeneration  [OPTIONAL — only if Attempt 1 fails validation]
    │   ├── coach.workflow.generate_brief  [Attempt 2]
    │   └── brew.output.validate  [brew.validation.stage="domain_and_quality"]
    └── brew.persistence.save_brief_artifacts
        ├── firestore.meetings.save
        ├── firestore.briefs.save  [transactional brief + immutable v{N} revision]
        └── firestore.workflow_idempotency.save  [when Idempotency-Key is supplied]
```

### Canonical Safe Span Attributes

| Attribute Key | Type | Emitted On | Description |
| :--- | :--- | :--- | :--- |
| `brew.request_id` | `string` | All spans | Validated `X-Request-ID` caller correlation ID (or 32-hex trace ID). |
| `brew.trace_id` | `string` | All spans | Unified workflow/API correlation trace ID returned in responses/errors. |
| `brew.otel_trace_id` | `string` | All spans | Canonical 32-character lowercase hex W3C / Cloud Trace ID. |
| `brew.operation.name` | `string` | All Brew & enriched ADK spans | Normalized stage (`http.request`, `workflow.generate_brief`, `context.retrieve`, `agent.invoke`, `tool.<name>`, `output.validate`, `workflow.corrective_regeneration`, `memory.approve`, `firestore.<coll>.<op>`). |
| `brew.agent.name` | `string` | Agent, workflow, validation spans | `conversation_coach` or `memory_candidate_extractor`. |
| `brew.agent.version` | `string` | Agent, workflow, validation spans | Semantic version of the agent (`1.0.0`). |
| `brew.model.name` | `string` | Agent, model, adapter spans | Configured/resolved Gemini model (e.g., `gemini-3.8-flash`). |
| `brew.tool.name` | `string` | Tool spans | Specific verb-noun tool (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`). |
| `brew.duration_ms` | `float` | All Brew & enriched ADK spans | Wall-clock stage duration in milliseconds. |
| `gen_ai.usage.input_tokens` / `brew.tokens.input` | `int` | `generate_content` & workflow/adapter spans | Prompt token count per model call and cumulative workflow total. |
| `gen_ai.usage.output_tokens` / `brew.tokens.output` | `int` | `generate_content` & workflow/adapter spans | Candidate output token count per call and cumulative workflow total. |
| `brew.tokens.total` | `int` | Workflow & adapter spans | Total tokens (`input + output`) across all model turns in the stage. |
| `brew.result.status` | `string` | All spans | `ok`, `success`, `empty`, `repaired`, `completed`, `completed_repaired`, `degraded`, or `error`. |
| `brew.error.classification` | `string` | Error & degraded spans | Canonical failure category (e.g., `TIMEOUT`, `MODEL_TIMEOUT`, `OUTPUT_VALIDATION_ERROR`, `TOOL_RETRY_LIMIT_EXCEEDED`, `PERSISTENCE_UNAVAILABLE`, `FORBIDDEN`). |
| `brew.error.code` | `string` | Error spans | Domain or HTTP error code (`MODEL_TIMEOUT`, `VERSION_CONFLICT`, etc.). |
| `brew.memory.retrieved_count` | `int` | Context, memory, tool, Firestore spans | Count of active approved memories loaded into context or returned. |
| `brew.memory.saved_count` | `int` | Memory propose/approve, tool, Firestore spans | Count of staged proposals or newly persisted durable memories. |

---

## 2. Privacy & Content-Capture Lockdown

Brew handles sensitive interpersonal context. By default, **raw contact notes, private biographies, meeting notes, credentials, and full LLM prompts/responses are never captured in traces or logs**:

1. **Prompt/Response Capture Disabled by Default**:
   - Startup (`enforce_telemetry_privacy_defaults` in [`app/infrastructure/observability.py`](../app/infrastructure/observability.py)) sets:
     - `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT`
     - `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` *(overrides ADK's legacy default-on span capture)*
   - Every ADK `RunConfig` attaches `TelemetryConfig(capture_message_content=ContentCapturingMode.NO_CONTENT)` unless `BREW_TELEMETRY_CAPTURE_CONTENT=true` is explicitly authorized.
2. **Completion Uploads Disabled Unless Authorized**:
   - Unless `BREW_TELEMETRY_UPLOAD_COMPLETIONS=true` is explicitly configured, startup removes `OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK`, `OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH`, and `OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT` from the process environment and logs `telemetry.privacy.upload_hooks_disabled`.
3. **Attribute Denylist & Active PII/Credential Redaction**:
   - `FORBIDDEN_TELEMETRY_KEYS` ([`app/application/shared/telemetry.py`](../app/application/shared/telemetry.py)) drops keys such as `notes`, `meeting_notes`, `context_notes`, `prompt`, `instructions`, `edited_text`, `excerpt`, `authorization`, `token`, `api_key`, and `secret`.
   - `scrub_sensitive_telemetry_text` redacts `Bearer` credentials, JWTs (`eyJ...`), Google API keys (`AIza...`), OAuth tokens (`ya29...`), emails, SSNs, and phone numbers across both span attributes and structured JSON logs.

---

## 3. Operational Runbooks

### 3.1 How to Locate a Request Trace

Every HTTP response (2xx and 4xx/5xx) exposes correlation identifiers in three places:
1. **Response Headers**:
   - `X-Trace-ID`: 32-hex OpenTelemetry trace ID (use this directly in Cloud Trace Explorer).
   - `X-Request-ID`: Caller-supplied `X-Request-ID` header or generated request ID.
2. **Brief Workflow Payload**: `response.workflow.trace_id` and `response.workflow.request_id`.
3. **API Error Envelope**: `response.error.trace_id`.

**Upstream Propagation**: Brew automatically continues incoming W3C `traceparent` (`00-<trace_id>-<span_id>-01`) and Google Cloud Load Balancer / Cloud Run `X-Cloud-Trace-Context` (`<trace_id>/<span_id>;o=1`) headers.

**In Google Cloud Console (Trace Explorer)**:
- **Direct Lookup by `X-Trace-ID`**: Open **Cloud Console -> Trace -> Trace Explorer** and paste the 32-hex `X-Trace-ID` into the **Trace ID** lookup box.
- **Filter by Custom `X-Request-ID`**: Add span attribute filter:
  ```text
  +brew.request_id:<X_REQUEST_ID>
  ```
- **Via `gcloud` CLI**:
  ```bash
  # Find the 32-hex Cloud Trace ID from a custom X-Request-ID via Cloud Logging
  gcloud logging read \
    'jsonPayload.request_id="req_http_01"' \
    --project="${GOOGLE_CLOUD_PROJECT}" \
    --limit=5 \
    --format='table(timestamp, trace, jsonPayload.event_type, jsonPayload.http_status_code)'
  ```

---

### 3.2 How to Identify Expensive Model Calls

Expensive model invocations manifest either as **high latency (`brew.duration_ms`)** or **high token consumption (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `brew.tokens.total`)**.

1. **In Cloud Trace Explorer**:
   - Filter by span name `generate_content` (individual Gemini calls) or `brew.workflow.generate_brief` / `brew.workflow.revise_brief` (cumulative request totals) and set **Min Latency** (e.g., `>= 3s`).
   - Click a `generate_content <model>` span to inspect:
     - `gen_ai.request.model` / `brew.model.name`
     - `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`
   - Click the parent `brew.workflow.generate_brief` span to inspect cumulative multi-turn cost:
     - `brew.tokens.input`, `brew.tokens.output`, and `brew.tokens.total`
     - `brew.regeneration.count` (whether a validation retry doubled token spend)
2. **In Cloud Logging (Find Top Token Consumers or Slow Calls)**:
   ```bash
   # Find Gemini calls exceeding 1,500 total tokens or 4,000 ms latency
   gcloud logging read \
     'jsonPayload.event_type="workflow.model.outcome" AND (jsonPayload.total_tokens > 1500 OR jsonPayload.duration_ms > 4000)' \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --limit=20 \
     --format='table(timestamp, jsonPayload.trace_id, jsonPayload.agent_name, jsonPayload.model_name, jsonPayload.input_tokens, jsonPayload.output_tokens, jsonPayload.total_tokens, jsonPayload.duration_ms)'
   ```

---

### 3.3 How to Inspect Tool Failures

Brew's coaching tools (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`) catch operational errors and return structured `recovery_instruction` payloads so `conversation_coach` can degrade gracefully without crashing the user's request.

Even when the overall HTTP request succeeds (`201 Created`), **failed tool spans are explicitly marked `StatusCode.ERROR`** so they never fail silently:

1. **In Cloud Trace Explorer**:
   - Filter spans by:
     - Span name prefix: `execute_tool`
     - Status: `Error` (or `+brew.result.status:error`)
   - Inspect attributes on the red `execute_tool <tool_name>` span:
     - `brew.tool.name`: Which tool failed (e.g., `get_meeting_history`).
     - `brew.error.classification`: Exact root cause (`TIMEOUT`, `SERVICE_UNAVAILABLE`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`, `IDENTITY_OVERRIDE_FORBIDDEN`, `TOOL_RETRY_LIMIT_EXCEEDED`).
     - `brew.duration_ms`: Whether the tool hit `FIRESTORE_TIMEOUT_SECONDS` (`TIMEOUT`) or failed fast.
   - Check child `firestore.*` spans underneath `execute_tool` to see if the failure originated in Firestore (`PERSISTENCE_TIMEOUT`, `PERSISTENCE_AUTH_ERROR`, `PERSISTENCE_UNAVAILABLE`).
2. **In Cloud Logging**:
   ```bash
   gcloud logging read \
     'jsonPayload.event_type=("agent.tool.outcome" OR "tool.execution.failed" OR "workflow.tool.retry_capped") AND jsonPayload.result_status="error"' \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --limit=20 \
     --format='table(timestamp, jsonPayload.trace_id, jsonPayload.tool_name, jsonPayload.error_classification, jsonPayload.duration_ms)'
   ```

---

### 3.4 How to Understand Retries

Brew enforces strict, deterministic retry budgets across four distinct layers so transient issues heal while runaway loops are impossible:

| Layer | Where It Appears in Trace | Max Budget | How to Read It in Cloud Trace |
| :--- | :--- | :--- | :--- |
| **1. Pre-Brief Context Source Retry** | Multiple `firestore.*` child spans under `brew.context.retrieve` | `1 + BREW_WORKFLOW_MAX_TOOL_RETRIES` (default `2` tries) | If an optional read (`meeting_history`, `preference_memories`, `contact_memories`) still fails, `brew.context.retrieve` sets `brew.result.status="degraded"`, `brew.context.degraded_sources_count > 0`, and logs `workflow.context.degraded`. |
| **2. Agent Tool Retry Cap** | Multiple `execute_tool <name>` spans under `invoke_agent` | `BREW_WORKFLOW_MAX_TOOL_RETRIES` (default `1` retry) | First failure shows `brew.error.classification="TIMEOUT"` (or `SERVICE_UNAVAILABLE`). If the LLM retries past the cap, `WorkflowSafeguardPlugin` short-circuits before I/O and stamps `brew.error.classification="TOOL_RETRY_LIMIT_EXCEEDED"`. |
| **3. Output Validation Retry (Corrective Regeneration)** | `brew.output.validate` (failed) followed by `brew.workflow.corrective_regeneration` | At most **1** (`MAX_ALLOWED_REGENERATIONS = 1`) | Attempt 1's `brew.output.validate` has `brew.validation.passed=false` and `StatusCode.ERROR` (`OUTPUT_VALIDATION_ERROR`). Next, `brew.workflow.corrective_regeneration` (`brew.regeneration.attempt=1`) runs a repair turn. If repaired, `brew.result.status="repaired"` and the workflow finishes `completed_repaired`; if Attempt 2 also fails, it marks `StatusCode.ERROR` and returns HTTP `422 MODEL_OUTPUT_VALIDATION_ERROR`. |
| **4. Caller Idempotent Replay** | `POST /api/v1/briefs/generate` or `/revise` with `Idempotency-Key` | Deduplicated | `firestore.workflow_idempotency.get` hits an existing fingerprint; zero `invoke_agent` or `generate_content` spans execute, and `workflow.terminal_state="completed_idempotent_replay"`. |

---

### 3.5 How to Correlate Errors with Logs

Every log line emitted by `app.*` and `google_adk.*` is formatted by `StructuredJsonFormatter` + `TraceContextLogFilter` ([`app/infrastructure/observability.py`](../app/infrastructure/observability.py)) as single-line JSON with Cloud Logging's native trace-linking fields:

```json
{
  "timestamp": "2026-11-24T10:01:18.439514+00:00",
  "severity": "ERROR",
  "logger": "app.api.errors",
  "message": "API domain error MODEL_TIMEOUT (HTTP 504)",
  "request_id": "3466756f628f6b13dc48b42811a43067",
  "trace_id": "3466756f628f6b13dc48b42811a43067",
  "otel_trace_id": "3466756f628f6b13dc48b42811a43067",
  "span_id": "573f4557ea332d1e",
  "logging.googleapis.com/trace": "projects/my-gcp-project/traces/3466756f628f6b13dc48b42811a43067",
  "logging.googleapis.com/spanId": "573f4557ea332d1e",
  "logging.googleapis.com/trace_sampled": true,
  "event_type": "http.error.domain",
  "operation_name": "http.request",
  "result_status": "error",
  "error_type": "ModelTimeoutError",
  "error_code": "MODEL_TIMEOUT",
  "error_classification": "MODEL_TIMEOUT",
  "http_method": "POST",
  "http_route": "/api/v1/briefs/generate",
  "http_status_code": 504
}
```

#### Error Classification Reference

| `error_classification` | Domain / Python `error_type` | HTTP Status | Typical Span Location |
| :--- | :--- | :---: | :--- |
| `MODEL_TIMEOUT` | `ModelTimeoutError` / `TimeoutError` | `504` | `coach.workflow.*`, `brew.workflow.*` |
| `MODEL_INVOCATION_LIMIT_EXCEEDED` | `ModelExecutionError` | `502` | `invoke_agent`, `coach.workflow.*` |
| `MODEL_EXECUTION_ERROR` | `ModelExecutionError` | `502` | `generate_content`, `coach.workflow.*` |
| `OUTPUT_VALIDATION_ERROR` | `ModelOutputValidationError` / `BriefQualityViolation` | `422` | `brew.output.validate`, `brew.workflow.corrective_regeneration` |
| `TIMEOUT` / `TOOL_TIMEOUT` | `TimeoutError` | Recovered (or `504`) | `execute_tool <tool_name>` |
| `TOOL_RETRY_LIMIT_EXCEEDED` | Safeguard short-circuit | Recovered | `execute_tool <tool_name>` |
| `PERSISTENCE_TIMEOUT` / `PERSISTENCE_UNAVAILABLE` | `PersistenceOperationError` | `503` (or degraded) | `firestore.<collection>.<op>` |
| `PERSISTENCE_AUTH_ERROR` | `PersistenceOperationError` (`GoogleAuthError`) | `503` | `firestore.<collection>.<op>` |
| `AUTHENTICATION_REQUIRED` | `AuthenticationError` | `401` | `GET/POST /api/v1/...` |
| `FORBIDDEN` | `AuthorizationError` | `403` | `execute_tool` or `/api/v1/...` |
| `NOT_FOUND` | `EntityNotFoundError` | `404` | `execute_tool` or `/api/v1/...` |
| `VERSION_CONFLICT` / `STATE_CONFLICT` | `VersionConflictError` / `ConflictError` | `409` | `brew.memory.approve`, `firestore.*.save` |
| `VALIDATION_ERROR` | `DomainValidationError` / `RequestValidationError` | `422` | `/api/v1/...` or `execute_tool` |

#### Step-by-Step Error -> Trace -> Log Workflow
1. **Start from an Error Alert or 4xx/5xx Response**: Copy `error.trace_id` from the JSON response (or `X-Trace-ID` header).
2. **Pull All Correlated Logs Across Every Layer**:
   ```bash
   TRACE_ID="3466756f628f6b13dc48b42811a43067"
   gcloud logging read \
     "trace=\"projects/${GOOGLE_CLOUD_PROJECT}/traces/${TRACE_ID}\" OR jsonPayload.trace_id=\"${TRACE_ID}\"" \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --order=asc \
     --format=json
   ```
3. **Jump Directly to the Failing Span**: Match `jsonPayload.span_id` (`logging.googleapis.com/spanId`) against the waterfall in **Cloud Trace Explorer** (or click **View in Trace** directly on the log entry in Cloud Logging).

---

## 4. Demonstrated Trace Scenarios & Local Verification

All five production trace scenarios and privacy invariants are deterministically verified offline in [`tests/unit/test_observability_tracing.py`](../tests/unit/test_observability_tracing.py):

1. **Successful Brief Generation (`test_scenario_1_...`)**: Correlates `POST /api/v1/briefs/generate` -> `brew.workflow.generate_brief` -> `brew.context.retrieve` (`brew.memory.retrieved_count=1`) -> `invoke_agent brief_synthesizer` -> `execute_tool get_meeting_history` -> `generate_content` (token counts) -> `brew.output.validate` -> `firestore.meetings.save` + `firestore.briefs.save`, proving zero leakage of contact notes, meeting notes, emails, phone numbers, tokens, or raw prompts.
2. **Memory Retrieval (`test_scenario_2_...`)**: Correlates `GET /api/v1/memories` -> `brew.memory.retrieve` -> `firestore.memories.list` with matching `brew.memory.retrieved_count=2` and zero memory-body leakage.
3. **Tool Timeout / Failure & Model Timeout (`test_scenario_3_...`)**: Demonstrates `execute_tool get_meeting_history` marked `StatusCode.ERROR` with `brew.error.classification="TIMEOUT"` followed by `TOOL_RETRY_LIMIT_EXCEEDED` and graceful brief synthesis, plus end-to-end `504 MODEL_TIMEOUT` span/log correlation.
4. **Validation Retry / Corrective Regeneration (`test_scenario_4_...`)**: Demonstrates failed `brew.output.validate` (`OUTPUT_VALIDATION_ERROR`) triggering `brew.workflow.corrective_regeneration` (`brew.regeneration.attempt=1`, `brew.result.status="repaired"`) as well as terminal `422 MODEL_OUTPUT_VALIDATION_ERROR` when both attempts fail.
5. **Memory Proposal & HITL Approval (`test_scenario_5_...`)**: Demonstrates `POST /api/v1/memories/propose` (`brew.memory.propose` -> `invoke_agent memory_candidate_extractor` -> `firestore.memory_proposals.save`, zero writes to `memories`) followed by `POST /api/v1/memories/{id}/approve` (`brew.memory.approve` -> `firestore.memories.save` with `brew.memory.saved_count=1`). The `suggest_memory_candidates` tool opens the same `brew.memory.propose` span. On both paths it carries `brew.memory.skipped_duplicates`, `brew.memory.filtered_sensitive_count` and `brew.memory.filtered_directive_count`.

Run the local tracing suite at any time with:

```bash
uv run pytest tests/unit/test_observability_tracing.py -v
```
