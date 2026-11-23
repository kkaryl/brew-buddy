import { useState, type FormEvent, type JSX } from "react";
import type {
  ApproveMemoryProposalRequest,
  ContactResponse,
  MeetingResponse,
  MemoryProposalBatchResponse,
  MemoryProposalResponse,
  MemoryResponse,
  MemoryType,
  PreparationBriefResponse,
  ProposeMemoriesRequest,
  RejectMemoryProposalRequest,
} from "../api/types";
import {
  MEMORY_TYPE_OPTIONS,
  errorToFeedbackNotice,
  formatEpistemicLabel,
  formatMemoryScopeLabel,
  formatMemoryTypeLabel,
  formatShortTimestamp,
  type FeedbackNotice,
} from "./formatters";
import { EmptyStateCard, StatusBanner } from "./StatusFeedback";

export interface MemoryReviewWorkspaceProps {
  readonly contacts: readonly ContactResponse[];
  readonly activeContact: ContactResponse | null;
  readonly activeMeeting: MeetingResponse | null;
  readonly activeBrief: PreparationBriefResponse | null;
  readonly pendingProposals: readonly MemoryProposalResponse[];
  readonly onProposeMemories: (
    payload: ProposeMemoriesRequest,
  ) => Promise<MemoryProposalBatchResponse>;
  readonly onApproveProposal: (
    proposalId: string,
    payload: ApproveMemoryProposalRequest,
  ) => Promise<MemoryResponse>;
  readonly onRejectProposal: (
    proposalId: string,
    payload: RejectMemoryProposalRequest,
  ) => Promise<MemoryProposalResponse>;
}

export function MemoryReviewWorkspace({
  contacts,
  activeContact,
  activeMeeting,
  activeBrief,
  pendingProposals,
  onProposeMemories,
  onApproveProposal,
  onRejectProposal,
}: MemoryReviewWorkspaceProps): JSX.Element {
  const [notes, setNotes] = useState("");
  const [notesError, setNotesError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  const [editingProposalId, setEditingProposalId] = useState<string | null>(null);
  const [editedText, setEditedText] = useState("");
  const [editedType, setEditedType] = useState<MemoryType>("counterpart_background");
  const [editError, setEditError] = useState<string | null>(null);

  const [rejectingProposalId, setRejectingProposalId] = useState<string | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");

  const [busyProposalId, setBusyProposalId] = useState<string | null>(null);

  const contactNameById = new Map<string, string>(contacts.map((c) => [c.id, c.name]));

  const handleExtractSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setFeedback(null);

    const trimmed = notes.trim();
    if (trimmed.length < 5) {
      setNotesError("Enter at least 5 characters of meeting notes.");
      return;
    }
    if (trimmed.length > 10_000) {
      setNotesError("Meeting notes must be 10,000 characters or fewer.");
      return;
    }

    setNotesError(null);
    setExtracting(true);
    try {
      const payload: ProposeMemoriesRequest = {
        notes: trimmed,
        source_type: "meeting_notes",
        contact_id: activeContact?.id ?? null,
        meeting_id: activeMeeting?.id ?? null,
        brief_id: activeBrief?.id ?? null,
      };
      const batch = await onProposeMemories(payload);
      setNotes("");

      const extraNotes: string[] = [];
      if (batch.skipped_duplicates > 0) {
        extraNotes.push(`${String(batch.skipped_duplicates)} duplicate skipped`);
      }
      if (batch.filtered_sensitive_count > 0) {
        extraNotes.push(`${String(batch.filtered_sensitive_count)} sensitive assumption excluded`);
      }
      const suffix = extraNotes.length > 0 ? ` (${extraNotes.join(", ")})` : "";

      setFeedback({
        kind: batch.total > 0 ? "success" : "info",
        title:
          batch.total > 0
            ? `${String(batch.total)} memory ${batch.total === 1 ? "proposal" : "proposals"} staged for review`
            : "No new memory proposals staged",
        message: `Nothing is saved to durable memory until you explicitly approve it${suffix}.`,
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not extract memory proposals"));
    } finally {
      setExtracting(false);
    }
  };

  const handleApprove = async (
    proposal: MemoryProposalResponse,
    withEdits: boolean,
  ): Promise<void> => {
    setFeedback(null);
    setEditError(null);

    let customText: string | null = null;
    let customType: MemoryType | null = null;
    if (withEdits) {
      const trimmed = editedText.trim();
      if (trimmed.length < 3) {
        setEditError("Memory text must be at least 3 characters.");
        return;
      }
      if (trimmed.length > 1000) {
        setEditError("Memory text must be 1,000 characters or fewer.");
        return;
      }
      customText = trimmed;
      customType = editedType;
    }

    setBusyProposalId(proposal.id);
    try {
      const approved = await onApproveProposal(proposal.id, {
        expected_version: proposal.version,
        edited_text: customText,
        memory_type: customType,
        supersedes_memory_id: proposal.supersedes_memory_id,
      });
      setEditingProposalId(null);
      setFeedback({
        kind: "success",
        title: "Memory approved",
        message: approved.supersedes_memory_id
          ? "Saved to active memory and marked the previous conflicting entry as superseded."
          : "Saved to durable memory for future conversation preparation.",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not approve memory proposal"));
    } finally {
      setBusyProposalId(null);
    }
  };

  const handleReject = async (proposal: MemoryProposalResponse): Promise<void> => {
    setFeedback(null);
    setBusyProposalId(proposal.id);
    try {
      await onRejectProposal(proposal.id, {
        expected_version: proposal.version,
        reason: rejectionReason.trim() || null,
      });
      setRejectingProposalId(null);
      setRejectionReason("");
      setFeedback({
        kind: "info",
        title: "Proposal rejected",
        message: "Excluded from active memory and future retrieval.",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not reject memory proposal"));
    } finally {
      setBusyProposalId(null);
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-display text-2xl font-semibold text-[#23170F] sm:text-3xl">
          Post-Meeting Notes &amp; Review
        </h1>
        <p className="text-sm text-[#594638]">
          {activeContact
            ? `Linked to ${activeContact.name}. Candidate takeaways require your explicit approval.`
            : "Submit reflections to propose personal preferences or counterpart memories for human review."}
        </p>
      </header>

      {feedback && (
        <StatusBanner
          notice={feedback}
          onDismiss={() => {
            setFeedback(null);
          }}
        />
      )}

      {/* Post-Meeting Notes Submission Form */}
      <form
        onSubmit={(e) => void handleExtractSubmit(e)}
        noValidate
        aria-labelledby="session-notes-heading"
        className="md-card space-y-4 p-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="session-notes-heading" className="text-lg font-semibold text-[#23170F]">
            Capture Session Notes
          </h2>
          {activeContact && (
            <span className="md-badge md-badge-espresso">{activeContact.name}</span>
          )}
        </div>

        <div>
          <label
            htmlFor="post-meeting-notes-input"
            className="block text-sm font-medium text-[#23170F]"
          >
            Meeting reflections <span className="text-[#9E2A2B]">*</span>
          </label>
          <textarea
            id="post-meeting-notes-input"
            rows={4}
            required
            maxLength={10000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            aria-invalid={notesError ? "true" : "false"}
            aria-describedby={notesError ? "post-meeting-notes-error" : undefined}
            placeholder="e.g., We discussed his team's challenges adopting AI. He recommended learning more about evaluation pipelines. I prefer having informal conversations with engineers."
            className="md-textarea mt-1.5"
          />
          {notesError && (
            <p id="post-meeting-notes-error" role="alert" className="mt-1 text-xs text-[#9E2A2B]">
              {notesError}
            </p>
          )}
        </div>

        <div className="flex justify-end">
          <button
            id="btn-submit-propose-memories"
            type="submit"
            disabled={extracting}
            className="md-btn md-btn-filled"
          >
            {extracting ? "Extracting Proposals..." : "Propose Memory Candidates"}
          </button>
        </div>
      </form>

      {/* Pending Proposals Review Queue */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-[#23170F]">Pending Human Review</h2>
          <span className="md-badge md-badge-neutral font-mono-code">
            {String(pendingProposals.length)} pending
          </span>
        </div>

        {pendingProposals.length === 0 ? (
          <EmptyStateCard
            title="No pending memory proposals"
            description="Proposed counterpart takeaways and personal coaching preferences appear here for review before anything is saved."
          />
        ) : (
          <ul className="space-y-4">
            {pendingProposals.map((proposal) => {
              const isEditing = editingProposalId === proposal.id;
              const isRejecting = rejectingProposalId === proposal.id;
              const isBusy = busyProposalId === proposal.id;
              const counterpartName = proposal.contact_id
                ? contactNameById.get(proposal.contact_id)
                : null;

              return (
                <li key={proposal.id} className="md-card space-y-4 p-5 sm:p-6">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`md-badge ${
                          proposal.scope === "contact" ? "md-badge-espresso" : "md-badge-sage"
                        }`}
                      >
                        {counterpartName
                          ? `${counterpartName} · Counterpart`
                          : formatMemoryScopeLabel(proposal.scope)}
                      </span>
                      <span className="md-badge md-badge-neutral">
                        {formatMemoryTypeLabel(proposal.memory_type)}
                      </span>
                      <span className="md-badge md-badge-neutral">
                        {formatEpistemicLabel(proposal.epistemic_status)}
                      </span>
                    </div>
                    <span className="font-mono-code text-xs text-[#594638]">
                      {formatShortTimestamp(proposal.created_at)}
                    </span>
                  </div>

                  {proposal.conflict_summary && (
                    <div className="rounded-xl border border-[#E5CFA4] bg-[#F8E8CB] px-3.5 py-2.5 text-xs text-[#3F2702]">
                      <strong>Updates existing memory:</strong> {proposal.conflict_summary}
                    </div>
                  )}

                  {!isEditing ? (
                    <p className="text-base font-medium leading-relaxed text-[#23170F]">
                      {proposal.text}
                    </p>
                  ) : (
                    <div className="space-y-3 rounded-xl bg-[#F5EEE4] p-4">
                      <div>
                        <label
                          htmlFor={`edit-proposal-text-${proposal.id}`}
                          className="block text-xs font-semibold text-[#23170F]"
                        >
                          Edit memory text before saving
                        </label>
                        <textarea
                          id={`edit-proposal-text-${proposal.id}`}
                          rows={2}
                          maxLength={1000}
                          value={editedText}
                          onChange={(e) => setEditedText(e.target.value)}
                          aria-invalid={editError ? "true" : "false"}
                          className="md-textarea mt-1"
                        />
                        {editError && (
                          <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                            {editError}
                          </p>
                        )}
                      </div>

                      <div>
                        <label
                          htmlFor={`edit-proposal-type-${proposal.id}`}
                          className="block text-xs font-semibold text-[#23170F]"
                        >
                          Classification
                        </label>
                        <select
                          id={`edit-proposal-type-${proposal.id}`}
                          value={editedType}
                          onChange={(e) => setEditedType(e.target.value as MemoryType)}
                          className="md-select mt-1"
                        >
                          {MEMORY_TYPE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  )}

                  <div className="space-y-1 text-xs text-[#594638]">
                    <p>
                      <strong className="font-semibold text-[#23170F]">Why proposed:</strong>{" "}
                      {proposal.rationale}
                    </p>
                    {proposal.source.excerpt && (
                      <p>
                        <strong className="font-semibold text-[#23170F]">Source note:</strong> “
                        {proposal.source.excerpt}”
                      </p>
                    )}
                  </div>

                  {isRejecting && (
                    <div className="space-y-2.5 rounded-xl border border-[#E6B8B7] bg-[#FCEAE9]/60 p-3.5">
                      <label
                        htmlFor={`reject-reason-${proposal.id}`}
                        className="block text-xs font-semibold text-[#5A1213]"
                      >
                        Optional rejection note
                      </label>
                      <input
                        id={`reject-reason-${proposal.id}`}
                        type="text"
                        maxLength={500}
                        value={rejectionReason}
                        onChange={(e) => setRejectionReason(e.target.value)}
                        placeholder="Why shouldn't Brew save this?"
                        className="md-input"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          disabled={isBusy}
                          onClick={() => {
                            setRejectingProposalId(null);
                            setRejectionReason("");
                          }}
                          className="md-btn md-btn-outlined min-h-9 px-3 text-xs"
                        >
                          Cancel
                        </button>
                        <button
                          id={`btn-confirm-reject-${proposal.id}`}
                          type="button"
                          disabled={isBusy}
                          onClick={() => {
                            void handleReject(proposal);
                          }}
                          className="md-btn md-btn-danger min-h-9 px-3.5 text-xs"
                        >
                          {isBusy ? "Rejecting..." : "Confirm Reject"}
                        </button>
                      </div>
                    </div>
                  )}

                  {!isRejecting && (
                    <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[#E6DACB] pt-3">
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setEditingProposalId(null);
                              setEditError(null);
                            }}
                            className="md-btn md-btn-outlined"
                          >
                            Cancel
                          </button>
                          <button
                            id={`btn-save-edited-proposal-${proposal.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              void handleApprove(proposal, true);
                            }}
                            className="md-btn md-btn-filled"
                          >
                            {isBusy ? "Approving..." : "Approve Edited Memory"}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            id={`btn-reject-proposal-${proposal.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setEditingProposalId(null);
                              setRejectingProposalId(proposal.id);
                              setRejectionReason("");
                            }}
                            className="md-btn md-btn-danger"
                          >
                            Reject
                          </button>
                          <button
                            id={`btn-edit-proposal-${proposal.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setRejectingProposalId(null);
                              setEditingProposalId(proposal.id);
                              setEditedText(proposal.text);
                              setEditedType(proposal.memory_type);
                              setEditError(null);
                            }}
                            className="md-btn md-btn-outlined"
                          >
                            Edit
                          </button>
                          <button
                            id={`btn-approve-proposal-${proposal.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              void handleApprove(proposal, false);
                            }}
                            className="md-btn md-btn-filled"
                          >
                            {isBusy ? "Approving..." : "Approve"}
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
