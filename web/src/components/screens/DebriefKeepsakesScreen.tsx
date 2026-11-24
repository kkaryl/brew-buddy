import { Calendar, Compass, Sparkles } from "lucide-react";
import { useState, type FormEvent, type JSX } from "react";
import type {
  ApproveMemoryProposalRequest,
  ContactResponse,
  CreateContactRequest,
  MeetingResponse,
  MemoryProposalBatchResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
  ProposeMemoriesRequest,
  RejectMemoryProposalRequest,
} from "../../api/types";
import {
  formatCalendarDayLabel,
  matchCalendarEventContact,
} from "../../calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import { KeepsakeProposalCard } from "../domain/KeepsakeCard";
import { errorToFeedbackNotice, type FeedbackNotice } from "../formatters";
import { StatusBanner } from "../StatusFeedback";
import {
  ContactAvatar,
  EmptyState,
  FormField,
  Illustration,
  PillButton,
  PrimaryButton,
} from "../ui";

const GUIDED_REFLECTION_PROMPTS: readonly {
  readonly label: string;
  readonly snippet: string;
  readonly icon: "sparkles" | "calendar" | "compass";
}[] = [
  {
    label: "What lit them up?",
    snippet: "What energized them most: ",
    icon: "sparkles",
  },
  {
    label: "Follow-ups promised?",
    snippet: "Follow-ups we promised: ",
    icon: "calendar",
  },
  {
    label: "Pace & tone notes?",
    snippet: "My personal conversation style preference: ",
    icon: "compass",
  },
];

export interface DebriefKeepsakesScreenProps {
  readonly contacts: readonly ContactResponse[];
  readonly activeContact: ContactResponse | null;
  readonly activeMeeting: MeetingResponse | null;
  readonly activeBrief: PreparationBriefResponse | null;
  readonly targetCalendarEvent: CalendarCoffeeChatEvent | null;
  readonly pendingProposals: readonly MemoryProposalResponse[];
  readonly memories: readonly MemoryResponse[];
  readonly onSelectContact: (contactId: string) => Promise<void>;
  readonly onCreateContact: (payload: CreateContactRequest) => Promise<ContactResponse>;
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

export function DebriefKeepsakesScreen({
  contacts,
  activeContact,
  activeMeeting,
  activeBrief,
  targetCalendarEvent,
  pendingProposals,
  memories,
  onSelectContact,
  onCreateContact,
  onProposeMemories,
  onApproveProposal,
  onRejectProposal,
}: DebriefKeepsakesScreenProps): JSX.Element {
  const [notes, setNotes] = useState("");
  const [notesError, setNotesError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackNotice | null>(null);

  const contactById = new Map<string, ContactResponse>(contacts.map((c) => [c.id, c]));
  const memoryTextById = new Map<string, string>(memories.map((m) => [m.id, m.text]));

  const matchedCalendarContact = targetCalendarEvent
    ? matchCalendarEventContact(targetCalendarEvent, contacts)
    : null;

  const subjectContact = matchedCalendarContact ?? activeContact ?? contacts[0] ?? null;
  const subjectName =
    subjectContact?.name ?? targetCalendarEvent?.counterpartName ?? "your chat";
  const subjectFirstName = subjectName.trim().split(/\s+/)[0] || subjectName;

  const isFromGCal = Boolean(targetCalendarEvent);

  const appendPromptSnippet = (snippet: string): void => {
    setNotes((prev) => {
      if (!prev.trim()) {
        return snippet;
      }
      return `${prev.trimEnd()}\n\n${snippet}`;
    });
  };

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
      let resolvedContactId = subjectContact?.id ?? null;
      if (!resolvedContactId && targetCalendarEvent) {
        const created = await onCreateContact({
          name: targetCalendarEvent.counterpartName,
          organization: targetCalendarEvent.counterpartOrganization,
          role: targetCalendarEvent.counterpartRole,
          title: targetCalendarEvent.counterpartTitle,
          context_notes: null,
        });
        resolvedContactId = created.id;
      }

      const batch = await onProposeMemories({
        notes: trimmed,
        source_type: "meeting_notes",
        contact_id: resolvedContactId,
        meeting_id:
          activeMeeting && activeMeeting.contact_id === resolvedContactId
            ? activeMeeting.id
            : null,
        brief_id:
          activeBrief && activeBrief.contact_id === resolvedContactId
            ? activeBrief.id
            : null,
      });

      const filterNotes: string[] = [];
      if (batch.skipped_duplicates > 0) {
        filterNotes.push(`${String(batch.skipped_duplicates)} duplicate skipped`);
      }
      if (batch.filtered_sensitive_count > 0) {
        filterNotes.push(`${String(batch.filtered_sensitive_count)} sensitive item excluded`);
      }
      const suffix = filterNotes.length > 0 ? ` (${filterNotes.join(", ")})` : "";

      setFeedback({
        kind: batch.total > 0 ? "success" : "info",
        title:
          batch.total > 0
            ? `${String(batch.total)} suggested ${batch.total === 1 ? "keepsake" : "keepsakes"} staged`
            : "No new keepsake suggestions found",
        message: `Only cards you stamp Keep are saved to your journal${suffix}.`,
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not suggest keepsakes"));
    } finally {
      setExtracting(false);
    }
  };

  const handleStampApprove = async (
    proposalId: string,
    payload: ApproveMemoryProposalRequest,
  ): Promise<void> => {
    setFeedback(null);
    try {
      const approved = await onApproveProposal(proposalId, payload);
      setFeedback({
        kind: "success",
        title: "Keepsake stamped to journal",
        message: approved.supersedes_memory_id
          ? "Saved to your journal and archived the earlier note."
          : "Saved to your journal for future coffee chats.",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not stamp keepsake"));
    }
  };

  const handleTossReject = async (
    proposalId: string,
    payload: RejectMemoryProposalRequest,
  ): Promise<void> => {
    setFeedback(null);
    try {
      await onRejectProposal(proposalId, payload);
      setFeedback({
        kind: "info",
        title: "Keepsake tossed",
        message: "Excluded from your journal and future brief recall.",
      });
    } catch (err: unknown) {
      setFeedback(errorToFeedbackNotice(err, "Could not toss keepsake"));
    }
  };

  return (
    <div className="mx-auto max-w-[1300px] space-y-5">
      {feedback && (
        <StatusBanner notice={feedback} onDismiss={() => setFeedback(null)} />
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,95fr)_minmax(0,105fr)] lg:gap-7">
        {/* Left Reflection Pad (Responsive Mobile Peach Card + Desktop White Card) */}
        <section
          aria-labelledby="debrief-reflection-heading"
          className="brew-hero-peach min-w-0 rounded-[26px] p-4 md:rounded-[30px] md:border md:border-brew-border md:bg-none md:bg-brew-paper md:p-7"
        >
          <form
            onSubmit={(e) => void handleExtractSubmit(e)}
            noValidate
            className="flex flex-col gap-3.5 md:gap-4"
          >
            {/* Header Row */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <ContactAvatar
                  name={subjectName}
                  tone="peach"
                  size="md"
                  className="md:h-11 md:w-11"
                />
                <div className="min-w-0">
                  <div className="hidden flex-wrap items-center gap-2 md:flex">
                    <span className="brew-eyebrow">
                      {targetCalendarEvent
                        ? `WRAPPED ${formatCalendarDayLabel(targetCalendarEvent.scheduledEndIso).toUpperCase()} · ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(targetCalendarEvent.scheduledEndIso))}`
                        : "POST-CHAT REFLECTION"}
                    </span>
                    {isFromGCal && (
                      <span className="brew-badge-peach !px-2 !py-0.5 !text-[10.5px]">
                        from GCal
                      </span>
                    )}
                  </div>

                  <h1
                    id="debrief-reflection-heading"
                    className="truncate font-serif text-[20px] font-bold text-brew-plum md:mt-0.5 md:text-[25px]"
                  >
                    <span className="md:hidden">{subjectName}</span>
                    <span className="hidden md:inline">
                      How did it go with {subjectFirstName}?
                    </span>
                  </h1>

                  <div className="text-[11.5px] text-brew-secondary md:hidden">
                    {targetCalendarEvent
                      ? `${formatCalendarDayLabel(targetCalendarEvent.scheduledEndIso)} · ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(targetCalendarEvent.scheduledEndIso))}${isFromGCal ? " · from GCal" : ""}`
                      : "Post-chat reflection"}
                  </div>
                </div>
              </div>

              {/* Mobile Compact Illustration (matches Mockup 08) */}
              <Illustration
                name="debrief-keepsake-journal"
                decorative
                className="h-[74px] w-[112px] shrink-0 md:hidden"
              />

              {/* Counterpart Switcher on Desktop when multiple contacts exist */}
              {contacts.length > 1 && !targetCalendarEvent && (
                <select
                  id="debrief-contact-select"
                  aria-label="Select counterpart for debrief"
                  value={subjectContact?.id ?? ""}
                  onChange={(e) => {
                    if (e.target.value) {
                      void onSelectContact(e.target.value);
                    }
                  }}
                  className="hidden rounded-full border border-brew-border bg-brew-paper px-3 py-1.5 text-xs font-semibold text-brew-plum md:inline-block"
                >
                  {contacts.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Desktop Illustrated Peach Banner (matches Mockup 04) */}
            <div className="brew-hero-peach hidden justify-center rounded-[22px] px-4 py-2.5 shadow-none md:flex">
              <Illustration
                name="debrief-keepsake-journal"
                className="h-[138px] w-full"
              />
            </div>

            {/* Guided Prompt Chips */}
            <div className="hidden flex-wrap gap-1.5 md:flex">
              {GUIDED_REFLECTION_PROMPTS.map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={() => appendPromptSnippet(chip.snippet)}
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-full bg-brew-blush px-3 py-1.5 text-[11.5px] font-semibold text-brew-plum transition hover:bg-brew-peach"
                >
                  {chip.icon === "sparkles" && (
                    <Sparkles className="h-3 w-3 text-brew-coral-vibrant" aria-hidden="true" />
                  )}
                  {chip.icon === "calendar" && (
                    <Calendar className="h-3 w-3 text-brew-purple" aria-hidden="true" />
                  )}
                  {chip.icon === "compass" && (
                    <Compass className="h-3 w-3 text-brew-mint-deep" aria-hidden="true" />
                  )}
                  <span>{chip.label}</span>
                </button>
              ))}
            </div>

            {/* Notes Input */}
            <FormField
              htmlFor="post-meeting-notes-input"
              label="Session reflections"
              hideLabel
              error={notesError}
              errorId="post-meeting-notes-error"
            >
              <textarea
                id="post-meeting-notes-input"
                rows={3}
                required
                maxLength={10000}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                aria-invalid={notesError ? "true" : "false"}
                aria-describedby={notesError ? "post-meeting-notes-error" : undefined}
                placeholder="Great energy! Jot what lit them up, follow-ups promised, or how you like to pace future conversations..."
                className="brew-field-control min-h-[72px] rounded-[18px] bg-white/90 text-[13px] leading-[1.5] md:min-h-[166px] md:rounded-[22px] md:bg-brew-bg md:text-[14px] md:leading-[1.6]"
              />
            </FormField>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="hidden text-xs text-brew-secondary sm:inline">
                Write freely. You choose what belongs in your journal.
              </span>

              {pendingProposals.length > 0 ? (
                <PillButton
                  id="btn-submit-propose-memories"
                  type="submit"
                  variant="outline"
                  disabled={extracting}
                >
                  <span>{extracting ? "Suggesting..." : "Refresh Suggestions"}</span>
                  <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                </PillButton>
              ) : (
                <PrimaryButton
                  id="btn-submit-propose-memories"
                  type="submit"
                  shape="pill"
                  loading={extracting}
                  className="!min-h-[40px] !px-5 !py-2 !text-xs"
                >
                  <span>{extracting ? "Suggesting Keepsakes..." : "Suggest Keepsakes"}</span>
                  {!extracting && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
                </PrimaryButton>
              )}
            </div>
          </form>
        </section>

        {/* Right Suggested Keepsakes Column */}
        <section aria-labelledby="keepsakes-stamp-heading" className="flex min-w-0 flex-col gap-3.5">
          <div className="hidden px-1 md:block">
            <div className="brew-eyebrow !text-[#6E4AA3]">
              {String(pendingProposals.length)} SUGGESTED{" "}
              {pendingProposals.length === 1 ? "KEEPSAKE" : "KEEPSAKES"}
            </div>
            <h2
              id="keepsakes-stamp-heading"
              className="mt-0.5 font-serif text-[24px] font-bold text-brew-plum"
            >
              Stamp what belongs in memory
            </h2>
            <p className="mt-0.5 text-[13px] text-brew-secondary">
              Only cards you stamp Keep are saved to your journal.
            </p>
          </div>

          {pendingProposals.length === 0 ? (
            <EmptyState
              title="No keepsakes awaiting your stamp"
              description="Share a few post-chat reflections and Brew will stage counterpart takeaways and personal preferences here for your review."
              illustration="debrief-keepsake-journal"
            />
          ) : (
            <ul aria-label="Suggested keepsakes" className="flex flex-col gap-3.5">
              {pendingProposals.map((proposal, idx) => {
                const cName = proposal.contact_id
                  ? (contactById.get(proposal.contact_id)?.name ?? targetCalendarEvent?.counterpartName ?? null)
                  : null;
                const supersededText = proposal.supersedes_memory_id
                  ? (memoryTextById.get(proposal.supersedes_memory_id) ?? null)
                  : null;
                return (
                  <KeepsakeProposalCard
                    key={proposal.id}
                    proposal={proposal}
                    counterpartName={cName}
                    supersededMemoryText={supersededText}
                    indexLabel={
                      pendingProposals.length > 1
                        ? `${String(idx + 1)} of ${String(pendingProposals.length)}`
                        : undefined
                    }
                    onApprove={handleStampApprove}
                    onReject={handleTossReject}
                  />
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
