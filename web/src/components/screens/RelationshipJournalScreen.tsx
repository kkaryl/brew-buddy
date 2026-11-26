import {
  ArrowRight,
  Calendar,
  CheckCircle2,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useState, type ChangeEvent, type FormEvent, type JSX } from "react";
import type { HealthPayload } from "../../api/health";
import type {
  AuthenticatedPrincipalResponse,
  ContactResponse,
  MeetingResponse,
  MeetingTone,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
  UpdateMemoryRequest,
} from "../../api/types";
import {
  formatCalendarDayLabel,
  formatCalendarTimeRange,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import type { CoachingStyleDefaults } from "../../state/coachingDefaultsStore";
import { ApprovedKeepsakeCard } from "../domain/KeepsakeCard";
import {
  DURATION_PRESETS,
  MEETING_TONE_OPTIONS,
  errorToFeedbackNotice,
  formatPurposeLabel,
  formatShortTimestamp,
  formatToneLabel,
  type FeedbackNotice,
} from "../formatters";
import { StatusBanner } from "../StatusFeedback";
import {
  ContactAvatar,
  FormField,
  Illustration,
  PillButton,
  PrimaryButton,
  SegmentedChoice,
} from "../ui";

export type JournalFolioSelection =
  | { readonly kind: "coaching_style" }
  | { readonly kind: "all_memories" }
  | { readonly kind: "contact"; readonly contactId: string };

export interface RelationshipJournalScreenProps {
  readonly userDisplayName: string;
  readonly customDisplayName?: string | null | undefined;
  readonly accountDisplayName?: string | null | undefined;
  readonly userId: string;
  readonly isLocalMock: boolean;
  readonly contacts: readonly ContactResponse[];
  readonly activeContactId: string | null;
  readonly meetingsByContact: ReadonlyMap<string, readonly MeetingResponse[]>;
  readonly activeBrief: PreparationBriefResponse | null;
  readonly pendingProposals: readonly MemoryProposalResponse[];
  readonly memories: readonly MemoryResponse[];
  readonly calendarEvents: readonly CalendarCoffeeChatEvent[];
  readonly includeSuperseded: boolean;
  readonly initialFolioMode: "contact" | "coaching_style";
  readonly styleDefaults: CoachingStyleDefaults;
  readonly health:
    | { readonly kind: "loading" }
    | { readonly kind: "ready"; readonly data: HealthPayload }
    | { readonly kind: "error"; readonly message: string };
  readonly googleCalendarAvailable: boolean;
  readonly calendarSyncing: boolean;
  readonly onSelectContactFolio: (contactId: string) => Promise<void>;
  readonly onOpenNewContactModal: () => void;
  readonly onOpenCueStudioForContact: (contactId: string, briefId?: string | null) => void;
  readonly onOpenSetupForContact: (contactId: string) => void;
  readonly onOpenDebrief: (contactId?: string | null) => void;
  readonly onToggleIncludeSuperseded: (next: boolean) => void;
  readonly onUpdateMemory: (memoryId: string, payload: UpdateMemoryRequest) => Promise<MemoryResponse>;
  readonly onDeleteMemory: (memoryId: string, expectedVersion: number) => Promise<void>;
  readonly onDeleteContact?:
    | ((contactId: string, expectedVersion?: number) => Promise<void>)
    | undefined;
  readonly onDeleteBrief?:
    | ((briefId: string, expectedVersion?: number) => Promise<void>)
    | undefined;
  readonly onSaveStyleDefaults: (next: CoachingStyleDefaults) => void;
  readonly onUpdateDisplayName?: ((displayName: string | null) => Promise<AuthenticatedPrincipalResponse>) | undefined;
  readonly onConnectGoogleCalendar: () => Promise<void>;
  readonly onImportIcsText: (icsText: string) => void;
  readonly onClearCalendarEvents: () => void;
  readonly onRefreshHealth: () => void;
  readonly onSignOut: () => void;
}

const AVATAR_TONES = ["mint", "peach", "yellow", "lavender"] as const;

export function RelationshipJournalScreen({
  userDisplayName,
  customDisplayName = null,
  accountDisplayName = null,
  userId,
  isLocalMock,
  contacts,
  activeContactId,
  meetingsByContact,
  activeBrief,
  pendingProposals,
  memories,
  calendarEvents,
  includeSuperseded,
  initialFolioMode,
  styleDefaults,
  health,
  googleCalendarAvailable,
  calendarSyncing,
  onSelectContactFolio,
  onOpenNewContactModal,
  onOpenCueStudioForContact,
  onOpenSetupForContact,
  onOpenDebrief,
  onToggleIncludeSuperseded,
  onUpdateMemory,
  onDeleteMemory,
  onDeleteContact,
  onDeleteBrief,
  onSaveStyleDefaults,
  onUpdateDisplayName,
  onConnectGoogleCalendar,
  onImportIcsText,
  onClearCalendarEvents,
  onRefreshHealth,
  onSignOut,
}: RelationshipJournalScreenProps): JSX.Element {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFolio, setSelectedFolio] = useState<JournalFolioSelection>(() => {
    if (initialFolioMode === "coaching_style" || contacts.length === 0) {
      return { kind: "coaching_style" };
    }
    const targetId = activeContactId ?? contacts[0]?.id;
    return targetId ? { kind: "contact", contactId: targetId } : { kind: "coaching_style" };
  });

  const [defaultDuration, setDefaultDuration] = useState<string>(
    String(styleDefaults.defaultDurationMinutes),
  );
  const [defaultTone, setDefaultTone] = useState<MeetingTone>(styleDefaults.defaultTone);
  const [defaultStyleNotes, setDefaultStyleNotes] = useState<string>(
    styleDefaults.defaultStyleNotes,
  );
  const [savedDefaultsNotice, setSavedDefaultsNotice] = useState(false);

  const [displayNameInput, setDisplayNameInput] = useState<string>(
    customDisplayName ?? userDisplayName,
  );
  const [displayNameError, setDisplayNameError] = useState<string | null>(null);
  const [savingDisplayName, setSavingDisplayName] = useState(false);
  const [savedDisplayNameNotice, setSavedDisplayNameNotice] = useState<string | null>(null);
  const [confirmDeleteContactId, setConfirmDeleteContactId] = useState<string | null>(null);
  const [deletingContact, setDeletingContact] = useState(false);
  const [confirmDeleteBriefId, setConfirmDeleteBriefId] = useState<string | null>(null);
  const [deletingBrief, setDeletingBrief] = useState(false);

  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  useEffect(() => {
    if (initialFolioMode === "coaching_style") {
      setSelectedFolio({ kind: "coaching_style" });
      return;
    }
    if (activeContactId) {
      setSelectedFolio({ kind: "contact", contactId: activeContactId });
    }
  }, [activeContactId, initialFolioMode]);

  useEffect(() => {
    setDefaultDuration(String(styleDefaults.defaultDurationMinutes));
    setDefaultTone(styleDefaults.defaultTone);
    setDefaultStyleNotes(styleDefaults.defaultStyleNotes);
  }, [styleDefaults]);

  useEffect(() => {
    setDisplayNameInput(customDisplayName ?? userDisplayName);
  }, [customDisplayName, userDisplayName]);

  const userFirstName = userDisplayName.trim().split(/\s+/)[0] || "You";
  const normalizedQuery = searchQuery.trim().toLowerCase();

  const contactNameById = new Map<string, string>(contacts.map((c) => [c.id, c.name]));

  const filteredContacts = contacts.filter((c) => {
    if (!normalizedQuery) {
      return true;
    }
    const haystack = [c.name, c.title, c.organization, c.role, c.context_notes]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (haystack.includes(normalizedQuery)) {
      return true;
    }
    return memories.some(
      (m) => m.contact_id === c.id && m.text.toLowerCase().includes(normalizedQuery),
    );
  });

  const personalMemories = memories.filter((m) => m.scope === "user_preference");
  const activePersonalCount = personalMemories.filter(
    (m) => m.lifecycle_state === "approved",
  ).length;

  const selectedContact =
    selectedFolio.kind === "contact"
      ? (contacts.find((c) => c.id === selectedFolio.contactId) ?? contacts[0] ?? null)
      : null;

  const contactMemories = selectedContact
    ? memories.filter((m) => m.scope === "contact" && m.contact_id === selectedContact.id)
    : [];

  const activeContactMemoriesCount = contactMemories.filter(
    (m) => m.lifecycle_state === "approved",
  ).length;

  const contactMeetings = selectedContact
    ? (meetingsByContact.get(selectedContact.id) ?? [])
    : [];

  const contactCalendarEvent = selectedContact
    ? (calendarEvents.find(
        (ev) => matchCalendarEventContact(ev, [selectedContact]) !== null,
      ) ?? null)
    : null;

  const pendingForSelectedContact = selectedContact
    ? pendingProposals.filter((p) => p.contact_id === selectedContact.id)
    : [];

  const handleSaveDefaults = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const parsedDuration = Number.parseInt(defaultDuration, 10);
    onSaveStyleDefaults({
      defaultDurationMinutes: Number.isNaN(parsedDuration) ? 30 : parsedDuration,
      defaultTone,
      defaultStyleNotes: defaultStyleNotes.trim(),
    });
    setSavedDefaultsNotice(true);
  };

  const handleSaveDisplayName = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!onUpdateDisplayName) {
      return;
    }
    const cleaned = displayNameInput.replace(/\u2014/g, "-").trim();
    if (cleaned.length < 1 || cleaned.length > 120) {
      setDisplayNameError("Enter a display name between 1 and 120 characters.");
      setSavedDisplayNameNotice(null);
      return;
    }
    setDisplayNameError(null);
    setSavedDisplayNameNotice(null);
    setFeedback(null);
    setSavingDisplayName(true);
    try {
      const updated = await onUpdateDisplayName(cleaned);
      setDisplayNameInput(updated.custom_display_name ?? updated.display_name ?? cleaned);
      setSavedDisplayNameNotice("Display name updated");
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not update display name"));
    } finally {
      setSavingDisplayName(false);
    }
  };

  const handleResetDisplayName = async (): Promise<void> => {
    if (!onUpdateDisplayName) {
      return;
    }
    setDisplayNameError(null);
    setSavedDisplayNameNotice(null);
    setFeedback(null);
    setSavingDisplayName(true);
    try {
      const updated = await onUpdateDisplayName(null);
      setDisplayNameInput(updated.display_name ?? "");
      setSavedDisplayNameNotice(
        isLocalMock ? "Reverted to default persona name" : "Reverted to Google account name",
      );
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not reset display name"));
    } finally {
      setSavingDisplayName(false);
    }
  };

  const handleUpdateMemoryWrapped = async (
    memoryId: string,
    payload: UpdateMemoryRequest,
  ): Promise<void> => {
    setFeedback(null);
    try {
      await onUpdateMemory(memoryId, payload);
      setFeedback({
        kind: "success",
        title: "Keepsake updated",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not update keepsake"));
      throw err;
    }
  };

  const handleDeleteMemoryWrapped = async (
    memoryId: string,
    expectedVersion: number,
  ): Promise<void> => {
    setFeedback(null);
    try {
      await onDeleteMemory(memoryId, expectedVersion);
      setFeedback({
        kind: "info",
        title: "Keepsake removed from journal",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not delete keepsake"));
      throw err;
    }
  };

  const handleDeleteContactWrapped = async (contact: ContactResponse): Promise<void> => {
    if (!onDeleteContact) {
      return;
    }
    setFeedback(null);
    setDeletingContact(true);
    try {
      const remaining = contacts.filter((c) => c.id !== contact.id);
      await onDeleteContact(contact.id, contact.version);
      setConfirmDeleteContactId(null);
      setConfirmDeleteBriefId(null);
      const nextContact = remaining[0] ?? null;
      setSelectedFolio(
        nextContact ? { kind: "contact", contactId: nextContact.id } : { kind: "coaching_style" },
      );
      setFeedback({
        kind: "info",
        title: `Removed ${contact.name} along with their briefs and keepsakes`,
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not delete contact"));
    } finally {
      setDeletingContact(false);
    }
  };

  const handleDeleteBriefWrapped = async (briefId: string): Promise<void> => {
    if (!onDeleteBrief) {
      return;
    }
    setFeedback(null);
    setDeletingBrief(true);
    try {
      await onDeleteBrief(briefId);
      setConfirmDeleteBriefId(null);
      setFeedback({
        kind: "info",
        title: "Cue deck removed",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not delete cue deck"));
    } finally {
      setDeletingBrief(false);
    }
  };

  const handleIcsUpload = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string" && reader.result.trim()) {
        onImportIcsText(reader.result);
      }
    };
    reader.readAsText(file);
  };

  const shortToneWord = formatToneLabel(styleDefaults.defaultTone).split(" ")[0] ?? "Warm";

  return (
    <div className="space-y-4">
      {feedback && (
        <StatusBanner notice={feedback} onDismiss={() => setFeedback(null)} />
      )}

      {pendingProposals.length > 0 && (
        <div className="brew-card-lavender flex flex-wrap items-center justify-between gap-3 rounded-[20px] px-4.5 py-3 lg:hidden">
          <span className="text-xs font-bold text-brew-plum">
            {String(pendingProposals.length)}{" "}
            {pendingProposals.length === 1 ? "keepsake awaits" : "keepsakes await"} your stamp
          </span>
          <PillButton
            id="btn-journal-banner-review"
            variant="peach"
            size="sm"
            onClick={() => onOpenDebrief()}
          >
            Review &amp; Stamp
          </PillButton>
        </div>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,37fr)_minmax(0,63fr)] lg:gap-[26px]">
        {/* Left Master Folio Rail (matches Mockup 05) */}
        <div className="flex min-w-0 flex-col gap-3.5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="brew-eyebrow">RELATIONSHIP ATLAS</div>
              <h1 className="mt-0.5 font-serif text-[28px] leading-tight font-bold text-brew-plum">
                Folios &amp; Memory
              </h1>
            </div>

            <PillButton
              id="btn-journal-new-person"
              variant="outline"
              size="sm"
              onClick={onOpenNewContactModal}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Person</span>
            </PillButton>
          </div>

          {/* Search Input */}
          <div className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2 text-brew-muted"
              aria-hidden="true"
            />
            <label htmlFor="journal-search-input" className="sr-only">
              Search people, companies, or keepsakes
            </label>
            <input
              id="journal-search-input"
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search people, companies, or keepsakes..."
              className="min-h-[42px] w-full rounded-full border border-brew-border bg-brew-paper py-2 pr-4 pl-10 text-[13.5px] text-brew-plum placeholder:text-brew-muted focus:border-brew-purple focus:outline-none"
            />
          </div>

          {/* My Coaching Style Card */}
          <button
            id="btn-select-coaching-style-folio"
            type="button"
            onClick={() => setSelectedFolio({ kind: "coaching_style" })}
            className={`brew-card-mint flex w-full cursor-pointer items-center justify-between gap-3 rounded-[22px] px-[18px] py-3.5 text-left transition ${
              selectedFolio.kind === "coaching_style"
                ? "!border-2 !border-brew-mint-deep"
                : ""
            }`}
          >
            <div className="flex min-w-0 items-center gap-3">
              <ContactAvatar
                name={userDisplayName}
                tone="lavender"
                size="md"
                singleInitial
              />
              <div className="min-w-0">
                <div className="truncate text-[14.5px] font-extrabold text-brew-plum">
                  My Coaching Style ({userFirstName})
                </div>
                <div className="truncate text-xs text-[#235744]">
                  {String(activePersonalCount)} personal{" "}
                  {activePersonalCount === 1 ? "preference" : "preferences"} ·{" "}
                  {String(styleDefaults.defaultDurationMinutes)}m {shortToneWord}
                </div>
              </div>
            </div>
            <span className="brew-badge-mint !bg-brew-paper">Edit</span>
          </button>

          {/* Counterpart Folios List */}
          <div className="brew-card-paper flex flex-col gap-1.5 rounded-[26px] p-3">
            {filteredContacts.length === 0 ? (
              <div className="px-3 py-5 text-center text-xs text-brew-secondary">
                {contacts.length === 0
                  ? "No people saved yet. Add a counterpart or prep a calendar chat to create their folio."
                  : "No folios match your search."}
              </div>
            ) : (
              filteredContacts.map((contact, idx) => {
                const isSelected =
                  selectedFolio.kind === "contact" && selectedFolio.contactId === contact.id;
                const pendingCount = pendingProposals.filter(
                  (p) => p.contact_id === contact.id,
                ).length;
                const keepsakesCount = memories.filter(
                  (m) =>
                    m.contact_id === contact.id && m.lifecycle_state === "approved",
                ).length;
                const tone = AVATAR_TONES[idx % AVATAR_TONES.length] ?? "mint";

                return (
                  <button
                    key={contact.id}
                    id={`btn-folio-contact-${contact.id}`}
                    type="button"
                    onClick={() => {
                      setSelectedFolio({ kind: "contact", contactId: contact.id });
                      void onSelectContactFolio(contact.id);
                    }}
                    className={`flex w-full cursor-pointer items-center justify-between gap-3 rounded-[18px] px-3.5 py-3 text-left transition ${
                      isSelected
                        ? "brew-hero-peach !border-[1.5px] !border-brew-coral shadow-none"
                        : "hover:bg-brew-blush/60"
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <ContactAvatar name={contact.name} tone={tone} size="md" />
                      <div className="min-w-0">
                        <div
                          className={`truncate text-[14.5px] text-brew-plum ${
                            isSelected ? "font-extrabold" : "font-bold"
                          }`}
                        >
                          {contact.name}
                        </div>
                        <div className="truncate text-xs text-brew-secondary">
                          {[contact.title, contact.organization].filter(Boolean).join(" · ") ||
                            contact.role ||
                            "Counterpart"}
                        </div>
                      </div>
                    </div>

                    {pendingCount > 0 ? (
                      <span className="brew-badge-coral">
                        {String(pendingCount)} to stamp
                      </span>
                    ) : isSelected ? (
                      <span className="brew-badge-peach !bg-brew-paper">
                        {String(keepsakesCount)}{" "}
                        {keepsakesCount === 1 ? "keepsake" : "keepsakes"}
                      </span>
                    ) : (
                      <span className="text-xs whitespace-nowrap text-brew-secondary">
                        {String(keepsakesCount)}{" "}
                        {keepsakesCount === 1 ? "keepsake" : "keepsakes"}
                      </span>
                    )}
                  </button>
                );
              })
            )}

            {memories.length > 0 && (
              <div className="border-t border-brew-border pt-2 text-center">
                <button
                  id="btn-select-all-memories-folio"
                  type="button"
                  onClick={() => setSelectedFolio({ kind: "all_memories" })}
                  className={`cursor-pointer text-xs font-semibold ${
                    selectedFolio.kind === "all_memories"
                      ? "text-[#6E4AA3] underline"
                      : "text-brew-secondary hover:text-brew-plum"
                  }`}
                >
                  View all {String(memories.length)} workspace keepsakes
                </button>
              </div>
            )}
          </div>

          {/* Illustrated Companion Card (matches Mockup 05) */}
          <div className="brew-hero-peach flex flex-col items-center gap-2 rounded-[24px] px-4.5 py-4 text-center shadow-none">
            <Illustration
              name="relationship-folio-circle"
              decorative
              className="h-[118px] w-full"
            />
            <p className="text-[12.5px] leading-[1.4] text-brew-secondary">
              Every stamped keepsake compounds warmly across future coffee chats.
            </p>
          </div>
        </div>

        {/* Right Detail Folio Pane */}
        <section
          aria-label="Selected relationship folio"
          className="brew-card-paper flex min-w-0 flex-col gap-5.5 rounded-[28px] p-6 sm:rounded-[32px] sm:px-8 sm:py-7"
        >
          {selectedFolio.kind === "contact" && selectedContact ? (
            <>
              {/* Counterpart Dossier Header */}
              <div className="flex flex-col gap-3 border-b border-brew-border pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 flex-1 items-center gap-4">
                  <ContactAvatar
                    name={selectedContact.name}
                    tone="mint"
                    size="lg"
                    className="h-[60px] w-[60px] shrink-0 text-[20px]"
                  />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <h2 className="font-serif text-[26px] leading-tight font-bold text-brew-plum sm:text-[30px]">
                        {selectedContact.name}
                      </h2>
                      {selectedContact.role && (
                        <span className="brew-badge-lavender">{selectedContact.role}</span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-brew-secondary">
                      {[
                        [selectedContact.title, selectedContact.organization]
                          .filter(Boolean)
                          .join(" at "),
                        selectedContact.context_notes,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "Saved relationship folio"}
                    </p>
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-2 sm:pt-1">
                  {pendingForSelectedContact.length > 0 && (
                    <PillButton
                      id="btn-folio-review-pending"
                      variant="peach"
                      size="sm"
                      onClick={() => onOpenDebrief(selectedContact.id)}
                    >
                      Stamp {String(pendingForSelectedContact.length)} Pending
                    </PillButton>
                  )}

                  <PrimaryButton
                    id="btn-folio-open-brief"
                    shape="pill"
                    onClick={() => {
                      const briefId =
                        activeBrief?.contact_id === selectedContact.id
                          ? activeBrief.id
                          : (contactMeetings.find((m) => m.latest_brief_id)?.latest_brief_id ??
                            null);
                      if (briefId) {
                        onOpenCueStudioForContact(selectedContact.id, briefId);
                      } else {
                        onOpenSetupForContact(selectedContact.id);
                      }
                    }}
                    className="!min-h-[42px] !px-5 !py-2.5 !text-[13px]"
                  >
                    <span>
                      {(activeBrief?.contact_id === selectedContact.id ||
                        contactMeetings.some((m) => m.latest_brief_id))
                        ? "Open Brief"
                        : "Prep Chat"}
                    </span>
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </PrimaryButton>

                  {onDeleteContact && (
                    <PillButton
                      id={`btn-delete-contact-${selectedContact.id}`}
                      variant="ghost"
                      size="sm"
                      disabled={deletingContact}
                      aria-label={`Delete ${selectedContact.name}`}
                      onClick={() =>
                        setConfirmDeleteContactId((prev) =>
                          prev === selectedContact.id ? null : selectedContact.id,
                        )
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>Delete</span>
                    </PillButton>
                  )}
                </div>
              </div>

              {confirmDeleteContactId === selectedContact.id && onDeleteContact && (
                <div
                  role="region"
                  aria-label={`Confirm deletion of ${selectedContact.name}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-[22px] border border-[#F2C2BA] bg-[#FFF5F3] p-4 sm:px-5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-serif text-[17px] font-bold text-brew-plum">
                      Delete {selectedContact.name} from your journal?
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-brew-secondary">
                      Removes {selectedContact.name}, along with their preparation briefs, chat
                      history, and {String(contactMemories.length)}{" "}
                      {contactMemories.length === 1 ? "keepsake" : "keepsakes"}
                      {pendingForSelectedContact.length > 0
                        ? ` (${String(pendingForSelectedContact.length)} pending)`
                        : ""}
                      . Personal coaching preferences stay untouched.
                    </p>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <PillButton
                      id={`btn-cancel-delete-contact-${selectedContact.id}`}
                      variant="outline"
                      size="sm"
                      disabled={deletingContact}
                      onClick={() => setConfirmDeleteContactId(null)}
                    >
                      Cancel
                    </PillButton>
                    <PillButton
                      id={`btn-confirm-delete-contact-${selectedContact.id}`}
                      variant="danger"
                      size="sm"
                      disabled={deletingContact}
                      onClick={() => {
                        void handleDeleteContactWrapped(selectedContact);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>{deletingContact ? "Deleting..." : "Confirm Delete"}</span>
                    </PillButton>
                  </div>
                </div>
              )}

              {/* Relationship Keepsakes Grid */}
              <div>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="brew-eyebrow">
                    RELATIONSHIP KEEPSAKES ({String(activeContactMemoriesCount)})
                  </div>

                  <label
                    htmlFor="toggle-show-superseded"
                    className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-brew-secondary hover:text-brew-plum"
                  >
                    <input
                      id="toggle-show-superseded"
                      type="checkbox"
                      checked={includeSuperseded}
                      onChange={(e) => onToggleIncludeSuperseded(e.target.checked)}
                      className="h-3.5 w-3.5 cursor-pointer rounded accent-brew-purple"
                    />
                    <span>Show earlier notes</span>
                  </label>
                </div>

                {contactMemories.length === 0 ? (
                  <div className="rounded-[22px] border border-brew-border bg-brew-bg p-5 text-sm text-brew-secondary">
                    <p>
                      No keepsakes stamped for{" "}
                      <strong className="text-brew-plum">{selectedContact.name}</strong> yet.
                      Capture a post-chat debrief to suggest takeaways for your approval.
                    </p>
                    <div className="mt-3">
                      <PillButton
                        id="btn-folio-log-debrief"
                        variant="outline"
                        size="sm"
                        onClick={() => onOpenDebrief(selectedContact.id)}
                      >
                        Capture Debrief
                      </PillButton>
                    </div>
                  </div>
                ) : (
                  <ul
                    aria-label={`Keepsakes for ${selectedContact.name}`}
                    className="grid gap-3.5 md:grid-cols-2"
                  >
                    {contactMemories.map((mem, idx) => (
                      <ApprovedKeepsakeCard
                        key={mem.id}
                        memory={mem}
                        index={idx}
                        onUpdate={handleUpdateMemoryWrapped}
                        onDelete={handleDeleteMemoryWrapped}
                      />
                    ))}
                  </ul>
                )}
              </div>

              {/* Conversations Timeline */}
              <div>
                <div className="brew-eyebrow mb-2.5">
                  CONVERSATIONS WITH{" "}
                  {(selectedContact.name.split(/\s+/)[0] ?? selectedContact.name).toUpperCase()}
                </div>

                {contactMeetings.length === 0 && !contactCalendarEvent ? (
                  <div className="rounded-[18px] border border-brew-border px-4 py-3.5 text-xs text-brew-secondary">
                    No conversations prepared yet. Click <strong>Prep Chat</strong> above to shape
                    your first cue deck.
                  </div>
                ) : (
                  <div className="flex flex-col gap-2.5">
                    {contactCalendarEvent && contactMeetings.length === 0 && (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-[16px] border border-brew-border px-4 py-3">
                        <div>
                          <span className="text-sm font-bold text-brew-plum">
                            {formatCalendarDayLabel(contactCalendarEvent.scheduledStartIso)},{" "}
                            {formatCalendarTimeRange(
                              contactCalendarEvent.scheduledStartIso,
                              contactCalendarEvent.scheduledEndIso,
                            )}{" "}
                            · {formatPurposeLabel(contactCalendarEvent.purpose)} (
                            {String(contactCalendarEvent.durationMinutes)}m)
                          </span>
                        </div>
                        <span className="brew-badge-peach">from GCal</span>
                      </div>
                    )}

                    {contactMeetings.map((mtg, idx) => {
                      const isLinkedGcal = idx === 0 && contactCalendarEvent !== null;
                      const briefId = mtg.latest_brief_id;
                      const isConfirmingBriefDelete =
                        briefId !== null && confirmDeleteBriefId === briefId;
                      return (
                        <div
                          key={mtg.id}
                          className="flex w-full flex-wrap items-center justify-between gap-2 rounded-[16px] border border-brew-border px-4 py-3 transition hover:bg-brew-blush/50"
                        >
                          <button
                            type="button"
                            onClick={() => {
                              if (briefId) {
                                onOpenCueStudioForContact(selectedContact.id, briefId);
                              } else {
                                onOpenSetupForContact(selectedContact.id);
                              }
                            }}
                            className="min-w-0 flex-1 cursor-pointer text-left"
                          >
                            <span className="text-sm font-bold text-brew-plum">
                              {formatShortTimestamp(mtg.scheduled_at ?? mtg.created_at)} ·{" "}
                              {formatPurposeLabel(mtg.purpose)} ({String(mtg.duration_minutes)}m)
                            </span>
                            <span className="ml-2 text-xs text-brew-secondary">
                              {briefId ? "Cue deck ready" : mtg.objective}
                            </span>
                          </button>

                          <div className="flex flex-wrap items-center gap-2">
                            {isLinkedGcal ? (
                              <span className="brew-badge-peach">from GCal</span>
                            ) : (
                              <span className="text-xs text-brew-secondary">
                                {formatShortTimestamp(mtg.updated_at)}
                              </span>
                            )}

                            {briefId && onDeleteBrief && (
                              isConfirmingBriefDelete ? (
                                <div className="flex items-center gap-1.5">
                                  <PillButton
                                    id={`btn-cancel-delete-folio-brief-${briefId}`}
                                    variant="outline"
                                    size="sm"
                                    disabled={deletingBrief}
                                    onClick={() => setConfirmDeleteBriefId(null)}
                                  >
                                    Cancel
                                  </PillButton>
                                  <PillButton
                                    id={`btn-confirm-delete-folio-brief-${briefId}`}
                                    variant="danger"
                                    size="sm"
                                    disabled={deletingBrief}
                                    onClick={() => {
                                      void handleDeleteBriefWrapped(briefId);
                                    }}
                                  >
                                    <Trash2 className="h-3 w-3" aria-hidden="true" />
                                    <span>{deletingBrief ? "Deleting..." : "Confirm Delete"}</span>
                                  </PillButton>
                                </div>
                              ) : (
                                <button
                                  id={`btn-delete-folio-brief-${briefId}`}
                                  type="button"
                                  aria-label={`Delete cue deck from ${formatShortTimestamp(mtg.scheduled_at ?? mtg.created_at)}`}
                                  onClick={() => setConfirmDeleteBriefId(briefId)}
                                  className="cursor-pointer text-xs font-semibold text-brew-secondary transition hover:text-[#9E3426]"
                                >
                                  Delete
                                </button>
                              )
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          ) : selectedFolio.kind === "all_memories" ? (
            <>
              {/* All Workspace Keepsakes View */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-brew-border pb-4">
                <div>
                  <div className="brew-eyebrow">ALL KEEPSAKES</div>
                  <h2 className="mt-0.5 font-serif text-[26px] font-bold text-brew-plum">
                    Workspace Memory Ledger
                  </h2>
                </div>

                <label
                  htmlFor="toggle-show-superseded-all"
                  className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-brew-secondary hover:text-brew-plum"
                >
                  <input
                    id="toggle-show-superseded-all"
                    type="checkbox"
                    checked={includeSuperseded}
                    onChange={(e) => onToggleIncludeSuperseded(e.target.checked)}
                    className="h-3.5 w-3.5 cursor-pointer rounded accent-brew-purple"
                  />
                  <span>Show earlier notes</span>
                </label>
              </div>

              <ul aria-label="All workspace keepsakes" className="grid gap-3.5 md:grid-cols-2">
                {memories.map((mem, idx) => (
                  <ApprovedKeepsakeCard
                    key={mem.id}
                    memory={mem}
                    index={idx}
                    counterpartName={
                      mem.contact_id ? (contactNameById.get(mem.contact_id) ?? null) : "My Style"
                    }
                    onUpdate={handleUpdateMemoryWrapped}
                    onDelete={handleDeleteMemoryWrapped}
                  />
                ))}
              </ul>
            </>
          ) : (
            <>
              {/* My Coaching Style & Account Folio */}
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-brew-border pb-5">
                <div className="flex items-center gap-3.5">
                  <ContactAvatar
                    name={userDisplayName}
                    tone="lavender"
                    size="lg"
                    singleInitial
                  />
                  <div>
                    <div className="brew-eyebrow">PERSONAL FOLIO &amp; ACCOUNT</div>
                    <h2 className="mt-0.5 font-serif text-[26px] font-bold text-brew-plum">
                      My Coaching Style ({userDisplayName})
                    </h2>
                    <p className="text-xs text-brew-secondary">
                      {isLocalMock ? "Local isolated workspace" : "Verified Google account"} ·{" "}
                      <span className="font-mono-code">{userId}</span>
                    </p>
                  </div>
                </div>

                <PillButton
                  id="btn-sign-out"
                  variant="outline"
                  size="sm"
                  onClick={onSignOut}
                >
                  <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Sign out</span>
                </PillButton>
              </div>

              {/* Display Name Customization Form */}
              {onUpdateDisplayName && (
                <form
                  onSubmit={(e) => {
                    void handleSaveDisplayName(e);
                  }}
                  className="space-y-4 rounded-[24px] border border-brew-border bg-brew-bg p-5"
                >
                  <div>
                    <h3 className="font-serif text-[19px] font-bold text-brew-plum">
                      Display Name
                    </h3>
                    <p className="text-xs text-brew-secondary">
                      {customDisplayName && accountDisplayName
                        ? `Custom name active across your Clubhouse and cue cards · Default ${isLocalMock ? "persona" : "Google"} name: ${accountDisplayName}`
                        : `Choose how your name appears across your Clubhouse and cue cards instead of your default ${isLocalMock ? "persona" : "Google account"} name.`}
                    </p>
                  </div>

                  <FormField
                    htmlFor="profile-display-name"
                    label="Preferred name in Brew"
                    error={displayNameError}
                  >
                    <input
                      id="profile-display-name"
                      type="text"
                      maxLength={120}
                      value={displayNameInput}
                      aria-invalid={displayNameError ? "true" : undefined}
                      onChange={(e) => {
                        setDisplayNameInput(e.target.value);
                        setDisplayNameError(null);
                        setSavedDisplayNameNotice(null);
                      }}
                      placeholder={accountDisplayName ?? "e.g., Karina"}
                      className="brew-field-control"
                    />
                  </FormField>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                    {savedDisplayNameNotice ? (
                      <span
                        role="status"
                        className="inline-flex items-center gap-1.5 text-xs font-bold text-[#215A45]"
                      >
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                        <span>{savedDisplayNameNotice}</span>
                      </span>
                    ) : (
                      <span />
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                      {customDisplayName !== null && (
                        <PillButton
                          id="btn-reset-display-name"
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={savingDisplayName}
                          onClick={() => {
                            void handleResetDisplayName();
                          }}
                        >
                          <span>
                            {isLocalMock ? "Use default name" : "Use Google name"}
                            {accountDisplayName ? ` (${accountDisplayName})` : ""}
                          </span>
                        </PillButton>
                      )}

                      <PrimaryButton
                        id="btn-save-display-name"
                        type="submit"
                        shape="pill"
                        disabled={savingDisplayName}
                        className="!min-h-[40px] !px-5 !py-2 !text-xs"
                      >
                        {savingDisplayName ? "Saving..." : "Save Name"}
                      </PrimaryButton>
                    </div>
                  </div>
                </form>
              )}

              {/* Default Coaching Style Form */}
              <form
                onSubmit={handleSaveDefaults}
                className="space-y-4 rounded-[24px] border border-brew-border bg-brew-bg p-5"
              >
                <div>
                  <h3 className="font-serif text-[19px] font-bold text-brew-plum">
                    Default Conversation Pacing &amp; Tone
                  </h3>
                  <p className="text-xs text-brew-secondary">
                    Pre-fills length, tone, and communication style notes on new cue decks.
                  </p>
                </div>

                <fieldset className="space-y-2">
                  <legend className="text-xs font-bold text-brew-plum">
                    Preferred chat length
                  </legend>
                  <SegmentedChoice
                    ariaLabel="Preferred chat length"
                    value={defaultDuration}
                    onChange={(val) => {
                      setDefaultDuration(val);
                      setSavedDefaultsNotice(false);
                    }}
                    options={DURATION_PRESETS.map((mins) => ({
                      value: String(mins),
                      label: `${String(mins)}m`,
                    }))}
                  />
                </fieldset>

                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField htmlFor="profile-default-tone" label="Default conversation tone">
                    <select
                      id="profile-default-tone"
                      value={defaultTone}
                      onChange={(e) => {
                        setDefaultTone(e.target.value as MeetingTone);
                        setSavedDefaultsNotice(false);
                      }}
                      className="brew-field-control"
                    >
                      {MEETING_TONE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </FormField>

                  <FormField
                    htmlFor="profile-style-notes"
                    label="Personal communication style note"
                  >
                    <input
                      id="profile-style-notes"
                      type="text"
                      maxLength={500}
                      value={defaultStyleNotes}
                      onChange={(e) => {
                        setDefaultStyleNotes(e.target.value);
                        setSavedDefaultsNotice(false);
                      }}
                      placeholder="e.g., Prefer concise, story-first engineering questions."
                      className="brew-field-control"
                    />
                  </FormField>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  {savedDefaultsNotice ? (
                    <span
                      role="status"
                      className="inline-flex items-center gap-1.5 text-xs font-bold text-[#215A45]"
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      <span>Defaults saved for future chats</span>
                    </span>
                  ) : (
                    <span />
                  )}

                  <PrimaryButton
                    id="btn-save-coaching-defaults"
                    type="submit"
                    shape="pill"
                    className="!min-h-[40px] !px-5 !py-2 !text-xs"
                  >
                    Save Defaults
                  </PrimaryButton>
                </div>
              </form>

              {/* Personal Preference Keepsakes */}
              <div>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="brew-eyebrow">
                    PERSONAL PREFERENCE KEEPSAKES ({String(activePersonalCount)})
                  </div>

                  <label
                    htmlFor="toggle-show-superseded-personal"
                    className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-brew-secondary hover:text-brew-plum"
                  >
                    <input
                      id="toggle-show-superseded-personal"
                      type="checkbox"
                      checked={includeSuperseded}
                      onChange={(e) => onToggleIncludeSuperseded(e.target.checked)}
                      className="h-3.5 w-3.5 cursor-pointer rounded accent-brew-purple"
                    />
                    <span>Show earlier notes</span>
                  </label>
                </div>

                {personalMemories.length === 0 ? (
                  <div className="rounded-[20px] border border-brew-border bg-brew-mint-pale/60 p-4 text-xs text-brew-secondary">
                    No personal coaching preferences saved yet. Mention how you like to converse in
                    a post-chat debrief to save preferences here.
                  </div>
                ) : (
                  <ul
                    aria-label="Personal preference keepsakes"
                    className="grid gap-3.5 md:grid-cols-2"
                  >
                    {personalMemories.map((mem, idx) => (
                      <ApprovedKeepsakeCard
                        key={mem.id}
                        memory={mem}
                        index={idx}
                        onUpdate={handleUpdateMemoryWrapped}
                        onDelete={handleDeleteMemoryWrapped}
                      />
                    ))}
                  </ul>
                )}
              </div>

              {/* Read-Only Calendar & Workspace Connection */}
              <div className="grid gap-4 border-t border-brew-border pt-4 sm:grid-cols-2">
                <div className="space-y-2 rounded-[20px] border border-brew-border p-4">
                  <div className="brew-eyebrow">CALENDAR CONNECTION</div>
                  <p className="text-xs text-brew-secondary">
                    {String(calendarEvents.length)} coffee chat{" "}
                    {calendarEvents.length === 1 ? "slot" : "slots"} loaded (read-only).
                  </p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    {googleCalendarAvailable && (
                      <PillButton
                        id="btn-journal-sync-gcal"
                        variant="peach"
                        size="sm"
                        disabled={calendarSyncing}
                        onClick={() => {
                          void onConnectGoogleCalendar();
                        }}
                      >
                        <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>{calendarSyncing ? "Syncing..." : "Sync GCal"}</span>
                      </PillButton>
                    )}

                    <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-brew-border bg-brew-paper px-3 py-1.5 text-xs font-semibold text-brew-plum hover:bg-brew-blush">
                      <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>Import .ics</span>
                      <input
                        id="journal-ics-upload"
                        type="file"
                        accept=".ics,text/calendar"
                        onChange={handleIcsUpload}
                        className="sr-only"
                      />
                    </label>

                    {calendarEvents.length > 0 && (
                      <button
                        id="btn-clear-calendar-events"
                        type="button"
                        onClick={onClearCalendarEvents}
                        className="cursor-pointer text-xs font-semibold text-brew-secondary hover:text-[#9E3426]"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between gap-2 rounded-[20px] border border-brew-border p-4">
                  <div>
                    <div className="brew-eyebrow">WORKSPACE</div>
                    <div className="mt-0.5 text-xs font-bold text-brew-plum">
                      {health.kind === "ready"
                        ? `${health.data.service} v${health.data.version} · ${health.data.model}`
                        : health.kind === "error"
                          ? "Backend unreachable"
                          : "Checking..."}
                    </div>
                  </div>
                  <PillButton
                    id="btn-refresh-workspace-health"
                    variant="ghost"
                    size="sm"
                    disabled={health.kind === "loading"}
                    onClick={onRefreshHealth}
                    aria-label="Refresh workspace connection"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  </PillButton>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
