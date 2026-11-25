import { Clock, MessageCircle } from "lucide-react";
import { useState, type FormEvent, type JSX } from "react";
import type {
  ContactResponse,
  PreparationBriefResponse,
  ReviseBriefRequest,
} from "../../api/types";
import {
  formatCalendarTimeRange,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import { CueQuestionCard } from "../domain/CueQuestionCard";
import { computeBlueprintSplit } from "../../utils/pacingBlueprint";
import {
  errorToFeedbackNotice,
  formatShortTimestamp,
  formatToneLabel,
  type FeedbackNotice,
} from "../formatters";
import { StatusBanner } from "../StatusFeedback";
import { EmptyState, Illustration, PrimaryButton } from "../ui";

export interface PocketCueCardsScreenProps {
  readonly activeContact: ContactResponse | null;
  readonly activeBrief: PreparationBriefResponse | null;
  readonly calendarEvents: readonly CalendarCoffeeChatEvent[];
  readonly starredQuestionIds: ReadonlySet<string>;
  readonly onBackToStudio: () => void;
  readonly onReviseBrief: (
    briefId: string,
    payload: ReviseBriefRequest,
  ) => Promise<PreparationBriefResponse>;
}

export function PocketCueCardsScreen({
  activeContact,
  activeBrief,
  calendarEvents,
  starredQuestionIds,
  onBackToStudio,
  onReviseBrief,
}: PocketCueCardsScreenProps): JSX.Element {
  const [tuneText, setTuneText] = useState("");
  const [durationOverride, setDurationOverride] = useState<number | null>(null);
  const [toneOverride, setToneOverride] = useState<"warm_casual" | null>(null);
  const [showAllQuestions, setShowAllQuestions] = useState(false);
  const [tuning, setTuning] = useState(false);
  const [notice, setNotice] = useState<FeedbackNotice | null>(null);

  if (!activeContact || !activeBrief) {
    return (
      <div className="mx-auto max-w-[460px] py-6">
        <EmptyState
          title="No active cue cards yet"
          description="Synthesize a conversation deck first to view your starred Pocket Cue Cards."
          illustration="cue-studio-copilot"
          actionLabel="Back to Studio"
          onAction={onBackToStudio}
        />
      </div>
    );
  }

  const matchedCalendar =
    calendarEvents.find(
      (ev) =>
        ev.temporalStatus !== "wrapped" &&
        matchCalendarEventContact(ev, [activeContact]) !== null,
    ) ?? null;

  const starredQuestions = activeBrief.suggested_questions.filter((q) =>
    starredQuestionIds.has(q.id),
  );
  const visibleQuestions = showAllQuestions
    ? activeBrief.suggested_questions
    : starredQuestions.length > 0
      ? starredQuestions
      : activeBrief.suggested_questions.slice(0, 2);

  const split = computeBlueprintSplit(activeBrief.duration_minutes);
  const agendaSegments = activeBrief.time_boxed_agenda;
  const firstMin = agendaSegments[0]?.duration_minutes ?? split.hookMinutes;
  const lastMin =
    agendaSegments.length >= 2
      ? (agendaSegments[agendaSegments.length - 1]?.duration_minutes ?? split.wrapMinutes)
      : split.wrapMinutes;
  const middleMin = Math.max(1, activeBrief.duration_minutes - firstMin - lastMin);

  const closingLine =
    activeBrief.suggested_follow_up_topics[0] ??
    agendaSegments[agendaSegments.length - 1]?.description ??
    "Confirm one thoughtful follow-up takeaway before wrapping.";

  const handleTuneSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmed = tuneText.trim();
    if (trimmed.length < 3) {
      setNotice({
        kind: "error",
        title: "Enter a quick adjustment",
        message: "Type at least 3 characters or tap one of the quick chips below.",
      });
      return;
    }

    setNotice(null);
    setTuning(true);
    try {
      await onReviseBrief(activeBrief.id, {
        instructions: trimmed,
        expected_version: activeBrief.version,
        duration_minutes: durationOverride,
        tone: toneOverride,
      });
      setTuneText("");
      setDurationOverride(null);
      setToneOverride(null);
    } catch (err: unknown) {
      setNotice(errorToFeedbackNotice(err, "Could not tune deck"));
    } finally {
      setTuning(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-[500px] flex-col gap-3 pb-36">
      {notice && <StatusBanner notice={notice} onDismiss={() => setNotice(null)} />}

      {/* Top Counterpart & Proportional Time Card */}
      <section
        aria-labelledby="pocket-counterpart-heading"
        className="brew-card-paper rounded-[24px] px-[18px] py-3.5"
      >
        <div className="mb-2.5 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1
                id="pocket-counterpart-heading"
                className="font-serif text-[22px] font-bold text-brew-plum"
              >
                {activeContact.name}
              </h1>
              {matchedCalendar && (
                <span className="brew-badge-peach !px-2 !py-0.5 !text-[10px]">
                  from GCal
                </span>
              )}
            </div>
            <div className="mt-0.5 text-xs text-brew-secondary">
              {matchedCalendar
                ? `${formatCalendarTimeRange(matchedCalendar.scheduledStartIso, matchedCalendar.scheduledEndIso)} · `
                : `${String(activeBrief.duration_minutes)} min · `}
              {formatToneLabel(activeBrief.tone)}
            </div>
          </div>

          <Illustration
            name="cue-studio-copilot"
            decorative
            className="h-[46px] w-[68px] shrink-0"
          />
        </div>

        <div
          className="grid gap-1.5 overflow-hidden text-center text-[11px] font-bold text-brew-plum"
          style={{
            gridTemplateColumns: `minmax(0, ${String(Math.max(2, Math.round(activeBrief.duration_minutes * 0.2), firstMin))}fr) minmax(0, ${String(Math.max(3, middleMin))}fr) minmax(0, ${String(Math.max(2, Math.round(activeBrief.duration_minutes * 0.2), lastMin))}fr)`,
          }}
        >
          <div className="min-w-0 truncate rounded-[10px] bg-brew-peach px-1.5 py-1.5">
            {String(firstMin)}m
          </div>
          <div className="min-w-0 truncate rounded-[10px] bg-brew-lavender px-2 py-1.5">
            {String(middleMin)}m Deep Dive
          </div>
          <div className="min-w-0 truncate rounded-[10px] bg-brew-mint px-1.5 py-1.5">
            {String(lastMin)}m
          </div>
        </div>
      </section>

      {/* Warm Icebreaker */}
      {activeBrief.conversation_openers[0] && (
        <div className="brew-card-coral rounded-[22px] px-[18px] py-3.5">
          <div className="brew-eyebrow mb-1 !text-[10px] !text-[#9B4B35]">
            WARM ICEBREAKER
            {activeBrief.referenced_memory_ids.length > 0
              ? ` · ${formatShortTimestamp(activeBrief.updated_at).toUpperCase()} NOTE`
              : ""}
          </div>
          <p className="text-[13.5px] leading-[1.42] font-semibold text-brew-plum">
            “{activeBrief.conversation_openers[0]}”
          </p>
        </div>
      )}

      {/* Starred Cue Cards */}
      <ol aria-label="Pocket cue cards" className="flex flex-col gap-3">
        {visibleQuestions.map((q, idx) => {
          const isPrimaryStar = idx === 0;
          const label = showAllQuestions
            ? `Q${String(idx + 1)}`
            : idx === 0 && visibleQuestions.length > 1
              ? `STARRED Q1 · 1 OF ${String(visibleQuestions.length)}`
              : `STARRED Q${String(idx + 1)}`;

          return (
            <CueQuestionCard
              key={q.id}
              item={q}
              index={idx}
              isStarred={isPrimaryStar}
              pocketOrderLabel={label}
              compact={!isPrimaryStar}
            />
          );
        })}
      </ol>

      {activeBrief.suggested_questions.length > visibleQuestions.length && (
        <div className="flex justify-center">
          <button
            id="btn-pocket-toggle-all-questions"
            type="button"
            onClick={() => setShowAllQuestions(true)}
            className="cursor-pointer text-xs font-semibold text-brew-secondary hover:text-brew-plum"
          >
            Show all {String(activeBrief.suggested_questions.length)} questions
          </button>
        </div>
      )}

      {/* Graceful Close */}
      <div className="brew-card-mint rounded-[20px] px-[18px] py-3.5">
        <div className="brew-eyebrow mb-1 !text-[10px] !text-[#215A45]">
          {String(activeBrief.duration_minutes - lastMin)}-
          {String(activeBrief.duration_minutes)}M CLOSE
        </div>
        <p className="text-[12.5px] font-semibold text-brew-plum">{closingLine}</p>
      </div>

      {/* Floating Bottom Quick-Tune Bar (matches Mockup 07) */}
      <form
        onSubmit={(e) => void handleTuneSubmit(e)}
        aria-label="Quick-tune pocket deck"
        className="brew-card-lavender fixed right-[18px] bottom-[18px] left-[18px] z-30 mx-auto max-w-[500px] rounded-[24px] !border-[1.5px] !border-[#D5C4F7] px-3.5 py-3 shadow-floating"
      >
        <div className="mb-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => {
              setTuneText("Cut the agenda and questions down to a tight 15 minutes.");
              setDurationOverride(15);
            }}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full bg-brew-paper px-2.5 py-1 text-[11px] font-bold text-brew-plum"
          >
            <Clock className="h-3 w-3 text-brew-coral" aria-hidden="true" />
            <span>Cut to 15m</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setTuneText("Make the questions warmer and more casual.");
              setToneOverride("warm_casual");
            }}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full bg-brew-paper px-2.5 py-1 text-[11px] font-bold text-brew-plum"
          >
            <MessageCircle className="h-3 w-3 text-brew-purple" aria-hidden="true" />
            <span>Casual tone</span>
          </button>
        </div>

        <div className="flex items-center justify-between gap-2 rounded-full bg-brew-paper py-1.5 pr-2 pl-3.5">
          <label htmlFor="pocket-tune-input" className="sr-only">
            Ask Brew to tweak deck
          </label>
          <input
            id="pocket-tune-input"
            type="text"
            value={tuneText}
            onChange={(e) => setTuneText(e.target.value)}
            placeholder="Ask Brew to tweak deck..."
            className="min-w-0 flex-1 bg-transparent text-[12.5px] text-brew-plum placeholder:text-brew-muted focus:outline-none"
          />

          <PrimaryButton
            id="btn-pocket-tune-submit"
            type="submit"
            shape="pill"
            loading={tuning}
            className="!min-h-[32px] shrink-0 !px-3.5 !py-1 !text-xs"
          >
            {tuning ? "..." : "Tune"}
          </PrimaryButton>
        </div>
      </form>
    </div>
  );
}
