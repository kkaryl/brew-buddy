import { useState, type JSX } from "react";
import type {
  ContactResponse,
  MemoryResponse,
  MemoryType,
  UpdateMemoryRequest,
} from "../api/types";
import {
  MEMORY_TYPE_OPTIONS,
  errorToFeedbackNotice,
  formatEpistemicLabel,
  formatLifecycleLabel,
  formatMemoryScopeLabel,
  formatMemoryTypeLabel,
  formatShortTimestamp,
  formatSourceTypeLabel,
  type FeedbackNotice,
} from "./formatters";
import { EmptyStateCard, StatusBanner } from "./StatusFeedback";

type ScopeTab = "all" | "contact" | "user_preference";

export interface MemoryVaultWorkspaceProps {
  readonly contacts: readonly ContactResponse[];
  readonly activeContact: ContactResponse | null;
  readonly memories: readonly MemoryResponse[];
  readonly includeSuperseded: boolean;
  readonly onToggleIncludeSuperseded: (next: boolean) => void;
  readonly onUpdateMemory: (
    memoryId: string,
    payload: UpdateMemoryRequest,
  ) => Promise<MemoryResponse>;
  readonly onDeleteMemory: (memoryId: string, expectedVersion: number) => Promise<void>;
}

export function MemoryVaultWorkspace({
  contacts,
  activeContact,
  memories,
  includeSuperseded,
  onToggleIncludeSuperseded,
  onUpdateMemory,
  onDeleteMemory,
}: MemoryVaultWorkspaceProps): JSX.Element {
  const [scopeTab, setScopeTab] = useState<ScopeTab>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editType, setEditType] = useState<MemoryType>("counterpart_background");
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  const contactNameById = new Map<string, string>(contacts.map((c) => [c.id, c.name]));

  const filteredMemories = memories.filter((mem) => {
    if (scopeTab === "user_preference") {
      return mem.scope === "user_preference";
    }
    if (scopeTab === "contact") {
      if (activeContact) {
        return mem.scope === "contact" && mem.contact_id === activeContact.id;
      }
      return mem.scope === "contact";
    }
    return true;
  });

  const handleSaveUpdate = async (memory: MemoryResponse): Promise<void> => {
    setFeedback(null);
    const trimmed = editText.trim();
    if (trimmed.length < 3) {
      setEditError("Memory text must be at least 3 characters.");
      return;
    }
    if (trimmed.length > 1000) {
      setEditError("Memory text must be 1,000 characters or fewer.");
      return;
    }

    setEditError(null);
    setBusyId(memory.id);
    try {
      await onUpdateMemory(memory.id, {
        expected_version: memory.version,
        text: trimmed,
        memory_type: editType,
      });
      setEditingId(null);
      setFeedback({
        kind: "success",
        title: "Memory updated",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not update memory"));
    } finally {
      setBusyId(null);
    }
  };

  const handleConfirmDelete = async (memory: MemoryResponse): Promise<void> => {
    setFeedback(null);
    setBusyId(memory.id);
    try {
      await onDeleteMemory(memory.id, memory.version);
      setConfirmDeleteId(null);
      setFeedback({
        kind: "info",
        title: "Memory deleted",
        message: "Removed from active storage and excluded from future coaching sessions.",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not delete memory"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="font-display text-2xl font-semibold text-[#23170F] sm:text-3xl">
            Relationship Memory
          </h1>
          <p className="mt-1 text-sm text-[#594638]">
            Approved context and preferences that ground future session preparation.
          </p>
        </div>

        <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-[#594638]">
          <input
            id="toggle-include-superseded"
            type="checkbox"
            checked={includeSuperseded}
            onChange={(e) => onToggleIncludeSuperseded(e.target.checked)}
            className="h-4 w-4 rounded border-[#857060] accent-[#4A2E1B]"
          />
          <span>Show superseded history</span>
        </label>
      </header>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Memory scope">
        <button
          id="tab-memories-all"
          role="tab"
          aria-selected={scopeTab === "all"}
          type="button"
          onClick={() => setScopeTab("all")}
          className={`md-chip ${scopeTab === "all" ? "md-chip-active" : ""}`}
        >
          All ({String(memories.length)})
        </button>
        <button
          id="tab-memories-contact"
          role="tab"
          aria-selected={scopeTab === "contact"}
          type="button"
          onClick={() => setScopeTab("contact")}
          className={`md-chip ${scopeTab === "contact" ? "md-chip-active" : ""}`}
        >
          {activeContact ? activeContact.name : "Counterparts"}
        </button>
        <button
          id="tab-memories-preferences"
          role="tab"
          aria-selected={scopeTab === "user_preference"}
          type="button"
          onClick={() => setScopeTab("user_preference")}
          className={`md-chip ${scopeTab === "user_preference" ? "md-chip-active" : ""}`}
        >
          Personal Preferences
        </button>
      </div>

      {feedback && (
        <StatusBanner
          notice={feedback}
          onDismiss={() => {
            setFeedback(null);
          }}
        />
      )}

      {filteredMemories.length === 0 ? (
        <EmptyStateCard
          title="No approved memories yet"
          description="Once you approve post-meeting proposals, they appear here with full provenance and can be edited or deleted anytime."
        />
      ) : (
        <ul className="space-y-4">
          {filteredMemories.map((memory) => {
            const isSuperseded = memory.lifecycle_state === "superseded";
            const isEditing = editingId === memory.id;
            const isConfirmingDelete = confirmDeleteId === memory.id;
            const isBusy = busyId === memory.id;
            const counterpartName = memory.contact_id
              ? contactNameById.get(memory.contact_id)
              : null;

            return (
              <li
                key={memory.id}
                className={`md-card space-y-3.5 p-5 sm:p-6 ${isSuperseded ? "opacity-75" : ""}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`md-badge ${
                        memory.scope === "contact" ? "md-badge-espresso" : "md-badge-sage"
                      }`}
                    >
                      {counterpartName
                        ? `${counterpartName} · Counterpart`
                        : formatMemoryScopeLabel(memory.scope)}
                    </span>
                    <span className="md-badge md-badge-neutral">
                      {formatMemoryTypeLabel(memory.memory_type)}
                    </span>
                    <span className="md-badge md-badge-neutral">
                      {formatEpistemicLabel(memory.epistemic_status)}
                    </span>
                    {isSuperseded && (
                      <span className="md-badge md-badge-amber">
                        {formatLifecycleLabel(memory.lifecycle_state)}
                      </span>
                    )}
                  </div>
                  <span className="font-mono-code text-xs text-[#594638]">
                    v{String(memory.version)} · {formatShortTimestamp(memory.updated_at)}
                  </span>
                </div>

                {!isEditing ? (
                  <p className="text-sm font-medium leading-relaxed text-[#23170F] sm:text-base">
                    {memory.text}
                  </p>
                ) : (
                  <div className="space-y-3 rounded-xl bg-[#F5EEE4] p-4">
                    <div>
                      <label
                        htmlFor={`edit-memory-text-${memory.id}`}
                        className="block text-xs font-semibold text-[#23170F]"
                      >
                        Memory statement
                      </label>
                      <textarea
                        id={`edit-memory-text-${memory.id}`}
                        rows={2}
                        maxLength={1000}
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
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
                        htmlFor={`edit-memory-type-${memory.id}`}
                        className="block text-xs font-semibold text-[#23170F]"
                      >
                        Classification
                      </label>
                      <select
                        id={`edit-memory-type-${memory.id}`}
                        value={editType}
                        onChange={(e) => setEditType(e.target.value as MemoryType)}
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

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E6DACB] pt-3 text-xs text-[#594638]">
                  <div className="space-y-0.5">
                    <span>
                      Source: {formatSourceTypeLabel(memory.source.source_type)} (
                      {formatShortTimestamp(memory.source.recorded_at)})
                    </span>
                    {memory.source.excerpt && (
                      <p className="italic text-[#594638]">“{memory.source.excerpt}”</p>
                    )}
                  </div>

                  {!isSuperseded && (
                    <div className="flex flex-wrap items-center gap-2">
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setEditingId(null);
                              setEditError(null);
                            }}
                            className="md-btn md-btn-outlined min-h-9 px-3 text-xs"
                          >
                            Cancel
                          </button>
                          <button
                            id={`btn-save-memory-${memory.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              void handleSaveUpdate(memory);
                            }}
                            className="md-btn md-btn-filled min-h-9 px-3.5 text-xs"
                          >
                            {isBusy ? "Saving..." : "Save"}
                          </button>
                        </>
                      ) : isConfirmingDelete ? (
                        <>
                          <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => setConfirmDeleteId(null)}
                            className="md-btn md-btn-outlined min-h-9 px-3 text-xs"
                          >
                            Cancel
                          </button>
                          <button
                            id={`btn-confirm-delete-memory-${memory.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              void handleConfirmDelete(memory);
                            }}
                            className="md-btn md-btn-danger min-h-9 px-3.5 text-xs"
                          >
                            {isBusy ? "Deleting..." : "Confirm Delete"}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            id={`btn-edit-memory-${memory.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setConfirmDeleteId(null);
                              setEditingId(memory.id);
                              setEditText(memory.text);
                              setEditType(memory.memory_type);
                              setEditError(null);
                            }}
                            className="md-btn md-btn-outlined min-h-9 px-3 text-xs"
                          >
                            Edit
                          </button>
                          <button
                            id={`btn-delete-memory-${memory.id}`}
                            type="button"
                            disabled={isBusy}
                            onClick={() => {
                              setEditingId(null);
                              setConfirmDeleteId(memory.id);
                            }}
                            className="md-btn md-btn-danger min-h-9 px-3 text-xs"
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
