import { ArrowRight, Calendar, Check, Smartphone, Sparkles, Upload } from "lucide-react";
import { useState, type ChangeEvent, type JSX } from "react";
import type {
  ApproveMemoryProposalRequest,
  ContactResponse,
  MeetingResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
} from "../../api/types";
import {
  formatCalendarCountdown,
  formatCalendarDayLabel,
  formatCalendarTimeRange,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import { computeBlueprintSplit } from "../../utils/pacingBlueprint";
import { formatPurposeLabel, formatShortTimestamp } from "../formatters";
import { ContactAvatar, Illustration, LoadingSkeleton, PillButton, PrimaryButton } from "../ui";

export interface ClubhouseScreenProps {
  readonly userDisplayName: string;
  readonly contacts: readonly ContactResponse[];
  readonly activeContact: ContactResponse | null;
  readonly meetings: readonly MeetingResponse[];
  readonly activeBrief: PreparationBriefResponse | null;
  readonly pendingProposals: readonly MemoryProposalResponse[];
  readonly memories: readonly MemoryResponse[];
  readonly calendarEvents: readonly CalendarCoffeeChatEvent[];
  readonly loadingWorkspace: boolean;
  readonly googleCalendarAvailable: boolean;
  readonly calendarSyncing: boolean;
  readonly calendarNotice: string | null;
  readonly onOpenCueStudio: (contactId?: string, briefId?: string) => void;
  readonly onOpenPocketMode: (contactId?: string, briefId?: string) => void;
  readonly onOpenSetupWithCalendarEvent: (event: CalendarCoffeeChatEvent) => void;
  readonly onOpenSetupWithSparkText: (sparkText: string) => void;
  readonly onOpenSetupForContact: (contactId: string) => void;
  readonly onOpenNewContactModal: () => void;
  readonly onOpenDebrief: (options?: {
    readonly contactId?: string | null;
    readonly calendarEvent?: CalendarCoffeeChatEvent | null;
  }) => void;
  readonly onOpenJournalFolio: (contactId: string) => void;
  readonly onApproveProposal: (
    proposalId: string,
    payload: ApproveMemoryProposalRequest,
  ) => Promise<MemoryResponse>;
  readonly onConnectGoogleCalendar: () => Promise<void>;
  readonly onImportIcsText: (icsText: string) => void;
}

const AVATAR_TONE_CYCLE = ["mint", "yellow", "peach", "lavender"] as const;

export function ClubhouseScreen({
  userDisplayName,
  contacts,
  activeContact,
  meetings,
  activeBrief,
  pendingProposals,
  memories,
  calendarEvents,
  loadingWorkspace,
  googleCalendarAvailable,
  calendarSyncing,
  calendarNotice,
  onOpenCueStudio,
  onOpenPocketMode,
  onOpenSetupWithCalendarEvent,
  onOpenSetupWithSparkText,
  onOpenSetupForContact,
  onOpenNewContactModal,
  onOpenDebrief,
  onOpenJournalFolio,
  onApproveProposal,
  onConnectGoogleCalendar,
  onImportIcsText,
}: ClubhouseScreenProps): JSX.Element {
  const [sparkInput, setSparkInput] = useState("");
  const [showCalendarImportPanel, setShowCalendarImportPanel] = useState(false);
  const [icsPasteInput, setIcsPasteInput] = useState("");
  const [stampingProposalId, setStampingProposalId] = useState<string | null>(null);

  const userFirstName = userDisplayName.trim().split(/\s+/)[0] || "You";
  const approvedMemories = memories.filter((m) => m.lifecycle_state === "approved");
  const contactById = new Map<string, ContactResponse>(contacts.map((c) => [c.id, c]));

  // Determine the Up-Next featured conversation
  const upNextCalendarEvent =
    calendarEvents.find((ev) => ev.temporalStatus === "up_next") ??
    calendarEvents.find((ev) => ev.temporalStatus === "upcoming") ??
    null;

  const matchedUpNextContact = upNextCalendarEvent
    ? matchCalendarEventContact(upNextCalendarEvent, contacts)
    : null;

  const heroContact =
    (activeBrief ? contactById.get(activeBrief.contact_id) : null) ??
    matchedUpNextContact ??
    activeContact ??
    contacts[0] ??
    null;

  const heroCalendarEvent =
    heroContact && upNextCalendarEvent
      ? matchCalendarEventContact(upNextCalendarEvent, [heroContact])
        ? upNextCalendarEvent
        : activeBrief
          ? null
          : upNextCalendarEvent
      : upNextCalendarEvent;

  const heroHasBrief =
    activeBrief !== null &&
    (heroContact === null || activeBrief.contact_id === heroContact.id);

  const heroCounterpartName =
    heroContact?.name ?? heroCalendarEvent?.counterpartName ?? null;

  const heroKeepsakeCount = heroContact
    ? approvedMemories.filter((m) => m.contact_id === heroContact.id).length
    : 0;

  const heroDuration =
    (heroHasBrief ? activeBrief?.duration_minutes : null) ??
    heroCalendarEvent?.durationMinutes ??
    30;

  const heroSplit = computeBlueprintSplit(heroDuration);

  // Wrapped event for debrief nudge
  const wrappedCalendarEvent =
    calendarEvents.find((ev) => ev.temporalStatus === "wrapped") ?? null;
  const wrappedMatchedContact = wrappedCalendarEvent
    ? matchCalendarEventContact(wrappedCalendarEvent, contacts)
    : null;

  // Upcoming calendar events excluding the featured hero event
  const upcomingCalendarRows = calendarEvents.filter(
    (ev) => ev.temporalStatus !== "wrapped" && ev.id !== heroCalendarEvent?.id,
  );

  // Saved meetings for contacts when calendar events are empty
  const nonCalendarMeetings =
    upcomingCalendarRows.length === 0 && !wrappedCalendarEvent ? meetings.slice(0, 3) : [];

  const topPendingProposal = pendingProposals[0] ?? null;
  const topProposalContactName = topPendingProposal?.contact_id
    ? (contactById.get(topPendingProposal.contact_id)?.name ?? null)
    : null;

  // Warm reconnect candidate: pick a contact other than the hero contact, or fallback to first contact
  const reconnectContact =
    contacts.find((c) => c.id !== heroContact?.id) ?? contacts[0] ?? null;
  const reconnectFollowUp = reconnectContact
    ? approvedMemories.find(
        (m) =>
          m.contact_id === reconnectContact.id &&
          (m.memory_type === "follow_up_commitment" || m.memory_type === "relationship_note"),
      ) ?? approvedMemories.find((m) => m.contact_id === reconnectContact.id)
    : null;

  const handleIcsFileUpload = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string" && reader.result.trim()) {
        onImportIcsText(reader.result);
        setShowCalendarImportPanel(false);
      }
    };
    reader.readAsText(file);
  };

  const handleHeroPrimaryAction = (): void => {
    if (heroHasBrief && activeBrief) {
      onOpenCueStudio(activeBrief.contact_id, activeBrief.id);
      return;
    }
    if (heroCalendarEvent) {
      onOpenSetupWithCalendarEvent(heroCalendarEvent);
      return;
    }
    if (heroContact) {
      onOpenSetupForContact(heroContact.id);
      return;
    }
    onOpenSetupWithSparkText("");
  };

  const handleHeroPocketAction = (): void => {
    if (heroHasBrief && activeBrief) {
      onOpenPocketMode(activeBrief.contact_id, activeBrief.id);
      return;
    }
    handleHeroPrimaryAction();
  };

  if (loadingWorkspace && contacts.length === 0 && calendarEvents.length === 0) {
    return <LoadingSkeleton label="Preparing your Clubhouse..." rows={4} />;
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,136fr)_minmax(0,64fr)] lg:gap-[26px]">
      {/* Left Main Stream Column */}
      <div className="flex min-w-0 flex-col gap-3.5 md:gap-[22px]">
        {/* Up-Next Hero Card */}
        {heroCounterpartName ? (
          <section
            aria-labelledby="clubhouse-hero-heading"
            className="brew-hero-peach overflow-hidden rounded-[28px] p-5 md:grid md:grid-cols-[minmax(0,116fr)_minmax(0,84fr)] md:items-center md:gap-5 md:rounded-[34px] md:px-[30px] md:py-[28px]"
          >
            <div className="flex min-w-0 flex-col gap-2.5 md:gap-[13px]">
              <div className="flex flex-wrap items-center justify-between gap-2 md:justify-start">
                <span className="brew-badge-mint">
                  {heroCalendarEvent
                    ? formatCalendarCountdown(heroCalendarEvent.scheduledStartIso)
                    : heroHasBrief
                      ? `Cue deck v${String(activeBrief.version)} ready`
                      : `${String(heroDuration)}m session`}
                </span>
                {heroCalendarEvent && (
                  <span className="brew-badge-peach !bg-brew-paper">
                    <Calendar className="h-3 w-3 shrink-0" aria-hidden="true" />
                    <span>from GCal</span>
                  </span>
                )}
              </div>

              <h1
                id="clubhouse-hero-heading"
                className="font-serif text-[24px] leading-[1.12] font-bold text-brew-plum md:text-[35px]"
              >
                <span className="md:hidden">Coffee Chat: {heroCounterpartName}</span>
                <span className="hidden md:inline">
                  Coffee Chat: {userFirstName} &lt;&gt; {heroCounterpartName}
                </span>
              </h1>

              <p className="text-[12.5px] leading-[1.52] text-brew-secondary md:text-[14.5px]">
                {heroCalendarEvent && (
                  <>
                    <strong className="font-bold text-brew-plum">
                      {formatCalendarTimeRange(
                        heroCalendarEvent.scheduledStartIso,
                        heroCalendarEvent.scheduledEndIso,
                      )}
                    </strong>{" "}
                    ·{" "}
                  </>
                )}
                {[
                  heroContact?.title,
                  heroContact?.organization ?? heroCalendarEvent?.counterpartOrganization,
                ]
                  .filter(Boolean)
                  .join(" at ") ||
                  heroContact?.role ||
                  formatPurposeLabel(heroCalendarEvent?.purpose ?? "coffee_chat")}
                {heroKeepsakeCount > 0 && (
                  <>
                    {" "}
                    ·{" "}
                    <strong className="font-bold text-brew-plum">
                      {String(heroKeepsakeCount)}{" "}
                      {heroKeepsakeCount === 1 ? "keepsake" : "keepsakes"}
                    </strong>{" "}
                    woven in
                  </>
                )}
              </p>

              {/* Desktop Proportional Mini-Ribbon */}
              {(() => {
                const rawAgenda =
                  heroHasBrief && activeBrief.time_boxed_agenda.length >= 2
                    ? activeBrief.time_boxed_agenda
                    : [
                        {
                          title: "Warm-up",
                          duration_minutes: heroSplit.hookMinutes,
                          description: "",
                        },
                        {
                          title: heroHasBrief
                            ? activeBrief.meeting_objective
                            : "Core Conversation",
                          duration_minutes: heroSplit.coreMinutes,
                          description: "",
                        },
                        {
                          title: "Next Steps",
                          duration_minutes: heroSplit.wrapMinutes,
                          description: "",
                        },
                      ];

                const compactSegments =
                  rawAgenda.length <= 3
                    ? rawAgenda.map((seg) => ({
                        minutes: seg.duration_minutes,
                        label: seg.title,
                        tooltip: `${String(seg.duration_minutes)}m · ${seg.title}`,
                      }))
                    : (() => {
                        const first = rawAgenda[0];
                        const last = rawAgenda[rawAgenda.length - 1];
                        const middle = rawAgenda.slice(1, -1);
                        const middleMinutes = middle.reduce(
                          (acc, item) => acc + item.duration_minutes,
                          0,
                        );
                        return [
                          {
                            minutes: first?.duration_minutes ?? heroSplit.hookMinutes,
                            label: first?.title ?? "Warm-up",
                            tooltip: `${String(first?.duration_minutes ?? heroSplit.hookMinutes)}m · ${first?.title ?? "Warm-up"}`,
                          },
                          {
                            minutes: middleMinutes,
                            label: middle[0]?.title ?? "Core Topics",
                            tooltip: middle
                              .map((m) => `${String(m.duration_minutes)}m ${m.title}`)
                              .join(" + "),
                          },
                          {
                            minutes: last?.duration_minutes ?? heroSplit.wrapMinutes,
                            label: last?.title ?? "Next Steps",
                            tooltip: `${String(last?.duration_minutes ?? heroSplit.wrapMinutes)}m · ${last?.title ?? "Next Steps"}`,
                          },
                        ];
                      })();

                const totalRibbonMinutes = Math.max(
                  1,
                  compactSegments.reduce((acc, s) => acc + s.minutes, 0),
                );
                const minVisualWeight = Math.max(1, Math.round(totalRibbonMinutes * 0.24));
                const ribbonCols = compactSegments
                  .map((s) => `minmax(0, ${String(Math.max(minVisualWeight, s.minutes))}fr)`)
                  .join(" ");

                return (
                  <div
                    style={{ gridTemplateColumns: ribbonCols }}
                    className="hidden min-w-0 max-w-full items-center gap-1.5 overflow-hidden rounded-[16px] border border-[#F3DCD1] bg-white/78 px-2.5 py-2 text-xs md:grid"
                  >
                    {compactSegments.map((seg, idx) => {
                      const bgClass =
                        idx === 0
                          ? "bg-brew-peach"
                          : idx === compactSegments.length - 1
                            ? "bg-brew-mint"
                            : "bg-brew-lavender text-center";
                      return (
                        <span
                          key={`${seg.label}-${String(idx)}`}
                          title={seg.tooltip}
                          className={`min-w-0 truncate rounded-[10px] px-2.5 py-1 font-bold text-brew-plum ${bgClass}`}
                        >
                          {String(seg.minutes)}m {seg.label}
                        </span>
                      );
                    })}
                  </div>
                );
              })()}

              {/* Mobile Hero Illustration + Primary CTA (matches Mockup 06) */}
              <div className="space-y-2.5 pt-1 md:hidden">
                <Illustration
                  name="chat-setup-hero"
                  className="mx-auto h-[132px] w-full"
                />
                <PrimaryButton
                  id="btn-mobile-hero-open-pocket"
                  fullWidth
                  onClick={handleHeroPocketAction}
                >
                  <span>
                    {heroHasBrief ? "Open Pocket Cue Cards" : "Prepare Cue Cards"}
                  </span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </PrimaryButton>
              </div>

              {/* Desktop Action Row (matches Mockup 01) */}
              <div className="hidden items-center gap-2.5 pt-1 md:flex">
                <PrimaryButton
                  id="btn-hero-open-cue-cards"
                  onClick={handleHeroPrimaryAction}
                >
                  <span>{heroHasBrief ? "Open Cue Cards" : "Prepare Cue Cards"}</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </PrimaryButton>

                <PillButton
                  id="btn-hero-pocket-mode"
                  variant="outline"
                  onClick={handleHeroPocketAction}
                >
                  <Smartphone className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Pocket Mode</span>
                </PillButton>
              </div>
            </div>

            <div className="hidden min-w-0 justify-center md:flex">
              <Illustration
                name="chat-setup-hero"
                className="h-[225px] w-full"
              />
            </div>
          </section>
        ) : (
          <section
            aria-labelledby="clubhouse-empty-hero-heading"
            className="brew-hero-peach grid items-center gap-5 overflow-hidden rounded-[34px] p-6 md:grid-cols-[minmax(0,112fr)_minmax(0,88fr)] md:p-8"
          >
            <div className="min-w-0 space-y-3.5">
              <span className="brew-eyebrow">WELCOME TO YOUR CLUBHOUSE</span>
              <h1
                id="clubhouse-empty-hero-heading"
                className="font-serif text-[28px] leading-[1.12] font-bold text-brew-plum md:text-[34px]"
              >
                Walk into every coffee chat warm and prepared
              </h1>
              <p className="text-sm leading-relaxed text-brew-secondary">
                Connect your calendar or spark a conversation in one sentence to synthesize a
                time-boxed cue deck and build lasting relationship memory.
              </p>
              <div className="flex flex-wrap items-center gap-2.5 pt-1">
                <PrimaryButton
                  id="btn-clubhouse-start-spark"
                  onClick={() => onOpenSetupWithSparkText("")}
                >
                  <span>Quick Spark Setup</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </PrimaryButton>
                <PillButton
                  id="btn-clubhouse-add-contact"
                  variant="outline"
                  onClick={onOpenNewContactModal}
                >
                  <span>+ Add Person</span>
                </PillButton>
              </div>
            </div>
            <Illustration name="chat-setup-hero" className="max-h-[225px] w-full" />
          </section>
        )}

        {/* Mobile Standalone Wrapped Debrief Card (matches Mockup 06) */}
        {wrappedCalendarEvent && (
          <div className="brew-card-lavender flex items-center justify-between gap-3 rounded-[22px] px-[18px] py-[15px] md:hidden">
            <div className="min-w-0">
              <div className="brew-eyebrow !text-[10px] !text-[#6A469C]">
                WRAPPED ·{" "}
                {new Intl.DateTimeFormat("en-US", {
                  hour: "numeric",
                  minute: "2-digit",
                }).format(new Date(wrappedCalendarEvent.scheduledEndIso))}
              </div>
              <div className="mt-0.5 truncate text-sm font-extrabold text-brew-plum">
                {wrappedCalendarEvent.counterpartName} · Debrief
              </div>
              <div className="truncate text-xs text-brew-secondary">
                Jot 2 quick takeaways while fresh
              </div>
            </div>
            <PrimaryButton
              id="btn-mobile-wrapped-debrief"
              shape="pill"
              onClick={() =>
                onOpenDebrief({
                  contactId: wrappedMatchedContact?.id ?? null,
                  calendarEvent: wrappedCalendarEvent,
                })
              }
              className="!min-h-[36px] shrink-0 !px-3.5 !py-1.5 !text-xs"
            >
              Log Notes
            </PrimaryButton>
          </div>
        )}

        {/* This Week: Upcoming & Recent Chats */}
        <section
          aria-labelledby="this-week-heading"
          className="brew-card-paper rounded-[22px] p-4.5 md:rounded-[26px] md:px-[26px] md:py-6"
        >
          <div className="mb-3 flex items-center justify-between gap-2 md:mb-4">
            <div>
              <div className="brew-eyebrow">THIS WEEK</div>
              <h2
                id="this-week-heading"
                className="mt-0.5 hidden font-serif text-[22px] font-bold text-brew-plum md:block"
              >
                Upcoming &amp; Recent Chats
              </h2>
            </div>
            {upcomingCalendarRows.length > 0 && (
              <span className="brew-badge-peach !px-2 !py-0.5 !text-[10px] md:hidden">
                from GCal
              </span>
            )}
          </div>

          {!wrappedCalendarEvent &&
          upcomingCalendarRows.length === 0 &&
          nonCalendarMeetings.length === 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[18px] bg-brew-blush/70 px-4 py-3.5 text-sm text-brew-secondary">
              <span>
                No additional chats scheduled this week. Import a calendar invite or start an
                ad-hoc Quick Spark anytime.
              </span>
              <PillButton
                id="btn-this-week-new-spark"
                variant="outline"
                size="sm"
                onClick={() => onOpenSetupWithSparkText("")}
              >
                + Setup Chat
              </PillButton>
            </div>
          ) : (
            <div className="flex flex-col gap-2.5 md:gap-3">
              {/* Desktop Wrapped Debrief Row (matches Mockup 01) */}
              {wrappedCalendarEvent && (
                <div className="brew-card-lavender hidden grid-cols-[112px_1fr_auto] items-center gap-4 rounded-[20px] px-[18px] py-[15px] shadow-none md:grid">
                  <div>
                    <div className="text-[11px] font-extrabold text-[#6E4AA3] uppercase">
                      Wrapped{" "}
                      {new Intl.DateTimeFormat("en-US", {
                        hour: "numeric",
                        minute: "2-digit",
                      }).format(new Date(wrappedCalendarEvent.scheduledEndIso))}
                    </div>
                    <div className="mt-0.5 text-xs text-brew-secondary">
                      {formatCalendarDayLabel(wrappedCalendarEvent.scheduledStartIso)} ·{" "}
                      {String(wrappedCalendarEvent.durationMinutes)}m
                    </div>
                  </div>

                  <div className="flex min-w-0 items-center gap-3">
                    <ContactAvatar name={wrappedCalendarEvent.counterpartName} tone="peach" />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-[15px] font-bold text-brew-plum">
                          {wrappedCalendarEvent.title}
                        </span>
                        <span className="brew-badge-peach !bg-brew-paper !px-2 !py-0.5 !text-[10.5px]">
                          from GCal
                        </span>
                      </div>
                      <p className="truncate text-xs text-brew-secondary">
                        Jot a quick 60-second reflection while the conversation is fresh.
                      </p>
                    </div>
                  </div>

                  <PrimaryButton
                    id="btn-desktop-wrapped-debrief"
                    shape="pill"
                    onClick={() =>
                      onOpenDebrief({
                        contactId: wrappedMatchedContact?.id ?? null,
                        calendarEvent: wrappedCalendarEvent,
                      })
                    }
                    className="!min-h-[38px] !px-4 !py-2 !text-xs"
                  >
                    <span>Capture Debrief</span>
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  </PrimaryButton>
                </div>
              )}

              {/* Upcoming Calendar Rows */}
              {upcomingCalendarRows.map((ev, idx) => {
                const matched = matchCalendarEventContact(ev, contacts);
                const keepsakesForPerson = matched
                  ? approvedMemories.filter((m) => m.contact_id === matched.id).length
                  : 0;
                const avatarTone = AVATAR_TONE_CYCLE[idx % AVATAR_TONE_CYCLE.length] ?? "mint";
                const isPrimaryUpcoming = idx === 0;

                return (
                  <div
                    key={ev.id}
                    className={`flex items-center justify-between gap-3 md:grid md:grid-cols-[112px_1fr_auto] md:gap-4 md:rounded-[20px] md:border md:border-brew-border md:bg-brew-paper md:px-[18px] md:py-[15px] ${
                      idx > 0 ? "border-t border-brew-border pt-2.5 md:border-t" : ""
                    }`}
                  >
                    <div className="hidden md:block">
                      <div className="text-xs font-bold text-brew-plum">
                        {formatCalendarDayLabel(ev.scheduledStartIso)}
                      </div>
                      <div className="mt-0.5 text-xs text-brew-secondary">
                        {new Intl.DateTimeFormat("en-US", {
                          hour: "numeric",
                          minute: "2-digit",
                        }).format(new Date(ev.scheduledStartIso))}{" "}
                        · {String(ev.durationMinutes)}m
                      </div>
                    </div>

                    <div className="flex min-w-0 items-center gap-2.5 md:gap-3">
                      <ContactAvatar
                        name={ev.counterpartName}
                        tone={avatarTone}
                        size="sm"
                      />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-[13.5px] font-bold text-brew-plum md:text-[15px]">
                            {ev.title}
                          </span>
                          <span className="brew-badge-peach hidden !px-2 !py-0.5 !text-[10.5px] md:inline-flex">
                            from GCal
                          </span>
                          {!matched && (
                            <span className="brew-badge-yellow hidden !px-2 !py-0.5 !text-[10.5px] md:inline-flex">
                              New
                            </span>
                          )}
                        </div>
                        <div className="truncate text-[11.5px] text-brew-secondary md:hidden">
                          {formatCalendarDayLabel(ev.scheduledStartIso)}{" "}
                          {new Intl.DateTimeFormat("en-US", {
                            hour: "numeric",
                            minute: "2-digit",
                          }).format(new Date(ev.scheduledStartIso))}{" "}
                          · {String(ev.durationMinutes)}m
                        </div>
                        <div className="hidden truncate text-xs text-brew-secondary md:block">
                          {[
                            matched?.title ?? ev.counterpartRole,
                            `${String(ev.durationMinutes)}m slot`,
                            keepsakesForPerson > 0
                              ? `${String(keepsakesForPerson)} ${keepsakesForPerson === 1 ? "keepsake" : "keepsakes"}`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </div>
                    </div>

                    {isPrimaryUpcoming ? (
                      <button
                        id={`btn-prep-calendar-${ev.id}`}
                        type="button"
                        onClick={() => onOpenSetupWithCalendarEvent(ev)}
                        className="inline-flex min-h-[34px] shrink-0 cursor-pointer items-center gap-1.5 rounded-full bg-brew-coral px-3.5 py-1.5 text-xs font-bold text-brew-plum transition hover:bg-brew-coral-vibrant md:min-h-[38px] md:px-4"
                      >
                        <span className="md:hidden">Prep</span>
                        <span className="hidden md:inline">1-Click Prep</span>
                        <ArrowRight className="hidden h-3.5 w-3.5 md:inline" aria-hidden="true" />
                      </button>
                    ) : (
                      <PillButton
                        id={`btn-prep-calendar-${ev.id}`}
                        variant="outline"
                        size="sm"
                        onClick={() => onOpenSetupWithCalendarEvent(ev)}
                      >
                        <span className="md:hidden">Prep</span>
                        <span className="hidden md:inline">
                          Setup {String(ev.durationMinutes)}m Chat
                        </span>
                      </PillButton>
                    )}
                  </div>
                );
              })}

              {/* Fallback Saved Meetings if Calendar is Empty */}
              {nonCalendarMeetings.map((mtg) => {
                const c = contactById.get(mtg.contact_id);
                return (
                  <div
                    key={mtg.id}
                    className="flex items-center justify-between gap-3 rounded-[20px] border border-brew-border bg-brew-paper px-4 py-3.5"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <ContactAvatar name={c?.name ?? "Guest"} tone="mint" size="sm" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold text-brew-plum">
                          {formatPurposeLabel(mtg.purpose)}: {c?.name ?? "Counterpart"}
                        </div>
                        <div className="truncate text-xs text-brew-secondary">
                          {String(mtg.duration_minutes)}m · {mtg.objective}
                        </div>
                      </div>
                    </div>
                    <PillButton
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (mtg.latest_brief_id) {
                          onOpenCueStudio(mtg.contact_id, mtg.latest_brief_id);
                        } else {
                          onOpenSetupForContact(mtg.contact_id);
                        }
                      }}
                    >
                      {mtg.latest_brief_id ? "Open Deck" : "Prep"}
                    </PillButton>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Mobile Compact Keepsakes Banner (matches Mockup 06) */}
        <div className="brew-card-mint flex items-center justify-between gap-3 rounded-[22px] px-[18px] py-3.5 lg:hidden">
          <div>
            <div className="text-[13.5px] font-bold text-brew-plum">
              {pendingProposals.length > 0
                ? `${String(pendingProposals.length)} ${pendingProposals.length === 1 ? "Keepsake" : "Keepsakes"} to Stamp`
                : "Capture Post-Chat Reflections"}
            </div>
            <div className="text-[11.5px] text-[#235744]">
              {pendingProposals.length > 0
                ? "Review before adding to journal"
                : "Only stamped takeaways are saved"}
            </div>
          </div>
          <button
            id="btn-mobile-clubhouse-review-keepsakes"
            type="button"
            onClick={() => onOpenDebrief()}
            className="brew-badge-coral min-h-[32px] cursor-pointer !px-3 !py-1"
          >
            {pendingProposals.length > 0 ? "Review →" : "Debrief →"}
          </button>
        </div>
      </div>

      {/* Right Desktop Companion Column (matches Mockup 01) */}
      <aside
        aria-label="Quick Spark and Relationship Keepsakes"
        className="hidden flex-col gap-[18px] lg:flex"
      >
        {/* Quick Spark Prep Card */}
        <div className="brew-card-coral rounded-[26px] px-[22px] py-5">
          <div className="brew-eyebrow !text-[#9D4B34]">OFF-CALENDAR CHAT?</div>
          <h2 className="mt-1 font-serif text-[20px] font-bold text-brew-plum">
            Quick Spark Prep
          </h2>
          <p className="mt-1.5 mb-2.5 text-[13px] leading-[1.45] text-brew-secondary">
            Describe an ad-hoc chat in one sentence. Brew sets person, duration, and tone.
          </p>

          <label htmlFor="clubhouse-quick-spark-input" className="sr-only">
            Describe an off-calendar conversation
          </label>
          <textarea
            id="clubhouse-quick-spark-input"
            rows={2}
            value={sparkInput}
            onChange={(e) => setSparkInput(e.target.value)}
            placeholder="“20m casual coffee chat with Jordan Kim at Figma about design token governance...”"
            className="w-full resize-none rounded-[18px] border-[1.5px] border-[#F2CFC0] bg-brew-paper px-3.5 py-2.5 text-[13px] leading-[1.45] text-brew-plum placeholder:text-brew-secondary focus:border-brew-purple focus:outline-none"
          />

          <div className="mt-2.5 flex items-center justify-between gap-2">
            <button
              id="btn-toggle-calendar-import"
              type="button"
              onClick={() => setShowCalendarImportPanel((prev) => !prev)}
              className="cursor-pointer text-[11.5px] font-semibold text-brew-secondary underline-offset-2 hover:text-brew-plum hover:underline"
            >
              Or paste an invite link / .ics
            </button>

            <PrimaryButton
              id="btn-clubhouse-spark-brief"
              shape="pill"
              onClick={() => onOpenSetupWithSparkText(sparkInput)}
              className="!min-h-[36px] !px-4 !py-1.5 !text-[12.5px]"
            >
              Spark Brief
            </PrimaryButton>
          </div>

          {showCalendarImportPanel && (
            <div className="mt-3 space-y-2.5 rounded-[18px] border border-[#F2CFC0] bg-brew-paper p-3 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-brew-plum">Read-only Calendar Import</span>
                {googleCalendarAvailable && (
                  <PillButton
                    id="btn-sync-google-calendar"
                    variant="peach"
                    size="sm"
                    disabled={calendarSyncing}
                    onClick={() => {
                      void onConnectGoogleCalendar();
                    }}
                  >
                    <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>{calendarSyncing ? "Syncing..." : "Sync Google Calendar"}</span>
                  </PillButton>
                )}
              </div>

              <label htmlFor="ics-paste-textarea" className="sr-only">
                Paste iCalendar VEVENT text
              </label>
              <textarea
                id="ics-paste-textarea"
                rows={2}
                value={icsPasteInput}
                onChange={(e) => setIcsPasteInput(e.target.value)}
                placeholder="Paste .ics calendar invite content (BEGIN:VCALENDAR...)"
                className="brew-field-control !min-h-[60px] !p-2.5 !text-xs"
              />

              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-brew-secondary hover:text-brew-plum">
                  <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Upload .ics</span>
                  <input
                    id="ics-file-upload-input"
                    type="file"
                    accept=".ics,text/calendar"
                    onChange={handleIcsFileUpload}
                    className="sr-only"
                  />
                </label>

                <PillButton
                  id="btn-import-ics-submit"
                  variant="outline"
                  size="sm"
                  disabled={!icsPasteInput.trim()}
                  onClick={() => {
                    onImportIcsText(icsPasteInput);
                    setIcsPasteInput("");
                    setShowCalendarImportPanel(false);
                  }}
                >
                  Import Invite
                </PillButton>
              </div>

              {calendarNotice && (
                <p role="status" className="text-[11.5px] font-medium text-[#215A45]">
                  {calendarNotice}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Recent Keepsakes to Stamp Card */}
        <div className="brew-card-mint rounded-[26px] px-[22px] py-5">
          <div className="flex items-center justify-between gap-2">
            <div className="brew-eyebrow !text-[#26634C]">RECENT KEEPSAKES</div>
            {pendingProposals.length > 0 && (
              <span className="brew-badge-coral">
                {String(pendingProposals.length)} to review
              </span>
            )}
          </div>
          <h2 className="mt-1 font-serif text-[20px] font-bold text-brew-plum">
            Keepsakes to Stamp
          </h2>

          {topPendingProposal ? (
            <div className="mt-2.5 rounded-[18px] border border-[#CDE8D9] bg-brew-paper p-3.5">
              <div className="mb-1.5 flex flex-wrap gap-1.5">
                <span className="brew-badge-peach !px-2 !py-0.5 !text-[10.5px]">
                  {topProposalContactName ?? "My Coaching Style"}
                </span>
                {topPendingProposal.supersedes_memory_id && (
                  <span className="brew-badge-yellow !px-2 !py-0.5 !text-[10.5px]">
                    Updates prior note
                  </span>
                )}
              </div>
              <p className="text-[13px] leading-[1.45] font-semibold text-brew-plum">
                “{topPendingProposal.text}”
              </p>
              <div className="mt-2.5 flex justify-end gap-2">
                <PillButton
                  id="btn-clubhouse-edit-keepsake"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    onOpenDebrief({ contactId: topPendingProposal.contact_id })
                  }
                >
                  Edit
                </PillButton>
                <PrimaryButton
                  id="btn-clubhouse-stamp-keepsake"
                  shape="pill"
                  loading={stampingProposalId === topPendingProposal.id}
                  onClick={() => {
                    setStampingProposalId(topPendingProposal.id);
                    void onApproveProposal(topPendingProposal.id, {
                      expected_version: topPendingProposal.version,
                      supersedes_memory_id: topPendingProposal.supersedes_memory_id,
                    }).finally(() => setStampingProposalId(null));
                  }}
                  className="!min-h-[32px] !px-3.5 !py-1 !text-xs"
                >
                  <Check className="h-3 w-3" aria-hidden="true" />
                  <span>Stamp Keep</span>
                </PrimaryButton>
              </div>
            </div>
          ) : (
            <div className="mt-2.5 rounded-[18px] border border-[#CDE8D9] bg-brew-paper p-3.5 text-xs text-brew-secondary">
              <p className="leading-relaxed">
                All candidate keepsakes are reviewed. Capture a post-chat debrief after your next
                conversation to suggest takeaways.
              </p>
              <div className="mt-2.5 flex justify-end">
                <PillButton
                  id="btn-clubhouse-open-debrief"
                  variant="outline"
                  size="sm"
                  onClick={() => onOpenDebrief()}
                >
                  Open Debrief
                </PillButton>
              </div>
            </div>
          )}
        </div>

        {/* Warm Reconnect Card */}
        <div className="brew-card-paper rounded-[26px] px-[22px] py-[18px]">
          <div className="brew-eyebrow">WARM RECONNECT</div>
          <div className="mt-2 grid grid-cols-[116px_1fr] items-center gap-3.5">
            <Illustration
              name="relationship-folio-circle"
              decorative
              className="h-[82px] w-[116px]"
            />
            {reconnectContact ? (
              <div className="min-w-0">
                <button
                  type="button"
                  onClick={() => onOpenJournalFolio(reconnectContact.id)}
                  className="cursor-pointer truncate text-left text-[14.5px] font-bold text-brew-plum hover:underline"
                >
                  {[reconnectContact.name, reconnectContact.title]
                    .filter(Boolean)
                    .join(" · ")}
                </button>
                <div className="mt-0.5 text-xs leading-[1.45] text-brew-secondary">
                  {reconnectFollowUp ? (
                    <>
                      Saved note:{" "}
                      <em>
                        “{reconnectFollowUp.text.slice(0, 62)}
                        {reconnectFollowUp.text.length > 62 ? "..." : ""}”
                      </em>
                    </>
                  ) : (
                    <>
                      Added {formatShortTimestamp(reconnectContact.created_at)} · Tap to view
                      relationship folio
                    </>
                  )}
                </div>
              </div>
            ) : (
              <div>
                <div className="text-[14px] font-bold text-brew-plum">Build your circle</div>
                <div className="mt-0.5 text-xs leading-[1.45] text-brew-secondary">
                  Stamped keepsakes surface thoughtful reconnect prompts over time.
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
