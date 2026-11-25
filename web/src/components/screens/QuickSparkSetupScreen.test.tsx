import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ContactResponse } from "../../api/types";
import type { CalendarCoffeeChatEvent } from "../../calendar/calendarTypes";
import { DEFAULT_STYLE_DEFAULTS } from "../../state/coachingDefaultsStore";
import {
  QuickSparkSetupScreen,
  type QuickSparkSetupInitialSeed,
} from "./QuickSparkSetupScreen";

const OBJECTIVE_INPUT_ID = "setup-objective-input";
const DURATION_SELECT_ID = "setup-duration-select";
const SAVED_CONTACT_SELECT_ID = "setup-saved-contact-select";

function buildContact(id: string, name: string): ContactResponse {
  return {
    id,
    name,
    title: null,
    role: null,
    organization: null,
    context_notes: null,
    version: 1,
    created_at: "2026-11-20T09:00:00Z",
    updated_at: "2026-11-20T09:00:00Z",
  };
}

const UPCOMING_EVENT: CalendarCoffeeChatEvent = {
  id: "evt_priya_45",
  title: "Coffee chat with Priya Shah",
  counterpartName: "Priya Shah",
  counterpartTitle: null,
  counterpartOrganization: null,
  counterpartRole: null,
  purpose: "mentorship",
  scheduledStartIso: "2099-01-05T17:00:00Z",
  scheduledEndIso: "2099-01-05T17:45:00Z",
  durationMinutes: 45,
  notesExcerpt: null,
  source: "gcal",
  temporalStatus: "upcoming",
};

function renderSetup(
  initialSeed: QuickSparkSetupInitialSeed,
  contacts: readonly ContactResponse[] = [],
  calendarEvents: readonly CalendarCoffeeChatEvent[] = [],
): void {
  render(
    <QuickSparkSetupScreen
      contacts={contacts}
      calendarEvents={calendarEvents}
      styleDefaults={DEFAULT_STYLE_DEFAULTS}
      initialSeed={initialSeed}
      onCreateContact={vi.fn()}
      onGenerateBrief={vi.fn()}
      onOpenNewContactModal={vi.fn()}
    />,
  );
}

function fieldValue(id: string): string {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLTextAreaElement) && !(element instanceof HTMLSelectElement)) {
    throw new Error(`Expected a textarea or select with id "${id}".`);
  }
  return element.value;
}

function changeField(id: string, value: string): void {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`Expected an element with id "${id}".`);
  }
  fireEvent.change(element, { target: { value } });
}

describe("QuickSparkSetupScreen seed handling", () => {
  it("keeps the user's objective edits after a Quick Spark sentence pre-filled it", () => {
    renderSetup({
      sparkText: "20m casual coffee chat with Jordan Kim at Figma about design token governance",
    });
    expect(fieldValue(OBJECTIVE_INPUT_ID)).not.toBe("");

    changeField(OBJECTIVE_INPUT_ID, "Ask how Figma reviews token changes before release.");

    expect(fieldValue(OBJECTIVE_INPUT_ID)).toBe(
      "Ask how Figma reviews token changes before release.",
    );
  });

  it("keeps a changed duration when the objective is typed after a calendar seed", () => {
    renderSetup({ calendarEvent: UPCOMING_EVENT }, [], [UPCOMING_EVENT]);
    expect(fieldValue(DURATION_SELECT_ID)).toBe("45");

    changeField(DURATION_SELECT_ID, "20");
    changeField(OBJECTIVE_INPUT_ID, "Get one candid piece of career advice.");

    expect(fieldValue(DURATION_SELECT_ID)).toBe("20");
    expect(fieldValue(OBJECTIVE_INPUT_ID)).toBe("Get one candid piece of career advice.");
  });

  it("keeps a re-selected person when the objective is typed after a contact seed", () => {
    const maya = buildContact("cnt_maya", "Maya Lin");
    const jordan = buildContact("cnt_jordan", "Jordan Kim");
    renderSetup({ contactId: maya.id }, [maya, jordan]);
    expect(fieldValue(SAVED_CONTACT_SELECT_ID)).toBe(maya.id);

    changeField(SAVED_CONTACT_SELECT_ID, jordan.id);
    changeField(OBJECTIVE_INPUT_ID, "Compare notes on design system rollout.");

    expect(fieldValue(SAVED_CONTACT_SELECT_ID)).toBe(jordan.id);
  });
});
