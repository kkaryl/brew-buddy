# Product Requirements Document (PRD) — Brew

**Product Name:** Brew — AI-Powered Coffee Chat Buddy  
**Status:** Draft v1.0 (Foundational Specification)  
**Owner:** Principal Engineering  
**Last Updated:** 2026-11-22

---

## 1. Vision & Problem Statement

### 1.1 Vision
Brew helps professionals prepare for high-value interpersonal conversations—**coffee chats, networking meetings, mentorship conversations, and customer discovery meetings**—and compounds relationship context over time through user-governed, privacy-conscious memory.

### 1.2 Problem Statement
Professionals frequently enter 15-to-60-minute relationship-oriented conversations underprepared or relying on generic templates:
- Preparation notes are scattered across ad-hoc docs and lost after the meeting.
- Generic AI prompts produce robotic or overly formal agendas that ignore time constraints, desired tone, or past interactions with the same person.
- Insights and personal communication preferences gained in one meeting rarely carry forward cleanly into future sessions—yet automatic, unreviewed AI "memory" creates trust, accuracy, and privacy risks.

Brew solves this with a structured, conversational preparation-to-reflection loop backed by explicit Human-in-the-Loop (HITL) memory approval.

---

## 2. Target Users & Meeting Archetypes

| Archetype | Typical User | Primary Goal |
| :--- | :--- | :--- |
| **Coffee Chat** | Peer, colleague, or new teammate | Build rapport, align on shared context, and establish an authentic working relationship. |
| **Networking Meeting** | Career switcher, job seeker, or industry peer | Learn about a role, company, or industry; ask memorable questions; leave a strong impression. |
| **Mentorship Conversation** | Mentee or mentor | Drive focused growth discussions, follow through on prior commitments, and surface actionable feedback. |
| **Customer Discovery** | Product manager, founder, or UX researcher | Uncover real user pain points and workflows through non-leading, open-ended questions within a strict timebox. |

---

## 3. Core User Journey

Brew is organized around seven sequential, repeatable user journey stages:

1. **Enter Counterpart Details**: The user enters known context about the person they will meet—such as **name, title, role**, organization, and optional background notes (e.g., how they connected or shared interests).
2. **Select Meeting Parameters**: The user selects the **meeting purpose** (`coffee_chat`, `networking`, `mentorship`, `customer_discovery`), **duration** (e.g., 15, 30, 45, or 60 minutes), and **tone** (e.g., `warm_casual`, `curious_exploratory`, `structured_executive`, `candid_coaching`).
3. **Generate Personalized Conversation Preparation**: Brew synthesizes a structured, time-boxed preparation brief tailored to the counterpart, meeting parameters, and any relevant approved memories from past sessions.
4. **Refine the Brief Through Natural Language**: The user converses with Brew in natural language (e.g., *"Make the opening less formal"*, *"Focus more on platform scaling challenges"*, *"Cut this down to a tight 20-minute flow"*) to iteratively update the brief.
5. **Add Post-Meeting Notes**: After the conversation, the user records raw meeting notes, highlights, and follow-up takeaways in the session.
6. **Review and Approve Suggested Memories**: Brew asynchronously extracts candidate memories (e.g., counterpart facts, follow-up commitments, and user communication preferences), scrubs PII, and presents them for review. The user explicitly **approves, edits, or rejects** each candidate memory before anything is saved to long-term memory.
7. **Return in a New Session with Informed Preparation**: When the user starts a new session—whether meeting the same person again or preparing for a new conversation—Brew retrieves approved memories and user preferences to personalize the next preparation brief automatically.

---

## 4. Project Scope & Explicit Non-Goals

### 4.1 In-Scope (MVP & Core Platform)
- Counterpart intake form and structured validation (name, title, role, optional organization/context).
- Meeting configuration selector for **purpose**, **duration**, and **tone**.
- Structured preparation brief generation (`MeetingPreparationWorkflow`) containing:
  - Meeting objective & 2 to 3 tailored rapport openers
  - Realistic time-boxed conversation agenda summing strictly to selected duration
  - 5 to 8 prioritized, non-redundant open-ended questions with goal-linked coaching rationales (or explicit user-configured question count)
  - Personalized context callouts (sourced strictly from user input and approved memories—zero hallucinated biographical facts, verified via deterministic quality gates and at most one corrective regeneration)
  - Closing & next-step prompt
- Multi-turn natural-language refinement (`POST /api/v1/briefs/{id}/revise`) supporting duration adjustments (e.g., *"I only have 15 minutes"*), tone shifts (*"Make the questions less formal"*), topic pivots (*"Focus more on their engineering career"*, *"Give me more customer discovery questions"*), and non-repetitive replacements (*"I have already asked these questions before"*), while preserving unchanged context and archiving every historical brief revision immutably (`GET /api/v1/briefs/{id}/revisions`).
- Post-meeting note capture (`POST /api/v1/memories/propose`) with Gemini-backed candidate memory extraction (`AdkMemoryProposalAdapter` / `memory_candidate_extractor`), epistemic source attribution (`user_reported_observation` vs. `user_stated_preference`—never treated as verified objective facts about the wider world), PII scrubbing, and automatic exclusion of sensitive personal or speculative third-party assumptions.
- Human-in-the-Loop (HITL) 5-state memory governance (`proposed`, `approved`, `rejected`, `superseded`, `deleted`) via `GET /api/v1/memories/proposals`, `POST /api/v1/memories/{id}/approve`, `POST /api/v1/memories/{id}/reject`, `GET /api/v1/memories`, `PATCH /api/v1/memories/{id}`, and `DELETE /api/v1/memories/{id}`, including semantic deduplication and explicit contradiction/supersession resolution.
- Cross-session persistence in Firestore (`users/{uid}/preferences/default`, `users/{uid}/memoryProposals`, `users/{uid}/memories`, `users/{uid}/deletedMemories`) including user-configurable custom display names (`GET/PATCH /api/v1/auth/me`) and active-only memory recall in subsequent sessions.
- Responsive **Playful Social Club** pastel editorial web experience (`web/`, React 19 + Vite + TypeScript + Tailwind CSS v4, documented in [`docs/DESIGN.md`](DESIGN.md)) featuring an airy `#FFFAF8` canvas, `#FFFFFF` rounded paper surfaces, `#302731` dark plum typography (`Fraunces` bold headlines + `DM Sans` UI and `"brew."` wordmark with `#EF8B70` coral dot), Lucide outline icons, cohesive flat-vector character illustrations (`chat-setup-hero.png` and companion SVG scenes), shared 5-tab `BottomNavigation` (`Home`, `Chats`, `People`, `Memory`, `Me`) with `#FFE9DE` pale peach active pill, focused creation flows with `← Back` navigation, side-by-side desktop form + blueprint previews, keyboard/WCAG accessibility, same-origin API calls, verified Google/Firebase ID token authentication (`FirebaseGoogleTokenAuthenticator`), automatic token-expiry recovery, and strict deployment lockout of local mock identities.
- Full AgentOps instrumentation: OpenTelemetry + Cloud Trace, structured JSON intent/outcome logging, active PII redaction, ADK safety/policy plugins (`ConversationCoachGuardrailPlugin`), capability-restricted ADK coaching tools (`get_user_preferences`, `get_contact_context`, `get_meeting_history`, `suggest_memory_candidates`) on `conversation_coach`, and automated offline evaluation via `agents-cli eval`.

### 4.2 Explicit Non-Goals (Out of Scope)
1. **No Live Call Recording or Bot Joining**: Brew does not join Zoom, Google Meet, or Microsoft Teams calls, nor does it record or transcribe live audio streams.
2. **No Unauthorized Third-Party Web/Social Scraping**: Brew does not scrape LinkedIn, X/Twitter, or gated external profile databases. Counterpart context comes strictly from user-provided input and previously approved memories.
3. **No Autonomous Outbound Messaging or Calendar Mutation**: Brew will never send emails, DMs, or calendar invites on a user's behalf.
4. **No Silent / Unapproved Long-Term Memory**: Brew never writes inferred facts or preferences to durable cross-session memory without explicit Human-in-the-Loop user approval.
5. **No Enterprise Sales CRM Suite**: Brew is a personal conversation preparation and relationship memory buddy—not a multi-seat B2B sales pipeline, deal-forecasting, or lead-scoring CRM.
6. **No Native Mobile Apps in v1**: Delivered as a responsive web application (React + Vite + TypeScript + Tailwind); native iOS/Android clients are out of scope.

---

## 5. Functional Requirements

| ID | Journey Step | Requirement | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **FR-1** | 1. Counterpart Details | Capture counterpart profile (`name`, `title`, `role`, optional `organization` and `context_notes`). | Input validated via Pydantic & TypeScript schemas; empty/invalid required fields rejected with clear field-level messages. |
| **FR-2** | 2. Meeting Config | Select `purpose`, `duration_minutes`, and `tone`. | Supported enums enforced end-to-end; duration directly constrains agenda time-allocation totals in generated briefs. |
| **FR-3** | 3. Brief Generation | Generate structured `PreparationBrief` grounded in inputs + approved memories. | Brief renders structured sections, cites which approved memories influenced it (if any), and invents zero unverified biographical claims. |
| **FR-4** | 4. NL Refinement | Refine an existing brief via natural-language chat turns. | Refinement preserves unaffected sections, respects duration/tone constraints, and compacts history when conversation length crosses threshold. |
| **FR-5** | 5. Post-Meeting Notes | Submit free-form post-meeting notes tied to a meeting session. | Notes persist immediately with PII scrubbing applied to logs/storage pipelines; async memory extraction job is queued without blocking HTTP response. |
| **FR-6** | 6. Memory Approval | Present extracted `MemoryProposal` candidates (`contact` and `user_preference` scopes) with source provenance, epistemic framing, and conflict metadata for HITL review. | Proposals start in `proposed` state (zero automatic callback writes); user explicitly approves (with optional edit and explicit `supersedes_memory_id` resolution) or rejects (`POST /api/v1/memories/{id}/reject`); duplicates and sensitive third-party assumptions are filtered; rejected, superseded, and deleted items are never retrieved as active memories. |
| **FR-7** | 7. Cross-Session Recall | Retrieve active (`approved`) counterpart and user-preference memories across distinct sessions while honoring updates (`superseded`) and deletions (`deleted`). | Starting a new session with a distinct session ID retrieves approved memories with preserved provenance/timestamps, excludes rejected/superseded/deleted records, and grounds follow-up coaching without treating notes as verified wider-world facts. |

---

## 6. Non-Functional Requirements

- **Latency & Responsiveness**:
  - Initial brief generation (Gemini Pro): p95 < 10s (with clear loading/progress feedback).
  - Conversational brief refinement (Gemini Flash): p95 < 5s.
  - Post-meeting note submission API acknowledgment: p95 < 500ms (memory extraction runs asynchronously in the background).
- **Reliability & Graceful Degradation**:
  - Explicit timeouts on all Gemini, Firestore, and redaction calls.
  - If memory retrieval degrades or times out, brief generation still succeeds using current-session inputs while surfacing a non-fatal warning.
- **Privacy & Safety**:
  - Active PII redaction across structured logs and memory extraction pipelines before persistence.
  - System constitution and ADK runner-wide guardrails block prompt injection, toxic output, and fabricated personal claims.
- **Maintainability & Testability**:
  - Pure Python 3.12 domain layer decoupled from ADK and Firestore; strict static typing (`mypy`/`pyright` + `tsc`) and deterministic test suites (`pytest` + `Vitest`) complemented by `agents-cli eval`.

---

## 7. Quality & Evaluation Metrics

- **4-Layer Test Pyramid & Automated Agent Evaluation (`pytest`, `Vitest`, `agents-cli eval`)**:
  - **Unit & Contract Layer (`tests/unit/`)**: Pure domain invariants, SSN/email/phone PII scrubbing, 7-family prompt-injection sanitization, ADK tool schemas, plugin budgets, and deployment mock/fixture lockouts.
  - **Integration Layer (`tests/integration/`)**: Full 13-route FastAPI OpenAPI v1 verification, live Cloud Firestore Emulator persistence, multi-turn ADK `FirestoreSessionService` event continuity, and cross-tenant `401`/`403`/`422` authorization bounds.
  - **120-Scenario Agent Evaluation Suite (`tests/eval/datasets/brew-comprehensive-dataset.json`)**: 8 scenarios across each of 15 representative categories (first-time networking, Senior EM, potential mentor, customer discovery, returning contact, casual peer, 15-minute short chat, preference personalization, cross-session memory recall, conflicting memory, missing info, unsupported person claims, untrusted profile / prompt injection, tool failure, and follow-up preparation), graded via deterministic `coaching_guardrail_compliance` & `tool_trajectory_contract` metrics plus `brew_coaching_rubric_judge` and `custom_response_quality` LLM-as-judge rubrics.
  - **Frontend Experience Layer (`web/src/*.test.tsx`)**: End-to-end counterpart/brief journeys, deferred loading/timeout/degraded-source states, HITL memory approval/supersession/deletion, and immutable `v1 -> v2 -> v3` revision interactions.
