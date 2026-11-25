/**
 * Exact 1:1 TypeScript contracts mirroring Brew's FastAPI v1 Pydantic schemas (`docs/openapi.json`).
 * Do not introduce parallel client-only payload shapes that diverge from the backend contract.
 */

export type MeetingPurpose =
  | "coffee_chat"
  | "networking"
  | "mentorship"
  | "customer_discovery";

export type MeetingTone =
  | "warm_casual"
  | "curious_exploratory"
  | "structured_executive"
  | "candid_coaching";

export type MeetingStatus = "preparing" | "completed" | "cancelled";

export type MemoryScope = "user_preference" | "contact";

export type MemoryType =
  | "communication_preference"
  | "agenda_preference"
  | "counterpart_background"
  | "shared_interest"
  | "follow_up_commitment"
  | "relationship_note";

export type ConsentStatus = "approved" | "revoked";

export type ProposalStatus = "pending" | "approved" | "rejected";

export type MemoryLifecycleState =
  | "proposed"
  | "approved"
  | "rejected"
  | "superseded"
  | "deleted";

export type MemoryEpistemicStatus =
  | "user_reported_observation"
  | "user_stated_preference";

export type MemorySourceType =
  | "meeting_notes"
  | "brief_refinement"
  | "direct_user_input";

export type BriefWorkflowOperation = "generate" | "revise";

export type BriefWorkflowTerminalState =
  | "completed"
  | "completed_repaired"
  | "completed_idempotent_replay"
  | "failed_input_validation"
  | "failed_not_found"
  | "failed_forbidden"
  | "failed_conflict"
  | "failed_output_validation"
  | "failed_model_timeout"
  | "failed_model_error"
  | "failed_persistence";

export interface ErrorDetailItem {
  readonly field: string;
  readonly message: string;
  readonly error_type: string;
}

export interface ErrorObject {
  readonly code: string;
  readonly message: string;
  readonly trace_id: string;
  readonly details: readonly ErrorDetailItem[];
}

export interface ApiErrorResponse {
  readonly error: ErrorObject;
}

export interface FirebaseClientConfigResponse {
  readonly project_id: string;
  readonly api_key: string;
  readonly auth_domain: string;
}

export interface MockPersonaOptionResponse {
  readonly persona_id: string;
  readonly display_name: string;
  readonly role_summary: string;
}

export interface AuthClientConfigResponse {
  readonly auth_mode: "verified" | "local_mock";
  readonly environment: string;
  readonly local_mock_enabled: boolean;
  readonly google_sign_in_enabled: boolean;
  readonly firebase: FirebaseClientConfigResponse | null;
  readonly google_oauth_client_id: string | null;
  readonly mock_personas: readonly MockPersonaOptionResponse[];
}

export interface AuthenticatedPrincipalResponse {
  readonly user_id: string;
  readonly display_name: string | null;
  readonly auth_provider: string;
}

export interface MockSessionResponse {
  readonly access_token: string;
  readonly token_type: "Bearer";
  readonly expires_at: string;
  readonly principal: AuthenticatedPrincipalResponse;
}

export interface CreateContactRequest {
  readonly name: string;
  readonly title?: string | null;
  readonly role?: string | null;
  readonly organization?: string | null;
  readonly context_notes?: string | null;
}

export interface ContactResponse {
  readonly id: string;
  readonly name: string;
  readonly title: string | null;
  readonly role: string | null;
  readonly organization: string | null;
  readonly context_notes: string | null;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ContactListResponse {
  readonly items: readonly ContactResponse[];
  readonly total: number;
}

export interface MeetingResponse {
  readonly id: string;
  readonly contact_id: string;
  readonly purpose: MeetingPurpose;
  readonly tone: MeetingTone;
  readonly objective: string;
  readonly duration_minutes: number;
  readonly scheduled_at: string | null;
  readonly notes: string | null;
  readonly status: MeetingStatus;
  readonly latest_brief_id: string | null;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface MeetingListResponse {
  readonly items: readonly MeetingResponse[];
  readonly total: number;
}

export interface UserPreferencesInput {
  readonly preferred_question_count?: number | null;
  readonly communication_style_notes?: string | null;
  readonly focus_areas?: readonly string[] | null;
}

export interface GenerateBriefRequest {
  readonly contact_id: string;
  readonly purpose: MeetingPurpose;
  readonly tone?: MeetingTone;
  readonly meeting_objective: string;
  readonly duration_minutes: number;
  readonly scheduled_at?: string | null;
  readonly meeting_notes?: string | null;
  readonly preferences?: UserPreferencesInput | null;
}

export interface ReviseBriefRequest {
  readonly instructions: string;
  readonly expected_version: number;
  readonly duration_minutes?: number | null;
  readonly tone?: MeetingTone | null;
}

export interface AgendaItemResponse {
  readonly title: string;
  readonly duration_minutes: number;
  readonly description: string;
}

export interface ConversationQuestionResponse {
  readonly id: string;
  readonly question: string;
  readonly rationale: string;
  readonly category: string | null;
}

export interface BriefWorkflowDiagnosticsResponse {
  readonly request_id: string;
  readonly trace_id: string;
  readonly operation: BriefWorkflowOperation;
  readonly terminal_state: BriefWorkflowTerminalState;
  readonly attempt_count: number;
  readonly regeneration_count: number;
  readonly model_invocations: number;
  readonly tool_invocations: number;
  readonly replayed: boolean;
  readonly quality_passed: boolean;
  readonly degraded_sources: readonly string[];
  readonly previous_version: number | null;
}

export interface PreparationBriefResponse {
  readonly id: string;
  readonly meeting_id: string;
  readonly contact_id: string;
  readonly duration_minutes: number;
  readonly tone: MeetingTone;
  readonly contact_context: string;
  readonly meeting_objective: string;
  readonly conversation_openers: readonly string[];
  readonly time_boxed_agenda: readonly AgendaItemResponse[];
  readonly suggested_questions: readonly ConversationQuestionResponse[];
  readonly suggested_follow_up_topics: readonly string[];
  readonly referenced_memory_ids: readonly string[];
  readonly revision_summary: string | null;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly workflow: BriefWorkflowDiagnosticsResponse | null;
}

export interface BriefRevisionListResponse {
  readonly items: readonly PreparationBriefResponse[];
  readonly total: number;
}

export interface MemorySourceResponse {
  readonly source_type: MemorySourceType;
  readonly meeting_id: string | null;
  readonly brief_id: string | null;
  readonly proposal_id: string | null;
  readonly excerpt: string | null;
  readonly recorded_at: string;
}

export interface ProposeMemoriesRequest {
  readonly notes: string;
  readonly source_type?: MemorySourceType;
  readonly meeting_id?: string | null;
  readonly contact_id?: string | null;
  readonly brief_id?: string | null;
}

export interface MemoryProposalResponse {
  readonly id: string;
  readonly scope: MemoryScope;
  readonly contact_id: string | null;
  readonly memory_type: MemoryType;
  readonly text: string;
  readonly rationale: string;
  readonly source: MemorySourceResponse;
  readonly status: ProposalStatus;
  readonly lifecycle_state: MemoryLifecycleState;
  readonly epistemic_status: MemoryEpistemicStatus;
  readonly supersedes_memory_id: string | null;
  readonly conflict_summary: string | null;
  readonly rejection_reason: string | null;
  readonly approved_memory_id: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly reviewed_at: string | null;
  readonly version: number;
}

export interface MemoryProposalBatchResponse {
  readonly proposals: readonly MemoryProposalResponse[];
  readonly total: number;
  readonly skipped_duplicates: number;
  readonly filtered_sensitive_count: number;
}

export type MemoryExtractionJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface MemoryExtractionJobError {
  readonly code: string;
  readonly message: string;
}

export interface MemoryExtractionJobResponse {
  readonly id: string;
  readonly status: MemoryExtractionJobStatus;
  readonly contact_id: string | null;
  readonly meeting_id: string | null;
  readonly brief_id: string | null;
  readonly result: MemoryProposalBatchResponse | null;
  readonly error: MemoryExtractionJobError | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly completed_at: string | null;
}

export interface ApproveMemoryProposalRequest {
  readonly expected_version?: number;
  readonly edited_text?: string | null;
  readonly memory_type?: MemoryType | null;
  readonly supersedes_memory_id?: string | null;
}

export interface RejectMemoryProposalRequest {
  readonly expected_version?: number;
  readonly reason?: string | null;
}

export interface UpdateMemoryRequest {
  readonly expected_version: number;
  readonly text?: string | null;
  readonly memory_type?: MemoryType | null;
  readonly consent_status?: ConsentStatus | null;
}

export interface MemoryResponse {
  readonly id: string;
  readonly owner_user_id: string;
  readonly scope: MemoryScope;
  readonly contact_id: string | null;
  readonly memory_type: MemoryType;
  readonly text: string;
  readonly source: MemorySourceResponse;
  readonly consent_status: ConsentStatus;
  readonly lifecycle_state: MemoryLifecycleState;
  readonly epistemic_status: MemoryEpistemicStatus;
  readonly supersedes_memory_id: string | null;
  readonly superseded_by_memory_id: string | null;
  readonly superseded_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
}

export interface MemoryListResponse {
  readonly items: readonly MemoryResponse[];
  readonly total: number;
}
