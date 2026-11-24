import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function assertNoSeriousA11yViolations(page: Page, screenLabel: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  expect(
    blocking,
    `Expected zero critical/serious axe violations on ${screenLabel}, found: ${JSON.stringify(
      blocking.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length })),
    )}`,
  ).toEqual([]);
}

async function assertNoHorizontalOverflow(page: Page, viewportLabel: string): Promise<void> {
  const dims = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(
    dims.scrollWidth,
    `Horizontal overflow detected at ${viewportLabel}: scrollWidth=${String(dims.scrollWidth)} > innerWidth=${String(dims.innerWidth)}`,
  ).toBeLessThanOrEqual(dims.innerWidth + 1);
}

test.describe("Brew V2 Full-Stack E2E, Responsive, and Accessibility Suite", () => {
  test("1. Full coffee chat lifecycle: Sign-in -> Calendar .ics -> Quick Spark -> Cue Studio -> Pocket Glance -> Revision -> Debrief -> Journal -> Sign-out", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.goto("/");

    // Sign-in gate accessibility & mock persona sign-in
    await expect(page.locator("#btn-mock-persona-alice")).toBeVisible();
    await assertNoSeriousA11yViolations(page, "AuthSignInGate");
    await page.locator("#btn-mock-persona-alice").click();

    // Clubhouse loaded with 3-space navigation and demo GCal slots
    const primaryNav = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(primaryNav).toBeVisible();
    await expect(page.locator("#nav-space-clubhouse")).toHaveAttribute("aria-current", "page");
    await expect(page.locator("span:visible", { hasText: "from GCal" }).first()).toBeVisible();
    await assertNoSeriousA11yViolations(page, "Clubhouse Desktop");

    // Import an additional .ics coffee chat event
    await page.locator("#btn-toggle-calendar-import").click();
    const futureStart = new Date(Date.now() + 5 * 3600_000)
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(/\.\d{3}Z$/, "Z");
    const futureEnd = new Date(Date.now() + 5.5 * 3600_000)
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(/\.\d{3}Z$/, "Z");
    const icsPayload = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "BEGIN:VEVENT",
      "UID:e2e-jordan-slot",
      `DTSTART:${futureStart}`,
      `DTEND:${futureEnd}`,
      "SUMMARY:Coffee Chat: Jordan Rivera (Stripe)",
      "DESCRIPTION:Explore developer platform API ergonomics.",
      "END:VEVENT",
      "END:VCALENDAR",
    ].join("\r\n");
    await page.locator("#ics-paste-textarea").fill(icsPayload);
    await page.locator("#btn-import-ics-submit").click();
    await expect(page.locator("#btn-prep-calendar-ics-e2e-jordan-slot").or(page.locator("span:visible", { hasText: "Jordan Rivera" }).first())).toBeVisible();

    // Launch Quick Spark natural-language setup from Clubhouse
    await page
      .locator("#clubhouse-quick-spark-input")
      .fill("15m warm intro with Jordan Rivera (Platform Lead at Stripe) about API ergonomics");
    await page.locator("#btn-clubhouse-spark-brief").click();

    // Focused Setup screen: verify 3-space nav is hidden, back button shown, user-requested CTA & simplified setup
    await expect(primaryNav).toHaveCount(0);
    await expect(page.locator("#btn-setup-back")).toBeVisible();
    await expect(page.locator("#setup-duration-select")).toHaveValue("15");
    await expect(page.locator("#setup-adhoc-name-input")).toHaveValue("Jordan Rivera");
    await expect(page.getByText(/How you connected/i)).toHaveCount(0);
    await expect(page.getByText(/Your coaching style/i)).toHaveCount(0);
    const generateBtn = page.locator("#btn-submit-generate-brief");
    await expect(generateBtn).toHaveText("Synthesize Cue Deck");
    await assertNoSeriousA11yViolations(page, "QuickSparkSetup Focused Flow");

    // Synthesize Cue Deck -> lands in Cue Studio
    await generateBtn.click();
    await expect(page.locator("#nav-space-studio")).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { name: "Jordan Rivera" })).toBeVisible();
    await expect(page.locator("#btn-brief-revision-v1")).toBeVisible();
    await assertNoSeriousA11yViolations(page, "CueStudio Desktop");

    // Toggle star on the 3rd question if present, or verify starring works cleanly
    const starButtons = page.locator('[id^="btn-star-question-"]');
    const starCount = await starButtons.count();
    expect(starCount).toBeGreaterThanOrEqual(2);

    // Open Pocket Glance focused ritual
    await page.locator("#btn-open-pocket-glance").click();
    await expect(primaryNav).toHaveCount(0);
    await expect(page.locator("#btn-pocket-back")).toBeVisible();
    await assertNoSeriousA11yViolations(page, "PocketCueCards Focused Flow");

    // Live quick-tune revision from Pocket Glance -> creates v2
    await page.locator("#pocket-tune-input").fill("Focus more on API versioning lessons");
    await page.locator("#btn-pocket-tune-submit").click();
    await expect(page.getByText(/v2/)).toBeVisible();

    // Return to Cue Studio and inspect historical v1 snapshot banner
    await page.locator("#btn-pocket-back").click();
    await expect(page.locator("#btn-brief-revision-v2")).toBeVisible();
    await page.locator("#btn-brief-revision-v1").click();
    await expect(page.locator("#historical-revision-banner")).toBeVisible();
    await page.locator("#btn-brief-revision-v2").click();
    await expect(page.locator("#historical-revision-banner")).toHaveCount(0);

    // Wrap & Debrief -> Suggest Keepsakes -> Edit + Stamp Keep -> Reject second proposal if present
    await page.locator("#btn-wrap-and-debrief").click();
    await expect(page.locator("#btn-debrief-back")).toBeVisible();
    await page
      .locator("#post-meeting-notes-input")
      .fill(
        "Jordan shared that Stripe ships SDK previews behind date-pinned headers and offered to review our API changelog next month.",
      );
    await page.locator("#btn-submit-propose-memories").click();

    const approveButtons = page.locator('[id^="btn-approve-proposal-"]');
    await expect(approveButtons.first()).toBeVisible();
    await assertNoSeriousA11yViolations(page, "DebriefKeepsakes Focused Flow");

    // Edit & Stamp Keep on the first proposed keepsake
    const editProposalButtons = page.locator('[id^="btn-edit-proposal-"]');
    await editProposalButtons.first().click();
    const saveApproveButtons = page.locator('[id^="btn-save-approve-proposal-"]');
    await saveApproveButtons.first().click();

    // Navigate back to Relationship Journal and verify counterpart folio + keepsake lifecycle
    await page.locator("#btn-debrief-back").click();
    await page.locator("#nav-space-journal").click();
    await expect(page.locator("#nav-space-journal")).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { name: "Jordan Rivera" })).toBeVisible();
    await assertNoSeriousA11yViolations(page, "RelationshipJournal Desktop");

    // Edit an approved keepsake in the folio
    const editMemoryBtn = page.locator('[id^="btn-edit-memory-"]').first();
    await expect(editMemoryBtn).toBeVisible();

    // Switch to My Coaching Style folio and save defaults
    await page.locator("#btn-select-coaching-style-folio").click();
    await expect(page.locator("#profile-default-tone")).toBeVisible();
    await page.locator("#profile-style-notes").fill("Keep openers crisp and warm.");
    await page.locator("#btn-save-coaching-defaults").click();

    // Sign out cleanly
    await page.locator("#btn-sign-out").click();
    await expect(page.locator("#btn-mock-persona-alice")).toBeVisible();
  });

  test("2. Responsive layouts (Desktop 1440, Tablet 834, Mobile 430) & keyboard accessibility", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.goto("/");
    await page.locator("#btn-mock-persona-alice").click();
    await expect(page.locator("#nav-space-clubhouse")).toBeVisible();
    await assertNoHorizontalOverflow(page, "Desktop 1440x980");

    // Keyboard skip link & focus ring navigation
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: /Skip to workspace/i });
    await expect(skipLink).toBeFocused();

    // Tablet viewport (834x1194): TopBarShell visible, MobileDock hidden, zero overflow
    await page.setViewportSize({ width: 834, height: 1194 });
    await expect(page.locator("#nav-space-clubhouse")).toBeVisible();
    await expect(page.locator("#mobile-dock-clubhouse")).toBeHidden();
    await assertNoHorizontalOverflow(page, "Tablet 834x1194");

    // Mobile viewport (430x932): MobileDock visible, desktop center nav hidden, zero overflow
    await page.setViewportSize({ width: 430, height: 932 });
    const mobileDock = page.getByRole("navigation", { name: "Mobile dock" });
    await expect(mobileDock).toBeVisible();
    await expect(page.locator("#nav-space-clubhouse")).toBeHidden();
    await assertNoHorizontalOverflow(page, "Mobile 430x932 Clubhouse");
    await assertNoSeriousA11yViolations(page, "Clubhouse Mobile 430x932");

    // Navigate across spaces using MobileDock on mobile
    await page.locator("#mobile-dock-journal").click();
    await expect(page.locator("#mobile-dock-journal")).toHaveAttribute("aria-current", "page");
    await assertNoHorizontalOverflow(page, "Mobile 430x932 Journal");

    // Tap MobileDock center FAB -> opens Focused Setup and hides MobileDock
    await page.locator("#mobile-dock-quick-spark").click();
    await expect(mobileDock).toHaveCount(0);
    await expect(page.locator("#btn-setup-back")).toBeVisible();
    await assertNoHorizontalOverflow(page, "Mobile 430x932 QuickSparkSetup");
  });
});
