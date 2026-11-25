import { Calendar, ChevronDown, Plus, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import type {
  ContactResponse,
  CreateContactRequest,
  GenerateBriefRequest,
  MeetingPurpose,
  MeetingTone,
  PreparationBriefResponse,
} from "../../api/types";
import {
  formatCalendarDayLabel,
  formatCalendarTimeRange,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import type { CoachingStyleDefaults } from "../../state/coachingDefaultsStore";
import { parseQuickSparkPrompt } from "../../utils/quickSparkParser";
import { computeBlueprintSplit } from "../../utils/pacingBlueprint";
import {
  MEETING_PURPOSE_OPTIONS,
  MEETING_TONE_OPTIONS,
  errorToFeedbackNotice,
  validateBriefGenerationForm,
  type BriefGenerationFieldErrors,
  type FeedbackNotice,
} from "../formatters";
import { StatusBanner } from "../StatusFeedback";
import { ContactAvatar, FormField, Illustration, PrimaryButton } from "../ui";

export interface QuickSparkSetupInitialSeed {
  readonly calendarEvent?: CalendarCoffeeChatEvent | null | undefined;
  readonly contactId?: string | null | undefined;
  readonly sparkText?: string | null | undefined;
}

export interface QuickSparkSetupScreenProps {
  readonly contacts: readonly ContactResponse[];
  readonly calendarEvents: readonly CalendarCoffeeChatEvent[];
  readonly styleDefaults: CoachingStyleDefaults;
  readonly initialSeed: QuickSparkSetupInitialSeed | null;
  readonly onCreateContact: (payload: CreateContactRequest) => Promise<ContactResponse>;
  readonly onGenerateBrief: (payload: GenerateBriefRequest) => Promise<PreparationBriefResponse>;
  readonly onOpenNewContactModal: () => void;
}

const MADLIB_DURATIONS: readonly number[] = [15, 20, 30, 45, 60];

export function QuickSparkSetupScreen({
  contacts,
  calendarEvents,
  styleDefaults,
  initialSeed,
  onCreateContact,
  onGenerateBrief,
  onOpenNewContactModal,
}: QuickSparkSetupScreenProps): JSX.Element {
  const upcomingCalendarSlots = calendarEvents.filter((ev) => ev.temporalStatus !== "wrapped");

  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(() => {
    if (initialSeed?.calendarEvent) {
      return initialSeed.calendarEvent.id;
    }
    if (!initialSeed?.contactId && !initialSeed?.sparkText && upcomingCalendarSlots[0]) {
      return upcomingCalendarSlots[0].id;
    }
    return null;
  });

  const [selectedContactId, setSelectedContactId] = useState<string | null>(() => {
    if (initialSeed?.contactId) {
      return initialSeed.contactId;
    }
    if (initialSeed?.calendarEvent) {
      const matched = matchCalendarEventContact(initialSeed.calendarEvent, contacts);
      return matched?.id ?? null;
    }
    return contacts[0]?.id ?? null;
  });

  const [adHocName, setAdHocName] = useState<string>("");
  const [adHocTitle, setAdHocTitle] = useState<string>("");
  const [adHocOrg, setAdHocOrg] = useState<string>("");
  const [isCreatingAdHoc, setIsCreatingAdHoc] = useState<boolean>(false);

  const [durationMinutes, setDurationMinutes] = useState<number>(
    styleDefaults.defaultDurationMinutes,
  );
  const [tone, setTone] = useState<MeetingTone>(styleDefaults.defaultTone);
  const [purpose, setPurpose] = useState<MeetingPurpose>("coffee_chat");
  const [meetingObjective, setMeetingObjective] = useState<string>("");

  const [showExtraOptions, setShowExtraOptions] = useState<boolean>(false);
  const [customDurationInput, setCustomDurationInput] = useState<string>("");
  const [preferredQuestionCount, setPreferredQuestionCount] = useState<string>("");
  const [focusAreasRaw, setFocusAreasRaw] = useState<string>("");
  const [meetingNotes, setMeetingNotes] = useState<string>("");

  const [fieldErrors, setFieldErrors] = useState<
    BriefGenerationFieldErrors & { readonly counterpart_name?: string }
  >({});
  const [apiNotice, setApiNotice] = useState<FeedbackNotice | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Apply each seed object exactly once. This effect also re-runs when its other
  // dependencies change (every keystroke in the objective field, a refreshed contact
  // list), and re-applying the seed then would overwrite what the user just edited.
  const appliedSeedRef = useRef<QuickSparkSetupInitialSeed | null>(null);
  useEffect(() => {
    if (!initialSeed || appliedSeedRef.current === initialSeed) {
      return;
    }
    appliedSeedRef.current = initialSeed;
    if (initialSeed.calendarEvent) {
      const ev = initialSeed.calendarEvent;
      setSelectedSlotId(ev.id);
      setDurationMinutes(ev.durationMinutes);
      setPurpose(ev.purpose);
      setTone(styleDefaults.defaultTone);
      const matched = matchCalendarEventContact(ev, contacts);
      if (matched) {
        setSelectedContactId(matched.id);
        setIsCreatingAdHoc(false);
      } else {
        setSelectedContactId(null);
        setAdHocName(ev.counterpartName);
        setAdHocOrg(ev.counterpartOrganization ?? "");
        setAdHocTitle(ev.counterpartTitle ?? "");
        setIsCreatingAdHoc(false);
      }
      if (ev.notesExcerpt && !meetingObjective) {
        setMeetingObjective(ev.notesExcerpt.replace(/#brew/gi, "").trim());
      }
      return;
    }

    if (initialSeed.sparkText && initialSeed.sparkText.trim()) {
      setSelectedSlotId(null);
      const parsed = parseQuickSparkPrompt(initialSeed.sparkText);
      if (parsed.durationMinutes) {
        setDurationMinutes(parsed.durationMinutes);
      }
      if (parsed.tone) {
        setTone(parsed.tone);
      }
      if (parsed.purpose) {
        setPurpose(parsed.purpose);
      }
      if (parsed.objective) {
        setMeetingObjective(parsed.objective);
      }
      if (parsed.counterpartName) {
        const lowerTarget = parsed.counterpartName.toLowerCase();
        const existing = contacts.find((c) => c.name.trim().toLowerCase() === lowerTarget);
        if (existing) {
          setSelectedContactId(existing.id);
          setIsCreatingAdHoc(false);
        } else {
          setSelectedContactId(null);
          setAdHocName(parsed.counterpartName);
          setAdHocOrg(parsed.organization ?? "");
          setIsCreatingAdHoc(true);
        }
      }
      return;
    }

    if (initialSeed.contactId) {
      setSelectedSlotId(null);
      setSelectedContactId(initialSeed.contactId);
      setIsCreatingAdHoc(false);
    }
  }, [contacts, initialSeed, meetingObjective, styleDefaults.defaultTone]);

  const activeCalendarSlot =
    upcomingCalendarSlots.find((ev) => ev.id === selectedSlotId) ?? null;

  const displayedCalendarSlots = (() => {
    const topTwo = upcomingCalendarSlots.slice(0, 2);
    if (!activeCalendarSlot || topTwo.some((s) => s.id === activeCalendarSlot.id)) {
      return topTwo;
    }
    const second = upcomingCalendarSlots.find((s) => s.id !== activeCalendarSlot.id);
    return second ? [activeCalendarSlot, second] : [activeCalendarSlot];
  })();

  const activeContact =
    contacts.find((c) => c.id === selectedContactId) ??
    (activeCalendarSlot ? matchCalendarEventContact(activeCalendarSlot, contacts) : null);

  const effectiveCounterpartName = activeContact
    ? activeContact.name
    : activeCalendarSlot && !isCreatingAdHoc
      ? activeCalendarSlot.counterpartName
      : adHocName.trim();

  const effectiveCounterpartSubtitle = (() => {
    if (activeContact) {
      return (
        [activeContact.title, activeContact.organization].filter(Boolean).join(" · ") ||
        activeContact.role ||
        ""
      );
    }
    if (activeCalendarSlot && !isCreatingAdHoc) {
      const roleOrTitle =
        activeCalendarSlot.counterpartTitle ?? activeCalendarSlot.counterpartRole ?? "";
      const org = activeCalendarSlot.counterpartOrganization ?? "";
      if (roleOrTitle && org && roleOrTitle.toLowerCase().includes(org.toLowerCase())) {
        return roleOrTitle;
      }
      return [roleOrTitle, org].filter(Boolean).join(" · ");
    }
    return [adHocTitle.trim(), adHocOrg.trim()].filter(Boolean).join(" · ");
  })();

  const resolvedDuration = customDurationInput.trim()
    ? Number.parseInt(customDurationInput.trim(), 10)
    : durationMinutes;

  const safePreviewDuration =
    Number.isInteger(resolvedDuration) && resolvedDuration >= 5 && resolvedDuration <= 180
      ? resolvedDuration
      : durationMinutes;

  const split = computeBlueprintSplit(safePreviewDuration);

  const handleSelectCalendarSlot = (slot: CalendarCoffeeChatEvent): void => {
    setSelectedSlotId(slot.id);
    setDurationMinutes(slot.durationMinutes);
    setCustomDurationInput("");
    setPurpose(slot.purpose);
    setIsCreatingAdHoc(false);
    const matched = matchCalendarEventContact(slot, contacts);
    setSelectedContactId(matched?.id ?? null);
    if (!matched) {
      setAdHocName(slot.counterpartName);
      setAdHocOrg(slot.counterpartOrganization ?? "");
    }
  };

  const handleSelectSavedContact = (contact: ContactResponse): void => {
    setSelectedSlotId(null);
    setSelectedContactId(contact.id);
    setIsCreatingAdHoc(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setApiNotice(null);

    const validation = validateBriefGenerationForm({
      meetingObjective,
      durationMinutes: resolvedDuration,
      preferredQuestionCount,
      communicationStyleNotes: styleDefaults.defaultStyleNotes,
    });

    const nextErrors: Record<string, string> = { ...validation };
    if (!activeContact && !effectiveCounterpartName) {
      nextErrors["counterpart_name"] = "Enter or select who you are meeting with.";
    }

    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      let targetContactId = activeContact?.id ?? null;
      if (!targetContactId) {
        const createdContact = await onCreateContact({
          name: effectiveCounterpartName,
          title: adHocTitle.trim() || activeCalendarSlot?.counterpartTitle || null,
          organization:
            adHocOrg.trim() || activeCalendarSlot?.counterpartOrganization || null,
          role: activeCalendarSlot?.counterpartRole || null,
          context_notes: null,
        });
        targetContactId = createdContact.id;
      }

      const parsedQuestionCount = preferredQuestionCount.trim()
        ? Number.parseInt(preferredQuestionCount.trim(), 10)
        : null;
      const focusTags = focusAreasRaw
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t.length >= 2)
        .slice(0, 10);
      const trimmedDefaultStyle = styleDefaults.defaultStyleNotes.trim();
      const hasPreferences =
        parsedQuestionCount !== null ||
        trimmedDefaultStyle.length >= 3 ||
        focusTags.length > 0;

      const payload: GenerateBriefRequest = {
        contact_id: targetContactId,
        purpose,
        tone,
        meeting_objective: meetingObjective.trim(),
        duration_minutes: resolvedDuration,
        scheduled_at: activeCalendarSlot?.scheduledStartIso ?? null,
        meeting_notes: meetingNotes.trim() || null,
        preferences: hasPreferences
          ? {
              preferred_question_count: parsedQuestionCount,
              communication_style_notes:
                trimmedDefaultStyle.length >= 3 ? trimmedDefaultStyle : null,
              focus_areas: focusTags.length > 0 ? focusTags : null,
            }
          : null,
      };

      await onGenerateBrief(payload);
    } catch (err: unknown) {
      setApiNotice(errorToFeedbackNotice(err, "Cue deck synthesis failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto grid max-w-[1280px] items-start gap-7 lg:grid-cols-[minmax(0,114fr)_minmax(0,86fr)] lg:gap-[30px]">
      {/* Left Focused Setup Card */}
      <div className="brew-card-paper min-w-0 rounded-[28px] p-6 sm:rounded-[32px] sm:p-8">
        <form
          onSubmit={(e) => void handleSubmit(e)}
          noValidate
          aria-labelledby="conversation-setup-heading"
          className="space-y-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="brew-eyebrow">CONVERSATION SETUP</div>
              <h1
                id="conversation-setup-heading"
                className="mt-1 font-serif text-[26px] leading-tight font-bold text-brew-plum sm:text-[30px]"
              >
                Shape your conversation
              </h1>
            </div>

            {activeCalendarSlot && (
              <span className="brew-badge-peach">
                <Calendar className="h-3 w-3 shrink-0" aria-hidden="true" />
                <span>from GCal</span>
              </span>
            )}
          </div>

          {apiNotice && (
            <StatusBanner
              notice={apiNotice}
              onDismiss={() => setApiNotice(null)}
            />
          )}

          {/* Calendar Invite / Counterpart Slot Picker */}
          {(upcomingCalendarSlots.length > 0 || contacts.length > 0) && (
            <div className="space-y-2">
              <div className="grid gap-2.5 sm:grid-cols-2">
                {displayedCalendarSlots.map((slot, idx) => {
                  const isSelected = selectedSlotId === slot.id && !isCreatingAdHoc;
                  return (
                    <button
                      key={slot.id}
                      id={`btn-setup-slot-${slot.id}`}
                      type="button"
                      onClick={() => handleSelectCalendarSlot(slot)}
                      className={`flex cursor-pointer items-center gap-2.5 rounded-[18px] px-3.5 py-3 text-left transition ${
                        isSelected
                          ? "brew-hero-peach border-2 border-brew-coral shadow-none"
                          : "border border-brew-border bg-brew-blush/75 hover:border-brew-coral/55 hover:bg-brew-blush"
                      }`}
                    >
                      <ContactAvatar
                        name={slot.counterpartName}
                        tone={idx === 0 ? "yellow" : "mint"}
                        size="sm"
                      />
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-extrabold text-brew-plum">
                          {slot.title}
                        </div>
                        <div className="truncate text-[11.5px] text-brew-secondary">
                          {formatCalendarDayLabel(slot.scheduledStartIso)}{" "}
                          {formatCalendarTimeRange(slot.scheduledStartIso, slot.scheduledEndIso)}{" "}
                          · {String(slot.durationMinutes)}m
                        </div>
                      </div>
                    </button>
                  );
                })}

                {upcomingCalendarSlots.length === 0 &&
                  contacts.slice(0, 2).map((c, idx) => {
                    const isSelected = selectedContactId === c.id && !isCreatingAdHoc;
                    return (
                      <button
                        key={c.id}
                        id={`btn-setup-contact-${c.id}`}
                        type="button"
                        onClick={() => handleSelectSavedContact(c)}
                        className={`flex cursor-pointer items-center gap-2.5 rounded-[18px] px-3.5 py-3 text-left transition ${
                          isSelected
                            ? "brew-hero-peach border-2 border-brew-coral shadow-none"
                            : "border border-brew-border bg-brew-blush/75 hover:border-brew-coral/55 hover:bg-brew-blush"
                        }`}
                      >
                        <ContactAvatar
                          name={c.name}
                          tone={idx === 0 ? "mint" : "peach"}
                          size="sm"
                        />
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-extrabold text-brew-plum">
                            {c.name}
                          </div>
                          <div className="truncate text-[11.5px] text-brew-secondary">
                            {[c.title, c.organization].filter(Boolean).join(" · ") ||
                              c.role ||
                              "Saved counterpart"}
                          </div>
                        </div>
                      </button>
                    );
                  })}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 text-xs">
                {contacts.length > 0 && (
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor="setup-saved-contact-select"
                      className="font-semibold text-brew-secondary"
                    >
                      Or saved person:
                    </label>
                    <select
                      id="setup-saved-contact-select"
                      value={selectedSlotId || isCreatingAdHoc ? "" : (selectedContactId ?? "")}
                      onChange={(e) => {
                        const chosen = contacts.find((c) => c.id === e.target.value);
                        if (chosen) {
                          handleSelectSavedContact(chosen);
                        }
                      }}
                      className="rounded-full border border-brew-border bg-brew-paper px-3 py-1 text-xs font-semibold text-brew-plum"
                    >
                      <option value="">Choose person...</option>
                      {contacts.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <button
                    id="btn-setup-adhoc-person"
                    type="button"
                    onClick={() => {
                      setSelectedSlotId(null);
                      setSelectedContactId(null);
                      setIsCreatingAdHoc(true);
                    }}
                    className="inline-flex cursor-pointer items-center gap-1 font-semibold text-brew-secondary hover:text-brew-plum"
                  >
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>Off-calendar person</span>
                  </button>
                  <span aria-hidden="true" className="text-brew-border">
                    ·
                  </span>
                  <button
                    id="btn-setup-open-contact-modal"
                    type="button"
                    onClick={onOpenNewContactModal}
                    className="cursor-pointer font-semibold text-brew-secondary hover:text-brew-plum"
                  >
                    Full profile modal
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Inline Off-Calendar Counterpart Inputs (when no saved contact or calendar slot is selected) */}
          {(isCreatingAdHoc || (!activeContact && !activeCalendarSlot)) && (
            <div className="grid gap-3 rounded-[20px] border border-brew-border bg-brew-bg p-4 sm:grid-cols-3">
              <FormField
                htmlFor="setup-adhoc-name-input"
                label="Who are you meeting?"
                required
                error={fieldErrors.counterpart_name}
              >
                <input
                  id="setup-adhoc-name-input"
                  type="text"
                  maxLength={120}
                  value={adHocName}
                  onChange={(e) => setAdHocName(e.target.value)}
                  placeholder="e.g., Jordan Kim"
                  className="brew-field-control"
                />
              </FormField>

              <FormField htmlFor="setup-adhoc-title-input" label="Title">
                <input
                  id="setup-adhoc-title-input"
                  type="text"
                  maxLength={120}
                  value={adHocTitle}
                  onChange={(e) => setAdHocTitle(e.target.value)}
                  placeholder="e.g., Design Systems Lead"
                  className="brew-field-control"
                />
              </FormField>

              <FormField htmlFor="setup-adhoc-org-input" label="Company">
                <input
                  id="setup-adhoc-org-input"
                  type="text"
                  maxLength={160}
                  value={adHocOrg}
                  onChange={(e) => setAdHocOrg(e.target.value)}
                  placeholder="e.g., Figma"
                  className="brew-field-control"
                />
              </FormField>
            </div>
          )}

          {/* Conversational Mad-Libs Sentence Builder */}
          <div className="rounded-[24px] border border-[#F3DDD4] bg-brew-blush px-5 py-4.5 text-[16px] text-brew-plum">
            <div className="flex flex-wrap items-center gap-2">
              <span>I’m having a</span>
              <label htmlFor="setup-duration-select" className="sr-only">
                Meeting duration
              </label>
              <select
                id="setup-duration-select"
                value={String(durationMinutes)}
                onChange={(e) => {
                  setDurationMinutes(Number.parseInt(e.target.value, 10));
                  setCustomDurationInput("");
                }}
                className="brew-madlib-select border-[1.5px] border-[#F2C8B4] bg-brew-peach"
              >
                {MADLIB_DURATIONS.map((mins) => (
                  <option key={mins} value={String(mins)}>
                    {String(mins)} min
                  </option>
                ))}
              </select>
              <label htmlFor="setup-tone-select" className="sr-only">
                Conversation tone
              </label>
              <select
                id="setup-tone-select"
                value={tone}
                onChange={(e) => setTone(e.target.value as MeetingTone)}
                className="brew-madlib-select border-[1.5px] border-[#D6C4F8] bg-brew-lavender"
              >
                {MEETING_TONE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <label htmlFor="setup-purpose-select" className="sr-only">
                Conversation purpose
              </label>
              <select
                id="setup-purpose-select"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value as MeetingPurpose)}
                className="brew-madlib-select border-[1.5px] border-[#BFE4D0] bg-brew-mint"
              >
                {MEETING_PURPOSE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.value === "networking" ? "Networking Chat" : opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-2.5 leading-snug">
              <span>with </span>
              <strong className="font-extrabold text-brew-plum">
                {effectiveCounterpartName || "your counterpart"}
              </strong>
              {effectiveCounterpartSubtitle && (
                <span className="text-sm text-brew-secondary">
                  {" "}
                  ({effectiveCounterpartSubtitle})
                </span>
              )}
              <span>.</span>
            </div>
          </div>

          {/* Primary Worthwhile Objective Input */}
          <FormField
            htmlFor="setup-objective-input"
            label={`What would make this ${String(safePreviewDuration)}-minute chat feel worthwhile?`}
            required
            error={fieldErrors.meeting_objective}
            errorId="setup-objective-error"
          >
            <textarea
              id="setup-objective-input"
              rows={3}
              required
              maxLength={500}
              value={meetingObjective}
              onChange={(e) => setMeetingObjective(e.target.value)}
              aria-invalid={fieldErrors.meeting_objective ? "true" : "false"}
              aria-describedby={
                fieldErrors.meeting_objective ? "setup-objective-error" : undefined
              }
              placeholder="e.g., Learn how Priya bridges Figma token pipelines with engineering PR checks, and ask for one candid piece of career advice."
              className="brew-field-control"
            />
          </FormField>

          {/* Unobtrusive Disclosure for Optional Fine-Tuning (Question Count / Custom Duration / Focus Areas) */}
          <div>
            <button
              id="btn-toggle-setup-extra-options"
              type="button"
              aria-expanded={showExtraOptions}
              onClick={() => setShowExtraOptions((prev) => !prev)}
              className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-brew-secondary hover:text-brew-plum"
            >
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform ${showExtraOptions ? "rotate-180" : ""}`}
                aria-hidden="true"
              />
              <span>Fine-tune question count, custom length, or pre-chat notes</span>
            </button>

            {showExtraOptions && (
              <div className="mt-3 grid gap-3.5 rounded-[20px] border border-brew-border bg-brew-bg p-4 sm:grid-cols-3">
                <FormField
                  htmlFor="setup-custom-duration-input"
                  label="Custom duration (5-180m)"
                  error={fieldErrors.duration_minutes}
                >
                  <input
                    id="setup-custom-duration-input"
                    type="number"
                    min={5}
                    max={180}
                    value={customDurationInput}
                    onChange={(e) => setCustomDurationInput(e.target.value)}
                    placeholder={String(durationMinutes)}
                    className="brew-field-control font-mono-code"
                  />
                </FormField>

                <FormField
                  htmlFor="pref-question-count-input"
                  label="Question count (1-15)"
                  error={fieldErrors.preferred_question_count}
                >
                  <input
                    id="pref-question-count-input"
                    type="number"
                    min={1}
                    max={15}
                    value={preferredQuestionCount}
                    onChange={(e) => setPreferredQuestionCount(e.target.value)}
                    placeholder="Auto"
                    className="brew-field-control font-mono-code"
                  />
                </FormField>

                <FormField htmlFor="pref-focus-areas-input" label="Focus areas">
                  <input
                    id="pref-focus-areas-input"
                    type="text"
                    value={focusAreasRaw}
                    onChange={(e) => setFocusAreasRaw(e.target.value)}
                    placeholder="e.g., tokens, career"
                    className="brew-field-control"
                  />
                </FormField>

                <FormField
                  htmlFor="setup-prechat-notes-input"
                  label="Optional pre-chat notes"
                  className="sm:col-span-3"
                >
                  <input
                    id="setup-prechat-notes-input"
                    type="text"
                    maxLength={2000}
                    value={meetingNotes}
                    onChange={(e) => setMeetingNotes(e.target.value)}
                    placeholder="Any specific article, talk, or project context to weave in"
                    className="brew-field-control"
                  />
                </FormField>
              </div>
            )}
          </div>

          {fieldErrors.duration_minutes && !showExtraOptions && (
            <p role="alert" className="text-xs font-semibold text-[#9E3426]">
              {fieldErrors.duration_minutes}
            </p>
          )}

          {/* Primary CTA: Exact Approved Label "Synthesize Cue Deck" */}
          <div className="flex justify-end pt-2">
            <PrimaryButton
              id="btn-submit-generate-brief"
              type="submit"
              loading={submitting}
              className="w-full sm:w-auto sm:px-7 sm:py-3.5 sm:text-[14.5px]"
            >
              <span>{submitting ? "Synthesizing Cue Deck..." : "Synthesize Cue Deck"}</span>
              {!submitting && <Sparkles className="h-4 w-4" aria-hidden="true" />}
            </PrimaryButton>
          </div>
        </form>
      </div>

      {/* Right Illustrated Pacing Blueprint Card */}
      <aside
        aria-label="Conversation pacing blueprint"
        className="brew-hero-peach flex min-w-0 flex-col gap-[18px] rounded-[30px] p-6 sm:rounded-[34px] sm:p-7"
      >
        <Illustration
          name="chat-setup-hero"
          className="mx-auto h-[230px] w-full"
        />

        <div className="brew-card-paper rounded-[24px] p-5 shadow-none">
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="brew-eyebrow">
              {String(safePreviewDuration)}-MINUTE PACING BLUEPRINT
            </span>
            <span className="font-mono-code text-xs font-bold text-[#6E4AA3]">
              {String(safePreviewDuration)} min
            </span>
          </div>

          <div
            className="mb-3.5 grid gap-1.5 overflow-hidden text-center"
            style={{
              gridTemplateColumns: `minmax(0, ${String(Math.max(3, Math.round(safePreviewDuration * 0.2), split.hookMinutes))}fr) minmax(0, ${String(Math.max(4, split.coreMinutes))}fr) minmax(0, ${String(Math.max(3, Math.round(safePreviewDuration * 0.2), split.wrapMinutes))}fr)`,
            }}
          >
            <div className="min-w-0 rounded-[14px] bg-brew-peach px-2 py-2.5">
              <div className="truncate text-sm font-extrabold text-brew-plum">
                {String(split.hookMinutes)}m
              </div>
              <div className="truncate text-[10.5px] text-brew-secondary">Hook</div>
            </div>
            <div className="min-w-0 rounded-[14px] bg-brew-lavender px-2 py-2.5">
              <div className="truncate text-sm font-extrabold text-brew-plum">
                {String(split.coreMinutes)}m
              </div>
              <div className="truncate text-[10.5px] text-brew-secondary">
                {split.questionTargetLabel}
              </div>
            </div>
            <div className="min-w-0 rounded-[14px] bg-brew-mint px-2 py-2.5">
              <div className="truncate text-sm font-extrabold text-brew-plum">
                {String(split.wrapMinutes)}m
              </div>
              <div className="truncate text-[10.5px] text-brew-secondary">Wrap</div>
            </div>
          </div>

          <p className="text-[12.5px] leading-[1.52] text-brew-secondary">
            Because this slot is{" "}
            <strong className="font-bold text-brew-plum">
              {String(safePreviewDuration)} minutes
            </strong>
            , Brew paces your deck around{" "}
            <strong className="font-bold text-brew-plum">
              {split.questionTargetLabel.toLowerCase()}
            </strong>{" "}
            (starring the top 2 for Pocket Glance) so you finish right on time.
          </p>
        </div>
      </aside>
    </div>
  );
}
