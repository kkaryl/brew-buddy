import {
  Calendar,
  ChevronDown,
  Clock,
  Compass,
  MessageCircle,
  RefreshCw,
  Smartphone,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type FormEvent, type JSX } from "react";
import { BrewApiError } from "../../api/client";
import type {
  ContactResponse,
  MeetingResponse,
  MeetingTone,
  MemoryResponse,
  PreparationBriefResponse,
  ReviseBriefRequest,
} from "../../api/types";
import {
  formatCalendarDayLabel,
  formatCalendarTimeRange,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import type { CoachingStyleDefaults } from "../../state/coachingDefaultsStore";
import { CueQuestionCard } from "../domain/CueQuestionCard";
import { RunOfShowRibbon } from "../domain/PacingRibbon";
import {
  MEETING_TONE_OPTIONS,
  errorToFeedbackNotice,
  formatShortTimestamp,
  formatToneLabel,
  type FeedbackNotice,
} from "../formatters";
import { StatusBanner } from "../StatusFeedback";
import {
  ContactAvatar,
  EmptyState,
  FormField,
  Illustration,
  LoadingSkeleton,
  PillButton,
  PrimaryButton,
} from "../ui";

const ONE_TAP_ADJUSTMENTS: readonly {
  readonly label: string;
  readonly instruction: string;
  readonly icon: "clock" | "message" | "refresh" | "compass";
  readonly durationOverride?: number | undefined;
  readonly toneOverride?: MeetingTone | undefined;
}[] = [
  {
    label: "Trim to 15m",
    instruction: "I only have 15 minutes. Tighten the agenda and keep the highest-impact questions.",
    icon: "clock",
    durationOverride: 15,
  },
  {
    label: "Less formal",
    instruction: "Make the questions less formal and more conversational.",
    icon: "message",
    toneOverride: "warm_casual",
  },
  {
    label: "Swap Q3 & Q4",
    instruction: "Replace the later backup questions with fresher story-driven prompts.",
    icon: "refresh",
  },
  {
    label: "Career focus",
    instruction: "Focus more on their career trajectory and leadership trade-offs.",
    icon: "compass",
  },
];

export interface CueStudioScreenProps {
  readonly contacts: readonly ContactResponse[];
  readonly activeContact: ContactResponse | null;
  readonly meetings: readonly MeetingResponse[];
  readonly activeBrief: PreparationBriefResponse | null;
  readonly briefRevisions: readonly PreparationBriefResponse[];
  readonly memories: readonly MemoryResponse[];
  readonly calendarEvents: readonly CalendarCoffeeChatEvent[];
  readonly starredQuestionIds: ReadonlySet<string>;
  readonly styleDefaults: CoachingStyleDefaults;
  readonly loadingWorkspace: boolean;
  readonly onToggleStarQuestion: (questionId: string) => void;
  readonly onSelectContact: (contactId: string) => Promise<void>;
  readonly onOpenSetup: (contactId?: string) => void;
  readonly onOpenPocketGlance: () => void;
  readonly onOpenDebrief: (contactId?: string) => void;
  readonly onReviseBrief: (
    briefId: string,
    payload: ReviseBriefRequest,
  ) => Promise<PreparationBriefResponse>;
  readonly onReloadBrief: (briefId: string) => Promise<void>;
  readonly onDeleteBrief?:
    | ((briefId: string, expectedVersion?: number) => Promise<void>)
    | undefined;
}

export function CueStudioScreen({
  contacts,
  activeContact,
  meetings,
  activeBrief,
  briefRevisions,
  memories,
  calendarEvents,
  starredQuestionIds,
  styleDefaults,
  loadingWorkspace,
  onToggleStarQuestion,
  onSelectContact,
  onOpenSetup,
  onOpenPocketGlance,
  onOpenDebrief,
  onReviseBrief,
  onReloadBrief,
  onDeleteBrief,
}: CueStudioScreenProps): JSX.Element {
  const [selectedRevisionVersion, setSelectedRevisionVersion] = useState<number | null>(null);
  const [revisionInstructions, setRevisionInstructions] = useState("");
  const [revisionDurationOverride, setRevisionDurationOverride] = useState<string>("");
  const [revisionToneOverride, setRevisionToneOverride] = useState<MeetingTone | "">("");
  const [showOverrideControls, setShowOverrideControls] = useState(false);
  const [revisionFieldError, setRevisionFieldError] = useState<string | null>(null);
  const [revising, setRevising] = useState(false);
  const [confirmingDeleteBrief, setConfirmingDeleteBrief] = useState(false);
  const [deletingBrief, setDeletingBrief] = useState(false);
  const [versionConflictBriefId, setVersionConflictBriefId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  const activeBriefId = activeBrief?.id ?? null;

  useEffect(() => {
    setSelectedRevisionVersion(null);
    setConfirmingDeleteBrief(false);
    setVersionConflictBriefId(null);
    setFeedback(null);
  }, [activeBriefId]);

  if (loadingWorkspace && !activeBrief) {
    return <LoadingSkeleton label="Opening Cue Studio..." rows={4} />;
  }

  if (!activeContact || !activeBrief) {
    return (
      <section className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="brew-eyebrow">CUE STUDIO</div>
            <h1 className="brew-page-heading mt-1">Cue-Card Studio</h1>
          </div>
          {contacts.length > 1 && (
            <div className="flex items-center gap-2">
              <label
                htmlFor="studio-empty-contact-select"
                className="text-xs font-semibold text-brew-secondary"
              >
                Switch person:
              </label>
              <select
                id="studio-empty-contact-select"
                value={activeContact?.id ?? ""}
                onChange={(e) => {
                  if (e.target.value) {
                    void onSelectContact(e.target.value);
                  }
                }}
                className="rounded-full border border-brew-border bg-brew-paper px-3.5 py-1.5 text-xs font-bold text-brew-plum"
              >
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <EmptyState
          title={
            activeContact
              ? `No cue deck synthesized for ${activeContact.name} yet`
              : "Synthesize your first cue deck"
          }
          description="Shape your conversation objective, duration, and tone to generate a proportional run-of-show ribbon, warm icebreakers, and star-ready cue cards."
          illustration="cue-studio-copilot"
          actionLabel="Shape Conversation"
          actionId="btn-studio-open-setup"
          onAction={() => onOpenSetup(activeContact?.id)}
        />
      </section>
    );
  }

  const displayedBrief: PreparationBriefResponse =
    selectedRevisionVersion !== null
      ? (briefRevisions.find((rev) => rev.version === selectedRevisionVersion) ?? activeBrief)
      : activeBrief;

  const isViewingHistoricalRevision = displayedBrief.version !== activeBrief.version;

  const sortedRevisions =
    briefRevisions.length > 0
      ? [...briefRevisions].sort((a, b) => a.version - b.version)
      : [activeBrief];

  const matchedCalendarEvent =
    calendarEvents.find(
      (ev) =>
        ev.temporalStatus !== "wrapped" &&
        matchCalendarEventContact(ev, [activeContact]) !== null,
    ) ?? null;

  const activeMeeting =
    meetings.find((m) => m.id === displayedBrief.meeting_id) ?? meetings[0] ?? null;

  const referencedMemories = memories.filter((m) =>
    displayedBrief.referenced_memory_ids.includes(m.id),
  );
  const counterpartReferencedMemories = referencedMemories.filter((m) => m.scope === "contact");
  const styleReferencedMemories = referencedMemories.filter(
    (m) => m.scope === "user_preference",
  );

  const handleReviseSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
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
        title: `Updated to deck v${String(updated.version)}`,
        message:
          updated.revision_summary ??
          "Previous snapshot remains available in the version switcher.",
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

  const renderPresetIcon = (kind: "clock" | "message" | "refresh" | "compass"): JSX.Element => {
    switch (kind) {
      case "clock":
        return <Clock className="h-3.5 w-3.5 text-brew-coral" aria-hidden="true" />;
      case "message":
        return <MessageCircle className="h-3.5 w-3.5 text-brew-purple" aria-hidden="true" />;
      case "refresh":
        return <RefreshCw className="h-3.5 w-3.5 text-brew-mint-deep" aria-hidden="true" />;
      case "compass":
        return <Compass className="h-3.5 w-3.5 text-brew-coral-vibrant" aria-hidden="true" />;
    }
  };

  return (
    <div className="space-y-5">
      {/* Studio Top Session Header */}
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div className="flex items-start gap-3.5 sm:items-center">
          <ContactAvatar name={activeContact.name} tone="mint" size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-serif text-[26px] leading-tight font-bold text-brew-plum sm:text-[28px]">
                {activeContact.name}
              </h1>

              {(activeContact.title || activeContact.organization) && (
                <span className="brew-badge-peach">
                  {[activeContact.title, activeContact.organization]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              )}

              {matchedCalendarEvent && (
                <span className="brew-badge-mint">
                  <Calendar className="h-3 w-3 shrink-0" aria-hidden="true" />
                  <span>from GCal</span>
                </span>
              )}

              {contacts.length > 1 && (
                <select
                  id="studio-contact-switcher"
                  aria-label="Switch counterpart deck"
                  value={activeContact.id}
                  onChange={(e) => {
                    void onSelectContact(e.target.value);
                  }}
                  className="rounded-full border border-brew-border bg-brew-paper px-2.5 py-1 text-xs font-semibold text-brew-secondary hover:text-brew-plum"
                >
                  {contacts.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <p className="mt-1 text-[13px] text-brew-secondary">
              {matchedCalendarEvent ? (
                <>
                  {formatCalendarDayLabel(matchedCalendarEvent.scheduledStartIso)},{" "}
                  {formatCalendarTimeRange(
                    matchedCalendarEvent.scheduledStartIso,
                    matchedCalendarEvent.scheduledEndIso,
                  )}{" "}
                  ·{" "}
                </>
              ) : activeMeeting?.scheduled_at ? (
                <>{formatShortTimestamp(activeMeeting.scheduled_at)} · </>
              ) : (
                <>
                  {String(displayedBrief.duration_minutes)} min ·{" "}
                  {formatToneLabel(displayedBrief.tone)} ·{" "}
                </>
              )}
              Goal: {displayedBrief.meeting_objective}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Immutable Revision Switcher */}
          <div
            aria-label="Brief versions"
            className="inline-flex items-center gap-1 rounded-full border border-brew-border bg-brew-paper p-1"
          >
            <span className="px-2 text-[11.5px] font-medium text-brew-secondary">Version</span>
            {sortedRevisions.map((rev) => {
              const isSelected = displayedBrief.version === rev.version;
              return (
                <button
                  key={rev.version}
                  id={`btn-brief-revision-v${String(rev.version)}`}
                  type="button"
                  onClick={() =>
                    setSelectedRevisionVersion(
                      rev.version === activeBrief.version ? null : rev.version,
                    )
                  }
                  className={`min-h-[30px] cursor-pointer rounded-full px-2.5 py-1 font-mono-code text-xs transition ${
                    isSelected
                      ? "bg-brew-peach font-bold text-brew-plum"
                      : "font-medium text-brew-secondary hover:bg-brew-blush"
                  }`}
                >
                  v{String(rev.version)}
                </button>
              );
            })}
          </div>

          <PillButton
            id="btn-studio-new-setup"
            variant="outline"
            size="sm"
            onClick={() => onOpenSetup(activeContact.id)}
          >
            New Deck
          </PillButton>

          {onDeleteBrief && (
            <PillButton
              id={`btn-delete-brief-${activeBrief.id}`}
              variant="ghost"
              size="sm"
              disabled={deletingBrief}
              onClick={() => setConfirmingDeleteBrief((prev) => !prev)}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Delete Deck</span>
            </PillButton>
          )}

          <PillButton
            id="btn-open-pocket-glance"
            variant="outline"
            size="sm"
            onClick={onOpenPocketGlance}
          >
            <Smartphone className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Pocket Glance</span>
          </PillButton>

          <PrimaryButton
            id="btn-wrap-and-debrief"
            shape="pill"
            onClick={() => onOpenDebrief(activeContact.id)}
            className="!min-h-[40px] !px-4.5 !py-2 !text-[13px]"
          >
            Wrap &amp; Debrief
          </PrimaryButton>
        </div>
      </div>

      {confirmingDeleteBrief && onDeleteBrief && (
        <div
          role="region"
          aria-label={`Confirm deletion of cue deck for ${activeContact.name}`}
          className="flex flex-wrap items-center justify-between gap-3 rounded-[22px] border border-[#F2C2BA] bg-[#FFF5F3] px-5 py-4"
        >
          <div>
            <div className="font-serif text-[16px] font-bold text-brew-plum">
              Delete this cue deck for {activeContact.name}?
            </div>
            <p className="mt-0.5 text-xs text-brew-secondary">
              Removes v1 through v{String(activeBrief.version)} of this preparation brief. Stamped
              keepsakes in your journal are preserved.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <PillButton
              id={`btn-cancel-delete-brief-${activeBrief.id}`}
              variant="outline"
              size="sm"
              disabled={deletingBrief}
              onClick={() => setConfirmingDeleteBrief(false)}
            >
              Cancel
            </PillButton>
            <PillButton
              id={`btn-confirm-delete-brief-${activeBrief.id}`}
              variant="danger"
              size="sm"
              disabled={deletingBrief}
              onClick={() => {
                setDeletingBrief(true);
                setFeedback(null);
                void onDeleteBrief(activeBrief.id, activeBrief.version)
                  .then(() => {
                    setConfirmingDeleteBrief(false);
                  })
                  .catch((err: unknown) => {
                    setFeedback(errorToFeedbackNotice(err, "Could not delete cue deck"));
                  })
                  .finally(() => {
                    setDeletingBrief(false);
                  });
              }}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{deletingBrief ? "Deleting..." : "Confirm Delete"}</span>
            </PillButton>
          </div>
        </div>
      )}

      {/* Feedback, Version Conflict Recovery, Historical Snapshot, & Degraded Notices */}
      {feedback && (
        <div className="space-y-2">
          <StatusBanner notice={feedback} onDismiss={() => setFeedback(null)} />
          {versionConflictBriefId && (
            <div className="flex justify-end">
              <PillButton
                id="btn-reload-latest-brief"
                variant="peach"
                size="sm"
                onClick={() => {
                  void onReloadBrief(versionConflictBriefId).then(() => {
                    setVersionConflictBriefId(null);
                    setFeedback(null);
                  });
                }}
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Reload Latest Version</span>
              </PillButton>
            </div>
          )}
        </div>
      )}

      {isViewingHistoricalRevision && (
        <div
          id="historical-revision-banner"
          className="brew-card-yellow flex flex-wrap items-center justify-between gap-2 rounded-[18px] px-4 py-3 text-xs text-brew-plum"
        >
          <span>
            Viewing archived snapshot v{String(displayedBrief.version)} (saved{" "}
            {formatShortTimestamp(displayedBrief.updated_at)}).
          </span>
          <button
            id="btn-return-latest-revision"
            type="button"
            onClick={() => setSelectedRevisionVersion(null)}
            className="cursor-pointer font-bold text-brew-plum underline"
          >
            Return to latest (v{String(activeBrief.version)})
          </button>
        </div>
      )}

      {displayedBrief.workflow && displayedBrief.workflow.degraded_sources.length > 0 && (
        <div
          role="status"
          className="brew-card-yellow rounded-[18px] px-4 py-3 text-xs text-brew-plum"
        >
          Generated with partial context fallback (
          {displayedBrief.workflow.degraded_sources.join(", ")}).
        </div>
      )}

      {/* Split 2-Column Studio Grid */}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,145fr)_minmax(0,72fr)]">
        {/* Left Cue Deck Column */}
        <div className="flex min-w-0 flex-col gap-[18px]">
          {/* Proportional Run-of-Show Ribbon */}
          <RunOfShowRibbon
            segments={displayedBrief.time_boxed_agenda}
            totalDurationMinutes={displayedBrief.duration_minutes}
          />

          {/* Icebreakers Grid */}
          <div className="grid gap-3.5 md:grid-cols-2">
            {displayedBrief.conversation_openers.map((opener, idx) => {
              const isPrimaryOpener = idx === 0;
              const firstMem = counterpartReferencedMemories[0];
              return (
                <div
                  key={`icebreaker-${String(idx)}`}
                  className={`rounded-[22px] px-[18px] py-4 ${
                    isPrimaryOpener ? "brew-card-coral" : "brew-card-paper"
                  }`}
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span
                      className={`brew-eyebrow ${isPrimaryOpener ? "!text-[#9B4B35]" : ""}`}
                    >
                      ICEBREAKER 0{String(idx + 1)}
                    </span>
                    {isPrimaryOpener && displayedBrief.referenced_memory_ids.length > 0 && (
                      <span className="brew-badge-mint !px-2 !py-0.5 !text-[10px]">
                        {firstMem
                          ? `${formatShortTimestamp(firstMem.updated_at)} note`
                          : "Saved note"}
                      </span>
                    )}
                  </div>
                  <p className="text-[13.5px] leading-[1.45] font-semibold text-brew-plum">
                    “{opener}”
                  </p>
                </div>
              );
            })}
          </div>

          {/* Question Cue Cards Grid */}
          <ol aria-label="Cue card questions" className="grid gap-3.5 md:grid-cols-2">
            {displayedBrief.suggested_questions.map((question, idx) => (
              <CueQuestionCard
                key={question.id}
                item={question}
                index={idx}
                isStarred={starredQuestionIds.has(question.id)}
                onToggleStar={() => onToggleStarQuestion(question.id)}
              />
            ))}
          </ol>

          {/* Closing & Follow-Up Prompts */}
          {displayedBrief.suggested_follow_up_topics.length > 0 && (
            <div className="brew-card-mint rounded-[22px] px-5 py-4">
              <div className="brew-eyebrow mb-2 !text-[#215A45]">
                CLOSING &amp; FOLLOW-UP THREADS
              </div>
              <ul className="grid gap-2.5 sm:grid-cols-2">
                {displayedBrief.suggested_follow_up_topics.map((topic, idx) => (
                  <li
                    key={`followup-${String(idx)}`}
                    className="rounded-[16px] border border-[#CBE8D8] bg-brew-paper px-3.5 py-2.5 text-[13px] font-medium text-brew-plum"
                  >
                    {topic}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right Brief Co-Pilot Rail */}
        <aside
          aria-label="Brief Co-Pilot"
          className="brew-card-lavender flex min-w-0 flex-col gap-3.5 rounded-[30px] px-6 py-5.5 lg:sticky lg:top-24"
        >
          <div>
            <div className="brew-eyebrow !text-[#69469B]">BRIEF CO-PILOT</div>
            <h2 className="mt-0.5 font-serif text-[21px] font-bold text-brew-plum">
              Tune on the fly
            </h2>
          </div>

          <div className="flex justify-center rounded-[22px] border border-[#E3D7FA] bg-white/62 px-3 py-2">
            <Illustration
              name="cue-studio-copilot"
              className="h-[132px] w-full"
            />
          </div>

          {isViewingHistoricalRevision ? (
            <div className="space-y-3 rounded-[20px] border border-[#D5C4F7] bg-brew-paper p-4 text-xs text-brew-secondary">
              <p className="leading-relaxed">
                Snapshot <strong className="text-brew-plum">v{String(displayedBrief.version)}</strong>{" "}
                is preserved read-only. Switch back to{" "}
                <strong className="text-brew-plum">v{String(activeBrief.version)}</strong> to refine
                your live deck.
              </p>
              <PillButton
                variant="peach"
                size="sm"
                onClick={() => setSelectedRevisionVersion(null)}
              >
                Switch to v{String(activeBrief.version)}
              </PillButton>
            </div>
          ) : (
            <>
              <div>
                <div className="brew-eyebrow mb-2">ONE-TAP ADJUSTMENTS</div>
                <div className="flex flex-wrap gap-1.5">
                  {ONE_TAP_ADJUSTMENTS.map((preset) => (
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
                      className="inline-flex min-h-[34px] cursor-pointer items-center gap-1.5 rounded-full border border-brew-border bg-brew-paper px-3 py-1.5 text-xs font-semibold text-brew-plum transition hover:bg-brew-blush"
                    >
                      {renderPresetIcon(preset.icon)}
                      <span>{preset.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <form
                onSubmit={(e) => void handleReviseSubmit(e)}
                noValidate
                aria-label="Refine cue deck"
                className="rounded-[20px] border-[1.5px] border-[#D5C4F7] bg-brew-paper p-3.5"
              >
                <label htmlFor="revise-instructions-input" className="sr-only">
                  Revision instructions
                </label>
                <textarea
                  id="revise-instructions-input"
                  rows={3}
                  maxLength={1000}
                  value={revisionInstructions}
                  onChange={(e) => setRevisionInstructions(e.target.value)}
                  aria-invalid={revisionFieldError ? "true" : "false"}
                  aria-describedby={
                    revisionFieldError ? "revise-instructions-error" : undefined
                  }
                  placeholder="Swap Q3 for a question about how they simulate LLM gateway timeouts during game days..."
                  className="w-full resize-none border-0 bg-transparent text-[13px] leading-[1.45] text-brew-plum placeholder:text-brew-muted focus:outline-none"
                />

                {revisionFieldError && (
                  <p
                    id="revise-instructions-error"
                    role="alert"
                    className="mt-1.5 text-xs font-semibold text-[#9E3426]"
                  >
                    {revisionFieldError}
                  </p>
                )}

                <div className="mt-2">
                  <button
                    id="btn-toggle-revise-overrides"
                    type="button"
                    aria-expanded={showOverrideControls}
                    onClick={() => setShowOverrideControls((prev) => !prev)}
                    className="inline-flex cursor-pointer items-center gap-1 text-[11px] font-semibold text-brew-secondary hover:text-brew-plum"
                  >
                    <ChevronDown
                      className={`h-3 w-3 transition-transform ${showOverrideControls ? "rotate-180" : ""}`}
                      aria-hidden="true"
                    />
                    <span>Duration or tone override</span>
                  </button>

                  {showOverrideControls && (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <FormField htmlFor="revise-duration-input" label="Minutes">
                        <input
                          id="revise-duration-input"
                          type="number"
                          min={5}
                          max={180}
                          value={revisionDurationOverride}
                          onChange={(e) => setRevisionDurationOverride(e.target.value)}
                          placeholder={`${String(activeBrief.duration_minutes)}m`}
                          className="brew-field-control !min-h-[36px] !px-2.5 !py-1 !text-xs font-mono-code"
                        />
                      </FormField>

                      <FormField htmlFor="revise-tone-select" label="Tone">
                        <select
                          id="revise-tone-select"
                          value={revisionToneOverride}
                          onChange={(e) =>
                            setRevisionToneOverride(e.target.value as MeetingTone | "")
                          }
                          className="brew-field-control !min-h-[36px] !px-2.5 !py-1 !text-xs"
                        >
                          <option value="">Keep {formatToneLabel(activeBrief.tone)}</option>
                          {MEETING_TONE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </FormField>
                    </div>
                  )}
                </div>

                <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-brew-border pt-2.5">
                  <span className="text-[11.5px] text-brew-secondary">
                    Saves as v{String(activeBrief.version + 1)}
                  </span>

                  <PrimaryButton
                    id="btn-submit-revise-brief"
                    type="submit"
                    shape="pill"
                    loading={revising}
                    className="!min-h-[36px] !px-4 !py-1.5 !text-[12.5px]"
                  >
                    <span>{revising ? "Refining..." : "Refine Deck"}</span>
                    {!revising && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
                  </PrimaryButton>
                </div>
              </form>
            </>
          )}

          {/* Grounded Context Summary Box */}
          <div className="rounded-[18px] border border-[#C9E6D6] bg-brew-mint-pale px-4 py-3 text-xs">
            <div className="mb-1 font-bold text-[#215A45]">Context woven in:</div>
            <div className="space-y-1 leading-[1.45] text-brew-secondary">
              {counterpartReferencedMemories.length > 0 ? (
                counterpartReferencedMemories.slice(0, 2).map((mem) => (
                  <p key={mem.id}>
                    • <strong className="text-brew-plum">Saved keepsake:</strong> {mem.text}
                  </p>
                ))
              ) : (
                <p>{displayedBrief.contact_context}</p>
              )}
              {(styleReferencedMemories[0] || styleDefaults.defaultStyleNotes) && (
                <p>
                  • <strong className="text-brew-plum">Your style:</strong>{" "}
                  {styleReferencedMemories[0]?.text ?? styleDefaults.defaultStyleNotes}
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
