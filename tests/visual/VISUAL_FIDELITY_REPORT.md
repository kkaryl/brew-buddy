# Brew V2 Visual Fidelity Validation Report

Generated and verified via Playwright + Google Chrome (`web/e2e/visual-fidelity.spec.ts`) against the approved v2 mockups in `mockups/v2/`.

## Artifacts Under `tests/visual/`

- **Overview Board**: `tests/visual/00-side-by-side-overview.png`
- **Automated Similarity Metrics**: `tests/visual/metrics.json`
- **Live Browser Captures**: `tests/visual/actual/01..08-*.png`
- **Side-by-Side Comparison Boards**: `tests/visual/comparisons/01..08-*-side-by-side.png`

## Screen-by-Screen Comparison Summary

| Screen | Viewport | Pixel Similarity | Status & Notes |
| :--- | :---: | :---: | :--- |
| `01-desktop-clubhouse-calendar` | `1440x980` | **95.14%** | Matches 3-space `TopBarShell`, Peach Up-Next Hero (`chat-setup-hero.png`), proportional mini-ribbon, Wrapped lavender row, `from GCal` upcoming rows, Quick Spark card, Keepsakes to Stamp card, and Warm Reconnect card. |
| `02-desktop-quick-spark-setup` | `1440x960` | **96.43%** | Matches focused `← Back to Clubhouse` header, selected GCal slot highlight, single-line pastel Mad-Libs sentence controls, right-hand Pacing Blueprint (`chat-setup-hero.png`), and explicit user-approved overrides (`Synthesize Cue Deck` CTA; omitted `How you connected` and `Your coaching style` boxes). |
| `03-desktop-cue-card-studio` | `1440x980` | **93.73%** | Matches counterpart header, immutable `v1`/`v2` switcher, `Pocket Glance` + `Wrap & Debrief` actions, proportional Run-of-Show ribbon, 2-column Icebreaker cards, 2x2 star-able Cue Cards (`Starred` coral frame), and sticky lavender `Tune on the fly` Brief Co-Pilot (`cue-studio-copilot.png`). |
| `04-desktop-debrief-keepsakes` | `1440x960` | **94.01%** | Matches focused header, white paper reflection pad with inner peach `debrief-keepsake-journal.png` banner, guided reflection chips, and color-coded Suggested Keepsake cards (`Stamp Keep`, `Edit`, `Toss`, plus yellow supersession banner). |
| `05-desktop-journal-people-dna` | `1440x980` | **96.09%** | Matches 2-column Relationship Atlas (`37% / 63%`), `My Coaching Style` mint card, counterpart list with pending/keepsake badges, bounded `relationship-folio-circle.png` companion card, right-aligned `Open Brief` CTA, 2-column keepsake cards, and conversation timeline. |
| `06-mobile-clubhouse-calendar` | `430x932` | **87.67%** | Matches mobile wordmark + avatar, stacked Up-Next hero (`Open Pocket Cue Cards`), Wrapped lavender strip, clean `THIS WEEK` `from GCal` rows, Mint Keepsakes strip, and floating `MobileDock` + Coral `+` FAB with zero horizontal overflow. |
| `07-mobile-pocket-cue-cards` | `430x932` | **91.96%** | Matches focused `← Full Studio` / `POCKET CUE CARDS` / `Debrief` bar, compact proportional time ribbon, Warm Icebreaker, starred Q1 & Q2 cards, `Show all 4 questions` progressive disclosure, Mint Close card, and fixed bottom Quick-Tune bar. |
| `08-mobile-debrief-keepsakes` | `430x932` | **89.51%** | Matches focused `← Done` / `DEBRIEF` header, compact peach reflection card with `debrief-keepsake-journal.png` thumbnail, and mobile Keepsake proposal cards with zero horizontal clipping. |

## Iterative Visual Refinements Applied

1. **Tailwind v4 `@layer components` Cascade**: Wrapped custom `.brew-*` surface, typography, and badge classes in `@layer components` (`web/src/index.css`) so responsive Tailwind utilities (`hidden`, `md:inline-flex`, `md:bg-none`, `md:bg-brew-paper`) override component defaults cleanly without specificity leaks on mobile `06` and desktop `04`.
2. **Grid Track Proportions & Mobile Overflow Prevention**: Converted fractional grid templates to integer `minmax(0, ...fr)` tracks with `min-w-0` children across `ClubhouseScreen`, `QuickSparkSetupScreen`, `CueStudioScreen`, `DebriefKeepsakesScreen`, and `RelationshipJournalScreen`, eliminating an 11px mobile overflow at `430x932` and expanding Screen `05`'s right Counterpart Folio to its full `63%` column width.
3. **Illustration Bounding**: Updated `Illustration.tsx` (`overflow-hidden`, `h-full max-h-full w-auto max-w-full object-contain`) with explicit heights across all screens so `relationship-folio-circle.png` and `debrief-keepsake-journal.png` never overflow adjacent text.
4. **Screen `02` Slot Highlight & Mad-Libs Single-Row Fit**: Guaranteed the active calendar slot appears first in the 2-card picker strip, deduplicated organization subtitles, and tuned `.brew-madlib-select` padding so all three pill selectors sit on one row.
5. **WCAG 2.1 AA Contrast Calibration**: Calibrated `--color-brew-secondary` (`#6F5E6A`, `6.03:1` on paper and `5.15:1` on pale peach) and small badge/alert text tokens, verified by `@axe-core/playwright` in live Google Chrome with zero serious/critical violations.

## Remaining Intentional Differences from Static Mockups

1. **Screen `02` (`QuickSparkSetupScreen`) User-Approved Overrides**:
   - Primary button label is **`Synthesize Cue Deck`** (rather than `Synthesize 15m Cue Deck`).
   - Static **`HOW YOU CONNECTED`** and **`YOUR COACHING STYLE`** summary boxes are omitted per explicit user instruction.
   - Includes a compact `Or saved person` / `+ Off-calendar person` / `Full profile modal` selector row and collapsible `Fine-tune question count, custom length, or pre-chat notes` drawer to preserve 100% of v1 backend capabilities (`CreateContactRequest`, `preferred_question_count`, `focus_areas`, custom `duration_minutes`, `meeting_notes`).
2. **Interactive Production Controls**:
   - `CueStudioScreen` includes a compact counterpart `<select>` switcher and `New Deck` pill when multiple contacts exist so users can switch folios or start a new deck directly from Cue Studio.
   - `RelationshipJournalScreen` includes a `View all N workspace keepsakes` link when memories exist so cross-counterpart governance remains 1 click away.
   - Timestamps and fixture copy reflect live formatted `Intl.DateTimeFormat` dates and deterministic API fixtures.
