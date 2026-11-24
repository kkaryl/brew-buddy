import { Check, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import { useState, type JSX } from "react";
import type {
  ApproveMemoryProposalRequest,
  MemoryProposalResponse,
  MemoryResponse,
  MemoryType,
  RejectMemoryProposalRequest,
  UpdateMemoryRequest,
} from "../../api/types";
import {
  MEMORY_TYPE_OPTIONS,
  formatMemoryTypeLabel,
  formatShortTimestamp,
} from "../formatters";
import { FormField, PillButton, PrimaryButton } from "../ui";

export interface KeepsakeProposalCardProps {
  readonly proposal: MemoryProposalResponse;
  readonly counterpartName?: string | null | undefined;
  readonly supersededMemoryText?: string | null | undefined;
  readonly indexLabel?: string | undefined;
  readonly compactMobileLayout?: boolean | undefined;
  readonly onApprove: (
    proposalId: string,
    payload: ApproveMemoryProposalRequest,
  ) => Promise<void>;
  readonly onReject: (
    proposalId: string,
    payload: RejectMemoryProposalRequest,
  ) => Promise<void>;
}

export function KeepsakeProposalCard({
  proposal,
  counterpartName,
  supersededMemoryText,
  indexLabel,
  compactMobileLayout = false,
  onApprove,
  onReject,
}: KeepsakeProposalCardProps): JSX.Element {
  const [isEditing, setIsEditing] = useState(false);
  const [editedText, setEditedText] = useState(proposal.text);
  const [editedType, setEditedType] = useState<MemoryType>(proposal.memory_type);
  const [editError, setEditError] = useState<string | null>(null);
  const [isRejecting, setIsRejecting] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  const isPersonalStyle = proposal.scope === "user_preference";
  const hasSupersession = Boolean(proposal.supersedes_memory_id || proposal.conflict_summary);

  const surfaceClass = isPersonalStyle
    ? "brew-card-mint"
    : hasSupersession
      ? "brew-card-lavender"
      : "brew-card-paper";

  const handleStampKeep = async (withEdits: boolean): Promise<void> => {
    setEditError(null);
    let customText: string | null = null;
    let customType: MemoryType | null = null;

    if (withEdits) {
      const trimmed = editedText.trim();
      if (trimmed.length < 3) {
        setEditError("Keepsake text must be at least 3 characters.");
        return;
      }
      if (trimmed.length > 1000) {
        setEditError("Keepsake text must be 1,000 characters or fewer.");
        return;
      }
      customText = trimmed;
      customType = editedType;
    }

    setIsBusy(true);
    try {
      await onApprove(proposal.id, {
        expected_version: proposal.version,
        edited_text: customText,
        memory_type: customType,
        supersedes_memory_id: proposal.supersedes_memory_id,
      });
      setIsEditing(false);
    } finally {
      setIsBusy(false);
    }
  };

  const handleToss = async (reasonOverride?: string | null): Promise<void> => {
    setIsBusy(true);
    try {
      await onReject(proposal.id, {
        expected_version: proposal.version,
        reason: reasonOverride !== undefined ? reasonOverride : rejectionReason.trim() || null,
      });
      setIsRejecting(false);
    } finally {
      setIsBusy(false);
    }
  };

  const primaryLabel = isPersonalStyle
    ? compactMobileLayout
      ? "Keep"
      : "Save Preference"
    : compactMobileLayout
      ? "Keep"
      : "Stamp Keep";

  return (
    <li className={`min-w-0 rounded-[26px] p-4 sm:p-5 sm:px-6 ${surfaceClass}`}>
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {isPersonalStyle ? (
            <span className="brew-badge-mint bg-brew-paper">My Coaching Style</span>
          ) : (
            <>
              <span className="brew-badge-peach">
                {counterpartName ?? "Counterpart"}
              </span>
              <span className="brew-badge-lavender bg-brew-paper">
                {formatMemoryTypeLabel(proposal.memory_type)}
              </span>
            </>
          )}
        </div>

        <span
          className={`shrink-0 text-xs font-semibold whitespace-nowrap ${
            isPersonalStyle ? "text-[#235744]" : "text-brew-secondary"
          }`}
        >
          {indexLabel ??
            (isPersonalStyle
              ? "Personal preference"
              : formatShortTimestamp(proposal.created_at))}
        </span>
      </div>

      {hasSupersession && (
        <div className="brew-card-yellow mb-2.5 flex items-center gap-2 rounded-[14px] px-3 py-2 text-xs text-[#6B5314]">
          <RefreshCw className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            <strong>Updates prior note:</strong>{" "}
            {supersededMemoryText ? (
              <span className="line-through">“{supersededMemoryText}”</span>
            ) : (
              <span>{proposal.conflict_summary ?? "Replaces earlier keepsake"}</span>
            )}
          </span>
        </div>
      )}

      {!isEditing ? (
        <p className="mb-3 text-[15px] leading-[1.45] font-bold text-brew-plum">
          {proposal.text}
        </p>
      ) : (
        <div className="mb-3 space-y-3 rounded-2xl border border-brew-border bg-brew-paper p-3.5">
          <FormField
            htmlFor={`proposal-edit-text-${proposal.id}`}
            label="Edit keepsake"
            error={editError}
          >
            <textarea
              id={`proposal-edit-text-${proposal.id}`}
              rows={2}
              maxLength={1000}
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
              aria-invalid={editError ? "true" : "false"}
              className="brew-field-control"
            />
          </FormField>

          <FormField
            htmlFor={`proposal-edit-type-${proposal.id}`}
            label="Category"
          >
            <select
              id={`proposal-edit-type-${proposal.id}`}
              value={editedType}
              onChange={(e) => setEditedType(e.target.value as MemoryType)}
              className="brew-field-control"
            >
              {MEMORY_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </FormField>
        </div>
      )}

      {isRejecting && (
        <div className="mb-3 space-y-2.5 rounded-2xl border border-[#F2C2BA] bg-[#FFF5F3] p-3.5">
          <FormField
            htmlFor={`proposal-reject-reason-${proposal.id}`}
            label="Optional reason to toss"
          >
            <input
              id={`proposal-reject-reason-${proposal.id}`}
              type="text"
              maxLength={300}
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="e.g., Temporary detail, no need to remember"
              className="brew-field-control"
            />
          </FormField>
          <div className="flex justify-end gap-2">
            <PillButton
              variant="outline"
              size="sm"
              disabled={isBusy}
              onClick={() => setIsRejecting(false)}
            >
              Cancel
            </PillButton>
            <PillButton
              id={`btn-confirm-reject-${proposal.id}`}
              variant="danger"
              size="sm"
              disabled={isBusy}
              onClick={() => {
                void handleToss();
              }}
            >
              {isBusy ? "Tossing..." : "Confirm Toss"}
            </PillButton>
          </div>
        </div>
      )}

      {!isRejecting && (
        <div
          className={`flex flex-wrap items-center justify-between gap-2.5 ${
            hasSupersession ? "border-t border-[#DFD2FA] pt-3" : "pt-1"
          }`}
        >
          {proposal.source.excerpt && !compactMobileLayout ? (
            <span className="max-w-[46%] truncate text-xs text-brew-secondary">
              From: <em>“{proposal.source.excerpt}”</em>
            </span>
          ) : (
            <span />
          )}

          {isEditing ? (
            <div className="flex flex-wrap items-center gap-2">
              <PillButton
                variant="outline"
                size="sm"
                disabled={isBusy}
                onClick={() => {
                  setIsEditing(false);
                  setEditError(null);
                }}
              >
                Cancel
              </PillButton>
              <PrimaryButton
                id={`btn-save-approve-proposal-${proposal.id}`}
                shape="pill"
                loading={isBusy}
                onClick={() => {
                  void handleStampKeep(true);
                }}
                className="min-h-[38px] px-4 py-1.5 text-xs"
              >
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{isBusy ? "Saving..." : "Save & Stamp Keep"}</span>
              </PrimaryButton>
            </div>
          ) : (
            <div
              className={
                compactMobileLayout
                  ? "grid w-full grid-cols-[1fr_1fr_1.4fr] gap-2"
                  : "flex flex-wrap items-center gap-2"
              }
            >
              <PillButton
                id={`btn-reject-proposal-${proposal.id}`}
                variant="danger"
                size="sm"
                disabled={isBusy}
                onClick={() => {
                  setIsEditing(false);
                  setIsRejecting(true);
                }}
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Toss</span>
              </PillButton>

              <PillButton
                id={`btn-edit-proposal-${proposal.id}`}
                variant="outline"
                size="sm"
                disabled={isBusy}
                onClick={() => {
                  setIsRejecting(false);
                  setEditedText(proposal.text);
                  setEditedType(proposal.memory_type);
                  setEditError(null);
                  setIsEditing(true);
                }}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Edit</span>
              </PillButton>

              <PrimaryButton
                id={`btn-approve-proposal-${proposal.id}`}
                shape="pill"
                loading={isBusy}
                onClick={() => {
                  void handleStampKeep(false);
                }}
                className="min-h-[38px] px-4 py-1.5 text-xs"
              >
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{isBusy ? "Stamping..." : primaryLabel}</span>
              </PrimaryButton>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export interface ApprovedKeepsakeCardProps {
  readonly memory: MemoryResponse;
  readonly index: number;
  readonly counterpartName?: string | null | undefined;
  readonly onUpdate: (memoryId: string, payload: UpdateMemoryRequest) => Promise<void>;
  readonly onDelete: (memoryId: string, expectedVersion: number) => Promise<void>;
}

export function ApprovedKeepsakeCard({
  memory,
  index,
  counterpartName,
  onUpdate,
  onDelete,
}: ApprovedKeepsakeCardProps): JSX.Element {
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(memory.text);
  const [editType, setEditType] = useState<MemoryType>(memory.memory_type);
  const [editError, setEditError] = useState<string | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  const isSuperseded = memory.lifecycle_state === "superseded";

  if (isSuperseded) {
    return (
      <li className="brew-card-blush col-span-full flex flex-wrap items-center justify-between gap-3 rounded-[20px] px-4.5 py-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="brew-badge-yellow">
            Replaced {formatShortTimestamp(memory.superseded_at ?? memory.updated_at)}
          </span>
          <span className="text-[13px] text-brew-secondary line-through">{memory.text}</span>
        </div>
        <span className="text-xs font-medium whitespace-nowrap text-brew-secondary">
          Archived
        </span>
      </li>
    );
  }

  const toneClass =
    memory.scope === "user_preference"
      ? "brew-card-mint"
      : index % 2 === 0
        ? "brew-card-lavender"
        : "brew-card-mint";

  const handleSave = async (): Promise<void> => {
    const trimmed = editText.trim();
    if (trimmed.length < 3) {
      setEditError("Keepsake text must be at least 3 characters.");
      return;
    }
    if (trimmed.length > 1000) {
      setEditError("Keepsake text must be 1,000 characters or fewer.");
      return;
    }
    setEditError(null);
    setIsBusy(true);
    try {
      await onUpdate(memory.id, {
        expected_version: memory.version,
        text: trimmed,
        memory_type: editType,
      });
      setIsEditing(false);
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = async (): Promise<void> => {
    setIsBusy(true);
    try {
      await onDelete(memory.id, memory.version);
      setIsConfirmingDelete(false);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <li className={`flex min-w-0 flex-col justify-between gap-3 rounded-[22px] p-4.5 ${toneClass}`}>
      <div className="space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <span
            className={
              index % 2 === 0 && memory.scope !== "user_preference"
                ? "brew-badge-peach bg-brew-paper"
                : "brew-badge-mint bg-brew-paper"
            }
          >
            {counterpartName
              ? `${counterpartName} · ${formatMemoryTypeLabel(memory.memory_type)}`
              : formatMemoryTypeLabel(memory.memory_type)}
          </span>
          <span className="shrink-0 font-mono-code text-[11px] whitespace-nowrap text-brew-secondary">
            {formatShortTimestamp(memory.updated_at)}
          </span>
        </div>

        {!isEditing ? (
          <p className="text-[14px] leading-[1.45] font-semibold text-brew-plum">
            {memory.text}
          </p>
        ) : (
          <div className="space-y-2.5 rounded-2xl border border-brew-border bg-brew-paper p-3">
            <FormField
              htmlFor={`edit-memory-text-${memory.id}`}
              label="Keepsake statement"
              error={editError}
            >
              <textarea
                id={`edit-memory-text-${memory.id}`}
                rows={2}
                maxLength={1000}
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                aria-invalid={editError ? "true" : "false"}
                className="brew-field-control"
              />
            </FormField>

            <FormField
              htmlFor={`edit-memory-type-${memory.id}`}
              label="Category"
            >
              <select
                id={`edit-memory-type-${memory.id}`}
                value={editType}
                onChange={(e) => setEditType(e.target.value as MemoryType)}
                className="brew-field-control"
              >
                {MEMORY_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </FormField>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-brew-secondary">
        <span>{formatShortTimestamp(memory.source.recorded_at)} chat</span>

        {isEditing ? (
          <div className="flex items-center gap-1.5">
            <PillButton
              variant="outline"
              size="sm"
              disabled={isBusy}
              onClick={() => {
                setIsEditing(false);
                setEditError(null);
              }}
            >
              Cancel
            </PillButton>
            <PrimaryButton
              id={`btn-save-memory-${memory.id}`}
              shape="pill"
              loading={isBusy}
              onClick={() => {
                void handleSave();
              }}
              className="min-h-[34px] px-3.5 py-1 text-xs"
            >
              {isBusy ? "Saving..." : "Save"}
            </PrimaryButton>
          </div>
        ) : isConfirmingDelete ? (
          <div className="flex items-center gap-1.5">
            <PillButton
              variant="outline"
              size="sm"
              disabled={isBusy}
              onClick={() => setIsConfirmingDelete(false)}
            >
              Cancel
            </PillButton>
            <PillButton
              id={`btn-confirm-delete-memory-${memory.id}`}
              variant="danger"
              size="sm"
              disabled={isBusy}
              onClick={() => {
                void handleDelete();
              }}
            >
              <Trash2 className="h-3 w-3" aria-hidden="true" />
              <span>{isBusy ? "Deleting..." : "Confirm Delete"}</span>
            </PillButton>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              id={`btn-edit-memory-${memory.id}`}
              type="button"
              onClick={() => {
                setIsConfirmingDelete(false);
                setEditText(memory.text);
                setEditType(memory.memory_type);
                setEditError(null);
                setIsEditing(true);
              }}
              className="cursor-pointer font-semibold text-brew-secondary transition hover:text-brew-plum"
            >
              Edit
            </button>
            <span aria-hidden="true">·</span>
            <button
              id={`btn-delete-memory-${memory.id}`}
              type="button"
              onClick={() => {
                setIsEditing(false);
                setIsConfirmingDelete(true);
              }}
              className="cursor-pointer font-semibold text-brew-secondary transition hover:text-[#9E3426]"
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </li>
  );
}
