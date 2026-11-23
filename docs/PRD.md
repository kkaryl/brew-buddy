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
- Structured preparation brief generation containing:
  - Meeting objective & rapport opener
  - Time-boxed conversation arc tailored to selected duration
  - Prioritized, non-generic questions matched to purpose and tone
  - Personalized context callouts (sourced strictly from user input and approved memories—zero hallucinated biographical facts)
  - Closing & next-step prompt
- Multi-turn natural-language refinement chat with context compaction for extended sessions.
- Post-meeting note capture with non-blocking asynchronous candidate memory generation.
- Human-in-the-Loop (HITL) memory review queue (approve, edit before approving, or reject).
- Cross-session persistence in Firestore and memory-informed preparation in subsequent sessions.
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
| **FR-6** | 6. Memory Approval | Present extracted `CandidateMemory` items (`counterpart_fact`, `user_preference`, `follow_up`) for HITL review. | Candidates remain in `PENDING_REVIEW` state until user explicitly approves (with optional edit) or rejects; rejected items are never retrieved in future prep. |
| **FR-7** | 7. Cross-Session Recall | Retrieve approved memories for returning counterpart and global user preferences in new sessions. | Starting a new session with prior approved memories measurably incorporates user preferences (e.g., preferred question style) and counterpart history. |

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

- **Offline Agent Evaluation (`agents-cli eval`)**:
  - **Constraint Adherence**: Time-boxed sections sum to requested `duration_minutes`; tone matches requested archetype.
  - **Grounding & Hallucination Zero-Tolerance**: Zero fabricated counterpart employer history, schools, or biographical facts not present in input or approved memories.
  - **Memory Utilization**: Returning-session eval cases accurately reflect previously approved user preferences and counterpart takeaways.
  - **Guardrail Resilience**: Adversarial/injection inputs and PII-heavy post-meeting notes are safely handled and scrubbed.
