import { useEffect, useState, type FormEvent, type JSX } from "react";
import { BrewApiError } from "../api/client";
import type {
  ContactResponse,
  GenerateBriefRequest,
  MeetingPurpose,
  MeetingResponse,
  MeetingTone,
  PreparationBriefResponse,
  ReviseBriefRequest,
} from "../api/types";
import {
  DURATION_PRESETS,
  MEETING_PURPOSE_OPTIONS,
  MEETING_TONE_OPTIONS,
  errorToFeedbackNotice,
  formatPurposeLabel,
  formatShortTimestamp,
  formatToneLabel,
  validateBriefGenerationForm,
  type BriefGenerationFieldErrors,
  type FeedbackNotice,
} from "./formatters";
import { EmptyStateCard, LoadingCard, StatusBanner } from "./StatusFeedback";

const QUICK_REFINEMENT_PROMPTS: readonly {
  readonly label: string;
  readonly instruction: string;
  readonly durationOverride?: number;
  readonly toneOverride?: MeetingTone;
}[] = [
  {
    label: "15-minute trim",
    instruction: "I only have 15 minutes. Tighten the agenda and keep the highest-impact questions.",
    durationOverride: 15,
  },
  {
    label: "Less formal tone",
    instruction: "Make the questions less formal and more conversational.",
    toneOverride: "warm_casual",
  },
  {
    label: "Engineering career focus",
    instruction: "Focus more on their engineering career path and technical trade-offs.",
  },
  {
    label: "Customer discovery",
    instruction: "Give me more customer discovery questions focused on concrete workflow pain points.",
  },
];

export interface PrepareWorkspaceProps {
  readonly activeContact: ContactResponse | null;
  readonly meetings: readonly MeetingResponse[];
  readonly activeBrief: PreparationBriefResponse | null;
  readonly briefRevisions: readonly PreparationBriefResponse[];
  readonly loadingWorkspace: boolean;
  readonly onOpenNewContact: () => void;
  readonly onSelectMeetingBrief: (briefId: string) => Promise<void>;
  readonly onGenerateBrief: (payload: GenerateBriefRequest) => Promise<PreparationBriefResponse>;
  readonly onReviseBrief: (
    briefId: string,
    payload: ReviseBriefRequest,
  ) => Promise<PreparationBriefResponse>;
  readonly onReloadBrief: (briefId: string) => Promise<void>;
  readonly onJumpToPostMeetingNotes: () => void;
}

export function PrepareWorkspace({
  activeContact,
  meetings,
  activeBrief,
  briefRevisions,
  loadingWorkspace,
  onOpenNewContact,
  onSelectMeetingBrief,
  onGenerateBrief,
  onReviseBrief,
  onReloadBrief,
  onJumpToPostMeetingNotes,
}: PrepareWorkspaceProps): JSX.Element {
  const [showNewBriefForm, setShowNewBriefForm] = useState(false);
  const [selectedRevisionVersion, setSelectedRevisionVersion] = useState<number | null>(null);

  // Brief generation form state
  const [purpose, setPurpose] = useState<MeetingPurpose>("coffee_chat");
  const [tone, setTone] = useState<MeetingTone>("warm_casual");
  const [durationMinutes, setDurationMinutes] = useState<number>(30);
  const [meetingObjective, setMeetingObjective] = useState("");
  const [meetingNotes, setMeetingNotes] = useState("");
  const [showAdvancedPrefs, setShowAdvancedPrefs] = useState(false);
  const [preferredQuestionCount, setPreferredQuestionCount] = useState("");
  const [communicationStyleNotes, setCommunicationStyleNotes] = useState("");
  const [focusAreasRaw, setFocusAreasRaw] = useState("");
  const [genFieldErrors, setGenFieldErrors] = useState<BriefGenerationFieldErrors>({});
  const [generating, setGenerating] = useState(false);

  // Brief refinement form state
  const [revisionInstructions, setRevisionInstructions] = useState("");
  const [revisionDurationOverride, setRevisionDurationOverride] = useState<string>("");
  const [revisionToneOverride, setRevisionToneOverride] = useState<MeetingTone | "">("");
  const [revisionFieldError, setRevisionFieldError] = useState<string | null>(null);
  const [revising, setRevising] = useState(false);
  const [versionConflictBriefId, setVersionConflictBriefId] = useState<string | null>(null);

  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  const activeContactId = activeContact?.id ?? null;
  const activeBriefId = activeBrief?.id ?? null;
  const hasActiveBrief = activeBrief !== null;

  useEffect(() => {
    setSelectedRevisionVersion(null);
    setVersionConflictBriefId(null);
    setFeedback(null);
    setShowNewBriefForm(!hasActiveBrief);
  }, [activeContactId, activeBriefId, hasActiveBrief]);

  if (!activeContact) {
    return (
      <section className="space-y-6">
        <header>
          <h1 className="font-display text-2xl font-semibold text-[#23170F] sm:text-3xl">
            Meeting Preparation
          </h1>
        </header>
        <EmptyStateCard
          title="Add a counterpart to begin"
          description="Save who you are meeting so Brew can tailor your conversation openers, time-boxed agenda, and prioritized questions."
          actionLabel="New Counterpart"
          actionId="btn-empty-new-contact"
          onAction={onOpenNewContact}
        />
      </section>
    );
  }

  const displayedBrief: PreparationBriefResponse | null =
    selectedRevisionVersion !== null
      ? (briefRevisions.find((rev) => rev.version === selectedRevisionVersion) ?? activeBrief)
      : activeBrief;

  const isViewingHistoricalRevision =
    displayedBrief !== null &&
    activeBrief !== null &&
    displayedBrief.version !== activeBrief.version;

  const handleGenerateSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setFeedback(null);

    const validation = validateBriefGenerationForm({
      meetingObjective,
      durationMinutes,
      preferredQuestionCount,
      communicationStyleNotes,
    });
    setGenFieldErrors(validation);
    if (Object.keys(validation).length > 0) {
      return;
    }

    const parsedQuestionCount = preferredQuestionCount.trim()
      ? Number.parseInt(preferredQuestionCount.trim(), 10)
      : null;
    const focusTags = focusAreasRaw
      .split(",")
      .map((tag) => tag.trim())
      .filter((tag) => tag.length >= 2)
      .slice(0, 10);
    const trimmedStyleNotes = communicationStyleNotes.trim();
    const hasPreferences =
      parsedQuestionCount !== null || trimmedStyleNotes.length > 0 || focusTags.length > 0;

    setGenerating(true);
    try {
      const payload: GenerateBriefRequest = {
        contact_id: activeContact.id,
        purpose,
        tone,
        meeting_objective: meetingObjective.trim(),
        duration_minutes: durationMinutes,
        meeting_notes: meetingNotes.trim() || null,
        preferences: hasPreferences
          ? {
              preferred_question_count: parsedQuestionCount,
              communication_style_notes: trimmedStyleNotes || null,
              focus_areas: focusTags.length > 0 ? focusTags : null,
            }
          : null,
      };
      const created = await onGenerateBrief(payload);
      setShowNewBriefForm(false);
      setSelectedRevisionVersion(null);
      setMeetingObjective("");
      setMeetingNotes("");
      setFeedback({
        kind: "success",
        title: `Preparation brief v${String(created.version)} ready`,
        message: `${String(created.duration_minutes)}-minute ${formatToneLabel(created.tone).toLowerCase()} plan created.`,
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Brief generation failed"));
    } finally {
      setGenerating(false);
    }
  };

  const handleReviseSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!activeBrief) {
      return;
    }
    setFeedback(null);
    setVersionConflictBriefId(null);

    const trimmedInstructions = revisionInstructions.trim();
    if (trimmedInstructions.length < 3) {
      setRevisionFieldError("Enter revision instructions (at least 3 characters).");
      return;
    }
    if (trimmedInstructions.length > 1000) {
      setRevisionFieldError("Revision instructions must be 1,000 characters or fewer.");
      return;
    }

    let parsedDurationOverride: number | null = null;
    if (revisionDurationOverride.trim()) {
      const candidate = Number.parseInt(revisionDurationOverride.trim(), 10);
      if (!Number.isInteger(candidate) || candidate < 5 || candidate > 180) {
        setRevisionFieldError("Updated duration must be between 5 and 180 minutes.");
        return;
      }
      parsedDurationOverride = candidate;
    }

    setRevisionFieldError(null);
    setRevising(true);
    try {
      const payload: ReviseBriefRequest = {
        instructions: trimmedInstructions,
        expected_version: activeBrief.version,
        duration_minutes: parsedDurationOverride,
        tone: revisionToneOverride || null,
      };
      const updated = await onReviseBrief(activeBrief.id, payload);
      setRevisionInstructions("");
      setRevisionDurationOverride("");
      setRevisionToneOverride("");
      setSelectedRevisionVersion(null);
      setFeedback({
        kind: "success",
        title: `Updated to revision v${String(updated.version)}`,
        message:
          updated.revision_summary ??
          "Previous revision remains preserved in your revision history.",
      });
    } catch (err: unknown) {
      if (err instanceof BrewApiError && err.isVersionConflict) {
        setVersionConflictBriefId(activeBrief.id);
      }
      setFeedback(errorToFeedbackNotice(err, "Brief refinement failed"));
    } finally {
      setRevising(false);
    }
  };

  const meetingsWithBriefs = meetings.filter(
    (m): m is MeetingResponse & { readonly latest_brief_id: string } =>
      typeof m.latest_brief_id === "string" && m.latest_brief_id.length > 0,
  );

  return (
    <section className="space-y-6">
      {/* Counterpart Header */}
      <header className="md-card flex flex-col justify-between gap-4 p-5 sm:flex-row sm:items-center sm:p-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-2xl font-semibold text-[#23170F] sm:text-3xl">
              {activeContact.name}
            </h1>
            {activeContact.role && (
              <span className="md-badge md-badge-espresso">{activeContact.role}</span>
            )}
          </div>
          {(activeContact.title || activeContact.organization) && (
            <p className="text-sm font-medium text-[#594638]">
              {[activeContact.title, activeContact.organization].filter(Boolean).join(" · ")}
            </p>
          )}
          {activeContact.context_notes && (
            <p className="pt-1 text-sm text-[#594638]">{activeContact.context_notes}</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {activeBrief && (
            <button
              id="btn-toggle-new-brief-form"
              type="button"
              onClick={() => setShowNewBriefForm((prev) => !prev)}
              className="md-btn md-btn-outlined"
            >
              {showNewBriefForm ? "View Current Brief" : "New Meeting Brief"}
            </button>
          )}
          <button
            id="btn-capture-notes-shortcut"
            type="button"
            onClick={onJumpToPostMeetingNotes}
            className="md-btn md-btn-tonal"
          >
            Log Post-Meeting Notes
          </button>
        </div>
      </header>

      {/* Saved Meeting Switcher when multiple meetings exist for this contact */}
      {meetingsWithBriefs.length > 1 && !showNewBriefForm && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Recent meetings">
          <span className="text-xs font-semibold text-[#594638]">Sessions:</span>
          {meetingsWithBriefs.map((mtg) => {
            const isSelected = activeBrief?.id === mtg.latest_brief_id;
            return (
              <button
                key={mtg.id}
                type="button"
                onClick={() => {
                  void onSelectMeetingBrief(mtg.latest_brief_id);
                }}
                className={`md-chip ${isSelected ? "md-chip-active" : ""}`}
              >
                <span>{formatPurposeLabel(mtg.purpose)}</span>
                <span className="font-mono-code text-xs opacity-80">
                  {String(mtg.duration_minutes)}m
                </span>
              </button>
            );
          })}
        </div>
      )}

      {feedback && (
        <StatusBanner
          notice={feedback}
          onDismiss={() => {
            setFeedback(null);
          }}
        />
      )}

      {versionConflictBriefId && (
        <div className="md-card-tonal flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 text-sm">
          <span className="text-[#23170F]">
            A newer revision of this brief exists on the server.
          </span>
          <button
            id="btn-reload-conflicted-brief"
            type="button"
            onClick={() => {
              void onReloadBrief(versionConflictBriefId);
              setVersionConflictBriefId(null);
            }}
            className="md-btn md-btn-filled"
          >
            Reload Latest Version
          </button>
        </div>
      )}

      {loadingWorkspace && <LoadingCard label="Loading counterpart preparation..." />}

      {/* Generate Preparation Brief Form */}
      {!loadingWorkspace && (showNewBriefForm || !displayedBrief) && (
        <form
          onSubmit={(e) => void handleGenerateSubmit(e)}
          noValidate
          aria-labelledby="generate-brief-heading"
          className="md-card space-y-5 p-6 sm:p-7"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 id="generate-brief-heading" className="text-lg font-semibold text-[#23170F]">
              Prepare a Conversation Brief
            </h2>
            {activeBrief && (
              <button
                type="button"
                onClick={() => setShowNewBriefForm(false)}
                className="md-btn md-btn-text min-h-8 px-3 py-1 text-xs"
              >
                Close
              </button>
            )}
          </div>

          {/* Meeting Purpose */}
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-[#23170F]">Meeting purpose</legend>
            <div className="flex flex-wrap gap-2">
              {MEETING_PURPOSE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  id={`chip-purpose-${opt.value}`}
                  type="button"
                  aria-pressed={purpose === opt.value}
                  onClick={() => setPurpose(opt.value)}
                  className={`md-chip ${purpose === opt.value ? "md-chip-active" : ""}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </fieldset>

          {/* Duration & Tone */}
          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <label
                htmlFor="brief-duration-input"
                className="block text-sm font-medium text-[#23170F]"
              >
                Duration (minutes)
              </label>
              <div className="flex flex-wrap items-center gap-2">
                {DURATION_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    id={`chip-duration-${String(preset)}`}
                    type="button"
                    aria-pressed={durationMinutes === preset}
                    onClick={() => setDurationMinutes(preset)}
                    className={`md-chip ${durationMinutes === preset ? "md-chip-active" : ""}`}
                  >
                    {String(preset)}m
                  </button>
                ))}
                <input
                  id="brief-duration-input"
                  name="duration_minutes"
                  type="number"
                  min={5}
                  max={180}
                  value={Number.isNaN(durationMinutes) ? "" : String(durationMinutes)}
                  onChange={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    setDurationMinutes(Number.isNaN(parsed) ? 0 : parsed);
                  }}
                  aria-invalid={genFieldErrors.duration_minutes ? "true" : "false"}
                  aria-describedby={
                    genFieldErrors.duration_minutes ? "brief-duration-error" : undefined
                  }
                  className="md-input w-24 font-mono-code"
                />
              </div>
              {genFieldErrors.duration_minutes && (
                <p id="brief-duration-error" role="alert" className="text-xs text-[#9E2A2B]">
                  {genFieldErrors.duration_minutes}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <label htmlFor="brief-tone-select" className="block text-sm font-medium text-[#23170F]">
                Conversation tone
              </label>
              <select
                id="brief-tone-select"
                name="tone"
                value={tone}
                onChange={(e) => setTone(e.target.value as MeetingTone)}
                className="md-select"
              >
                {MEETING_TONE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Objective */}
          <div>
            <label
              htmlFor="brief-objective-input"
              className="block text-sm font-medium text-[#23170F]"
            >
              Meeting objective <span className="text-[#9E2A2B]">*</span>
            </label>
            <textarea
              id="brief-objective-input"
              name="meeting_objective"
              rows={2}
              required
              maxLength={500}
              value={meetingObjective}
              onChange={(e) => setMeetingObjective(e.target.value)}
              aria-invalid={genFieldErrors.meeting_objective ? "true" : "false"}
              aria-describedby={
                genFieldErrors.meeting_objective ? "brief-objective-error" : undefined
              }
              placeholder="e.g., Learn how Alex's team evaluates production LLM pipelines and align on practical career lessons."
              className="md-textarea mt-1.5"
            />
            {genFieldErrors.meeting_objective && (
              <p id="brief-objective-error" role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                {genFieldErrors.meeting_objective}
              </p>
            )}
          </div>

          {/* Optional Session Notes & Coaching Preferences */}
          <div className="border-t border-[#E6DACB] pt-4">
            <button
              id="btn-toggle-brief-preferences"
              type="button"
              aria-expanded={showAdvancedPrefs}
              onClick={() => setShowAdvancedPrefs((prev) => !prev)}
              className="md-btn md-btn-text min-h-9 px-2 text-xs"
            >
              {showAdvancedPrefs ? "Hide optional notes & preferences" : "Add session notes or preferences"}
            </button>

            {showAdvancedPrefs && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label
                    htmlFor="brief-notes-input"
                    className="block text-sm font-medium text-[#23170F]"
                  >
                    Additional meeting context
                  </label>
                  <textarea
                    id="brief-notes-input"
                    rows={2}
                    maxLength={5000}
                    value={meetingNotes}
                    onChange={(e) => setMeetingNotes(e.target.value)}
                    placeholder="Specific topics, shared articles, or constraints for this meeting."
                    className="md-textarea mt-1.5"
                  />
                </div>

                <div>
                  <label
                    htmlFor="pref-question-count-input"
                    className="block text-sm font-medium text-[#23170F]"
                  >
                    Question count (1–15)
                  </label>
                  <input
                    id="pref-question-count-input"
                    type="number"
                    min={1}
                    max={15}
                    value={preferredQuestionCount}
                    onChange={(e) => setPreferredQuestionCount(e.target.value)}
                    aria-invalid={genFieldErrors.preferred_question_count ? "true" : "false"}
                    placeholder="5–8 default"
                    className="md-input mt-1.5 font-mono-code"
                  />
                  {genFieldErrors.preferred_question_count && (
                    <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                      {genFieldErrors.preferred_question_count}
                    </p>
                  )}
                </div>

                <div>
                  <label
                    htmlFor="pref-focus-areas-input"
                    className="block text-sm font-medium text-[#23170F]"
                  >
                    Focus areas (comma-separated)
                  </label>
                  <input
                    id="pref-focus-areas-input"
                    type="text"
                    value={focusAreasRaw}
                    onChange={(e) => setFocusAreasRaw(e.target.value)}
                    placeholder="e.g., evaluation pipelines, career growth"
                    className="md-input mt-1.5"
                  />
                </div>

                <div className="sm:col-span-2">
                  <label
                    htmlFor="pref-style-notes-input"
                    className="block text-sm font-medium text-[#23170F]"
                  >
                    Personal coaching style notes
                  </label>
                  <input
                    id="pref-style-notes-input"
                    type="text"
                    maxLength={1000}
                    value={communicationStyleNotes}
                    onChange={(e) => setCommunicationStyleNotes(e.target.value)}
                    aria-invalid={genFieldErrors.communication_style_notes ? "true" : "false"}
                    placeholder="e.g., Prefer open-ended reflection questions without corporate jargon."
                    className="md-input mt-1.5"
                  />
                  {genFieldErrors.communication_style_notes && (
                    <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                      {genFieldErrors.communication_style_notes}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="flex justify-end pt-1">
            <button
              id="btn-submit-generate-brief"
              type="submit"
              disabled={generating}
              className="md-btn md-btn-filled"
            >
              {generating ? "Synthesizing Brief..." : "Generate Preparation Brief"}
            </button>
          </div>
        </form>
      )}

      {/* Structured Brief Display */}
      {!loadingWorkspace && !showNewBriefForm && displayedBrief && (
        <div className="space-y-6">
          {/* Brief Meta & Immutable Revision Switcher */}
          <div className="md-card space-y-4 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="md-badge md-badge-espresso font-mono-code">
                  v{String(displayedBrief.version)}
                </span>
                <span className="md-badge md-badge-neutral font-mono-code">
                  {String(displayedBrief.duration_minutes)} min
                </span>
                <span className="md-badge md-badge-neutral">
                  {formatToneLabel(displayedBrief.tone)}
                </span>
                {displayedBrief.referenced_memory_ids.length > 0 && (
                  <span className="md-badge md-badge-sage">
                    Grounded in {String(displayedBrief.referenced_memory_ids.length)} approved{" "}
                    {displayedBrief.referenced_memory_ids.length === 1 ? "memory" : "memories"}
                  </span>
                )}
              </div>

              {briefRevisions.length > 1 && (
                <div className="flex flex-wrap items-center gap-1.5" aria-label="Brief revisions">
                  <span className="text-xs font-medium text-[#594638]">Revisions:</span>
                  {briefRevisions.map((rev) => {
                    const selected = displayedBrief.version === rev.version;
                    return (
                      <button
                        key={rev.version}
                        id={`btn-brief-revision-v${String(rev.version)}`}
                        type="button"
                        onClick={() =>
                          setSelectedRevisionVersion(
                            activeBrief && rev.version === activeBrief.version ? null : rev.version,
                          )
                        }
                        className={`md-chip min-h-7 px-2.5 py-0.5 font-mono-code text-xs ${
                          selected ? "md-chip-active" : ""
                        }`}
                      >
                        v{String(rev.version)}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {isViewingHistoricalRevision && activeBrief && (
              <div
                id="historical-revision-banner"
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#D6C7B7] bg-[#F5EEE4] px-4 py-2.5 text-xs text-[#2B170A]"
              >
                <span>
                  {`Viewing archived snapshot v${String(displayedBrief.version)} (saved ${formatShortTimestamp(displayedBrief.updated_at)}).`}
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedRevisionVersion(null)}
                  className="font-semibold text-[#4A2E1B] underline"
                >
                  Return to latest (v{String(activeBrief.version)})
                </button>
              </div>
            )}

            {displayedBrief.workflow && displayedBrief.workflow.degraded_sources.length > 0 && (
              <div
                role="status"
                className="rounded-xl border border-[#E5CFA4] bg-[#F8E8CB] px-4 py-2.5 text-xs text-[#3F2702]"
              >
                Generated with partial context fallback (
                {displayedBrief.workflow.degraded_sources.join(", ")}).
              </div>
            )}

            <div className="space-y-2">
              <h2 className="text-base font-semibold text-[#23170F]">Objective</h2>
              <p className="text-sm leading-relaxed text-[#23170F]">
                {displayedBrief.meeting_objective}
              </p>
            </div>

            <div className="rounded-xl bg-[#F5EEE4] p-4">
              <h3 className="text-xs font-semibold tracking-wide text-[#4A2E1B] uppercase">
                Grounded Context
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-[#23170F]">
                {displayedBrief.contact_context}
              </p>
            </div>

            {displayedBrief.revision_summary && (
              <p className="text-xs text-[#594638]">
                <strong className="font-semibold text-[#23170F]">Latest revision note:</strong>{" "}
                {displayedBrief.revision_summary}
              </p>
            )}
          </div>

          {/* Openers + Time-Boxed Agenda Grid */}
          <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
            <article className="md-card space-y-4 p-6">
              <h2 className="text-lg font-semibold text-[#23170F]">Conversation Openers</h2>
              <ol className="space-y-3">
                {displayedBrief.conversation_openers.map((opener, idx) => (
                  <li
                    key={`opener-${String(idx)}`}
                    className="rounded-xl border border-[#E6DACB] bg-[#FAF6F0] p-3.5 text-sm leading-relaxed text-[#23170F]"
                  >
                    <span className="mr-2 font-mono-code text-xs font-semibold text-[#4A2E1B]">
                      0{String(idx + 1)}
                    </span>
                    {opener}
                  </li>
                ))}
              </ol>
            </article>

            <article className="md-card space-y-4 p-6">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-[#23170F]">Time-Boxed Agenda</h2>
                <span className="font-mono-code text-xs font-semibold text-[#594638]">
                  Total: {String(displayedBrief.duration_minutes)}m
                </span>
              </div>
              <ol className="space-y-3">
                {displayedBrief.time_boxed_agenda.map((segment, idx) => (
                  <li
                    key={`${segment.title}-${String(idx)}`}
                    className="flex items-start gap-3.5 rounded-xl border border-[#E6DACB] bg-[#FAF6F0] p-3.5"
                  >
                    <span className="md-badge md-badge-espresso shrink-0 font-mono-code">
                      {String(segment.duration_minutes)}m
                    </span>
                    <div className="space-y-0.5">
                      <p className="text-sm font-semibold text-[#23170F]">{segment.title}</p>
                      <p className="text-xs leading-relaxed text-[#594638]">
                        {segment.description}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </article>
          </div>

          {/* Prioritized Questions */}
          <article className="md-card space-y-4 p-6">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-[#23170F]">Prioritized Questions</h2>
              <span className="text-xs font-medium text-[#594638]">
                {String(displayedBrief.suggested_questions.length)} questions
              </span>
            </div>

            <ol className="grid gap-3.5 md:grid-cols-2">
              {displayedBrief.suggested_questions.map((item, idx) => (
                <li
                  key={item.id}
                  className="flex flex-col justify-between rounded-2xl border border-[#E6DACB] bg-[#FAF6F0] p-4"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono-code text-xs font-semibold text-[#4A2E1B]">
                        Q{String(idx + 1)}
                      </span>
                      {item.category && (
                        <span className="md-badge md-badge-neutral">{item.category}</span>
                      )}
                    </div>
                    <p className="text-sm font-semibold leading-snug text-[#23170F]">
                      {item.question}
                    </p>
                  </div>
                  <p className="mt-3 border-t border-[#E6DACB] pt-2.5 text-xs leading-relaxed text-[#594638]">
                    <span className="font-semibold text-[#4A2E1B]">Why it matters:</span>{" "}
                    {item.rationale}
                  </p>
                </li>
              ))}
            </ol>
          </article>

          {/* Suggested Follow-Up Topics */}
          {displayedBrief.suggested_follow_up_topics.length > 0 && (
            <article className="md-card space-y-3 p-6">
              <h2 className="text-base font-semibold text-[#23170F]">Follow-Up &amp; Closing Prompts</h2>
              <ul className="grid gap-2.5 sm:grid-cols-2">
                {displayedBrief.suggested_follow_up_topics.map((topic, idx) => (
                  <li
                    key={`followup-${String(idx)}`}
                    className="rounded-xl bg-[#F5EEE4] px-3.5 py-2.5 text-sm text-[#23170F]"
                  >
                    {topic}
                  </li>
                ))}
              </ul>
            </article>
          )}

          {/* Natural-Language Refinement Composer */}
          {!isViewingHistoricalRevision && activeBrief && (
            <form
              onSubmit={(e) => void handleReviseSubmit(e)}
              noValidate
              aria-labelledby="revise-brief-heading"
              className="md-card space-y-4 p-6"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="revise-brief-heading" className="text-lg font-semibold text-[#23170F]">
                  Refine Brief
                </h2>
                <span className="font-mono-code text-xs text-[#594638]">
                  Editing from v{String(activeBrief.version)} → v{String(activeBrief.version + 1)}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                {QUICK_REFINEMENT_PROMPTS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => {
                      setRevisionInstructions(preset.instruction);
                      if (preset.durationOverride !== undefined) {
                        setRevisionDurationOverride(String(preset.durationOverride));
                      }
                      if (preset.toneOverride !== undefined) {
                        setRevisionToneOverride(preset.toneOverride);
                      }
                    }}
                    className="md-chip"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              <div>
                <label
                  htmlFor="revise-instructions-input"
                  className="block text-sm font-medium text-[#23170F]"
                >
                  Revision instructions
                </label>
                <textarea
                  id="revise-instructions-input"
                  rows={2}
                  maxLength={1000}
                  value={revisionInstructions}
                  onChange={(e) => setRevisionInstructions(e.target.value)}
                  aria-invalid={revisionFieldError ? "true" : "false"}
                  aria-describedby={revisionFieldError ? "revise-instructions-error" : undefined}
                  placeholder="e.g., Make the questions less formal, or trim the agenda to 15 minutes."
                  className="md-textarea mt-1.5"
                />
                {revisionFieldError && (
                  <p
                    id="revise-instructions-error"
                    role="alert"
                    className="mt-1 text-xs text-[#9E2A2B]"
                  >
                    {revisionFieldError}
                  </p>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label
                    htmlFor="revise-duration-input"
                    className="block text-xs font-medium text-[#594638]"
                  >
                    Optional duration override (minutes)
                  </label>
                  <input
                    id="revise-duration-input"
                    type="number"
                    min={5}
                    max={180}
                    value={revisionDurationOverride}
                    onChange={(e) => setRevisionDurationOverride(e.target.value)}
                    placeholder={`Keep ${String(activeBrief.duration_minutes)}m`}
                    className="md-input mt-1 font-mono-code"
                  />
                </div>

                <div>
                  <label
                    htmlFor="revise-tone-select"
                    className="block text-xs font-medium text-[#594638]"
                  >
                    Optional tone override
                  </label>
                  <select
                    id="revise-tone-select"
                    value={revisionToneOverride}
                    onChange={(e) => setRevisionToneOverride(e.target.value as MeetingTone | "")}
                    className="md-select mt-1"
                  >
                    <option value="">Keep {formatToneLabel(activeBrief.tone)}</option>
                    {MEETING_TONE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex justify-end">
                <button
                  id="btn-submit-revise-brief"
                  type="submit"
                  disabled={revising}
                  className="md-btn md-btn-filled"
                >
                  {revising ? "Creating New Revision..." : "Save New Revision"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
