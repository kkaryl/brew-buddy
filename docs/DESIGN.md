# Design System & Illustration Specification: Brew

**Product:** Brew · AI-Powered Coffee Chat & Relationship Companion  
**Design Direction:** Playful Social Club · Modern Pastel Editorial SaaS  
**Canonical Token Stylesheet:** [`web/src/index.css`](../web/src/index.css)  
**Illustration Directory:** [`web/src/assets/illustrations/`](../web/src/assets/illustrations/)

---

## 1. Visual Aesthetic & Brand Personality

Brew is **not** a coffee shop, cafe ordering utility, or e-commerce storefront. It is an AI networking and relationship companion that helps professionals prepare thoughtful conversations, remember interpersonal context with explicit consent, and follow up with warmth.

The visual experience blends four touchpoints:
1. **A premium, contemporary lifestyle app**: airy off-white canvas (`#FFFAF8`), soft pastel color blocking, and generous whitespace.
2. **A friendly, illustrated productivity companion**: cohesive flat-vector editorial characters that feel human, optimistic, and approachable.
3. **A beautifully designed digital journal**: expressive `Fraunces` serif headlines paired with crisp `DM Sans` body typography on rounded paper surfaces (`#FFFFFF`).
4. **A modern AI application with human governance**: transparent revision snapshots and Human-in-the-Loop memory review cards without robotic enterprise clutter.

### Explicit Anti-Patterns (Never Use)
- Generic monochrome enterprise dashboards or dense data-grid layouts
- Heavy black borders, thick outlines, or harsh black drop shadows
- Excessive glassmorphism, neon gradients, or futuristic cyberpunk dark themes
- Random emojis used as primary hero or empty-state illustrations
- Stock photography of coffee cups, beans, or cafes
- Headline "biscuit pills" with pulsing dots above hero titles, or CSS gradient text fills
- Fake iOS/Android mobile status bars inside the web application
- Noisy system telemetry pills in navigation headers (e.g., `"GCal Sync"`, `"Coaching DNA Applied"`, `"PII Auto-Scrub Active"`)
- **Em-dashes (`U+2014` / `&mdash;`) anywhere in the web portal** (never use em-dashes in UI copy, titles, metadata, placeholders, badges, or generated brief cards; use periods, commas, colons, parentheses, or `·` middle dots instead)
- Oversized decorative elements that crowd primary actions or form controls

---

## 2. Centralized Design Tokens

All visual tokens are defined in [`web/src/index.css`](../web/src/index.css) via both `:root` CSS custom properties and Tailwind CSS v4 `@theme` variables. Components MUST consume these semantic tokens rather than introducing ad-hoc hex values.

### 2.1 Color Palette

| Semantic Role | CSS Variable | Tailwind Token | Hex | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **App Background** | `--brew-bg-app` | `brew-bg` | `#FFFAF8` | Global page canvas and header backdrop |
| **Primary Paper Surface** | `--brew-surface-paper` | `brew-paper` | `#FFFFFF` | Primary cards, form inputs, modals, bottom dock |
| **Primary Dark Text** | `--brew-text-primary` | `brew-plum` | `#302731` | Headlines, primary copy, wordmark letters (never `#000000`) |
| **Secondary Text** | `--brew-text-secondary` | `brew-secondary` | `#6F5E6A` | Supporting descriptions, metadata, eyebrows (`>= 5.15:1` WCAG AA contrast on paper and pastel tints) |
| **Muted Placeholder** | `--brew-text-placeholder` | `brew-muted` | `#A69AA7` | Form input and textarea placeholder copy |
| **Primary Dark Button** | `--brew-btn-primary` | `brew-dark-btn` | `#342B36` | High-emphasis primary action buttons |
| **Coral Accent** | `--brew-coral` | `brew-coral` | `#EF8B70` | Wordmark dot, radiating strokes, warm badges, illustration accents |
| **Vibrant Coral** | `--brew-coral-vibrant` | `brew-coral-vibrant` | `#E9785B` | Validation alert rings, high-emphasis warm accents |
| **Pale Peach** | `--brew-peach-pale` | `brew-peach` | `#FFE9DE` | Selected bottom navigation pill, hero accents, soft chips |
| **Warm Blush** | `--brew-blush-warm` | `brew-blush` | `#FFF1EC` | Subtle callout blocks and secondary warm surfaces |
| **Lavender** | `--brew-lavender` | `brew-lavender` | `#E9DFFC` | Circular user initial avatar, secondary tags, illustration backdrops |
| **Pale Lilac** | `--brew-lilac-pale` | `brew-lilac` | `#F5F0FC` | Soft lavender surface highlights |
| **Purple Accent** | `--brew-purple` | `brew-purple` | `#8C67BC` | Keyboard `:focus-visible` ring, memory provenance accents |
| **Mint** | `--brew-mint` | `brew-mint` | `#DDF3E7` | Grounded memory pills, success accents, illustration circles |
| **Pale Mint** | `--brew-mint-pale` | `brew-mint-pale` | `#F0F8F3` | Subtle grounded-context containers |
| **Deep Mint** | `--brew-mint-deep` | `brew-mint-deep` | `#3F9678` | Positive status text, runtime live badges |
| **Pale Yellow** | `--brew-yellow-pale` | `brew-yellow` | `#FFF2CD` | Gentle notices, historical revision snapshot banners |
| **Subtle Border** | `--brew-border-subtle` | `brew-border` | `#EEE4E6` | Hairline card borders, dividers, and input outlines |

### 2.2 Pastel Gradients

| Token / Utility | CSS Definition | Intended Surface |
| :--- | :--- | :--- |
| `--brew-gradient-peach-hero` (`.brew-hero-peach`) | `linear-gradient(135deg, #FFE9DF 0%, #FFF3EC 56%, #FFFDFB 100%)` | Hero banners (`PastelHero`), chat setup showcase |
| `--brew-gradient-lavender-card` (`.brew-card-lavender`) | `linear-gradient(145deg, #F8F4FF 0%, #EEE6FC 100%)` | Reflection/review highlight cards, coaching tips |
| `--brew-gradient-mint-card` (`.brew-card-mint`) | `linear-gradient(145deg, #F2FAF5 0%, #E4F4EA 100%)` | Grounded relationship memory cards, runtime readiness |
| `--brew-gradient-coral-highlight` (`.brew-card-coral`) | `linear-gradient(135deg, #FFE4D8 0%, #FFF2EB 100%)` | Upcoming chat spotlights, primary warm callouts |

### 2.3 Ambient Shadows

Brew avoids thick or harsh black shadows in favor of diffused lavender and warm-plum ambient elevation:
- `--shadow-card`: `0 8px 24px -6px rgba(48, 39, 49, 0.045), 0 2px 8px -2px rgba(140, 103, 188, 0.05)`
- `--shadow-ambient`: `0 10px 30px -8px rgba(140, 103, 188, 0.08), 0 3px 10px -3px rgba(48, 39, 49, 0.04)`
- `--shadow-floating`: `0 16px 40px -10px rgba(140, 103, 188, 0.14), 0 6px 16px -4px rgba(48, 39, 49, 0.06)`

---

## 3. Typography, Wordmark, & Microcopy

- **Headline Serif (`--font-serif`)**: `Fraunces` (weight `700`, optical sizing `9..144`, tight tracking `-0.014em` to `-0.026em`). Used for page heroes, page headings, section headings, and editorial card titles.
- **Body & UI Sans (`--font-sans`)**: `DM Sans` (weights `400`–`700`). Used for body copy, form controls, navigation labels, pills, and metadata.
- **Wordmark (`BrewLogo` / `.brew-wordmark`)**: Lowercase `"brew."` set in `DM Sans` weight `800` with tight `-0.045em` letter-spacing in `#302731` dark plum and a `#EF8B70` coral-orange period (`.` dot), sized at `~32px` in `AppHeader`.
- **Microcopy & Punctuation Discipline (Zero Em-Dashes)**:
  - **Eliminate em-dashes**: Never render em-dashes (Unicode `U+2014` or HTML `&mdash;`) anywhere in the web portal, including `<title>` / `<meta>` tags, hero descriptions, card copy, form labels, placeholders, badges, or AI-generated brief surfaces.
  - **Preferred punctuation**: Break clauses cleanly into short sentences with periods, or join related phrases with commas, colons, or `·` middle dots (e.g., `"2:00 - 2:30 PM · Principal SRE at CloudScale"`).
  - **Concise attribution**: Keep source tags short and human (e.g., `"from GCal"` rather than `"Linked from GCal"` or `"Detected on Google Calendar"`), and avoid surfacing internal system status pills in user-facing headers.

### Typography Scale

| Role | Mobile Size | Desktop Size | Font & Weight | CSS Utility |
| :--- | :--- | :--- | :--- | :--- |
| **Page Hero** | `38px–46px` | `52px–58px` | `Fraunces` 700, `-0.026em` | `.brew-hero-heading` |
| **Page Heading** | `30px–34px` | `34px–38px` | `Fraunces` 700, `-0.022em` | `.brew-page-heading` |
| **Section Heading** | `23px–25px` | `25px–27px` | `Fraunces` 700, `-0.018em` | `.brew-section-heading` |
| **Card Heading** | `18px–20px` | `20px–22px` | `Fraunces` 700, `-0.014em` | `.brew-card-heading` |
| **Body Copy** | `14px–15px` | `15px–16px` | `DM Sans` 400 / 500 | Base `body` |
| **Supporting Text** | `12px–13px` | `13px–14px` | `DM Sans` 400 / 500 | `text-xs` / `text-sm` |
| **Uppercase Eyebrow** | `11px–12px` | `11.5px–12px` | `DM Sans` 700, `+0.11em` | `.brew-eyebrow` |

---

## 4. Spacing, Radii, & Responsive Layout

- **Mobile Horizontal Gutter**: `20px` (`px-5`), optimized first for `375px–430px` viewports.
- **Desktop Maximum Container Width**: `1200px` (`max-w-[1200px] mx-auto`).
- **Section Vertical Rhythm**: `24px–32px` (`space-y-6` to `space-y-8`).
- **Card Padding**: `20px–28px` (`p-5` to `p-7`).
- **Border Radii**:
  - Cards: `24px–30px` (`rounded-[26px]` / `rounded-card`)
  - Large Heroes: `32px–38px` (`rounded-[34px]` / `rounded-hero`)
  - Primary Action Buttons: `16px–22px` (`rounded-[18px]` / `rounded-btn-primary`)
  - Pill Controls & Chips: `999px` (`rounded-full`)
- **Touch Targets**: Minimum `44px × 44px` (`min-h-[44px]`) across buttons, navigation items, segmented pills, and inputs.
- **Desktop Adaptation (`md` / `lg`)**:
  - Forms and live illustrated previews sit side-by-side (e.g., 7-column brief setup form + 5-column sticky `PastelHero` blueprint preview).
  - Counterparts, questions, and memories expand cleanly into 2-column and 3-column editorial card grids rather than stretching mobile cards edge-to-edge.
  - Illustrations use `object-contain` with generous aspect framing so faces are never stretched or cropped.

---

## 5. V2 3-Space Shell & Focused Ritual Architecture

### 5.1 Primary Browsing Shell (`TopBarShell` & `MobileDock`)
Brew v2 organizes browsing around **three primary spaces**:
1. **Clubhouse** (`ClubhouseScreen`): Calendar-aware Up-Next Coffee Chat hero, Quick Spark natural-language prompt bar, read-only Google Calendar / `.ics` upcoming & wrapped chat feed (`from GCal`), Keepsakes to Stamp card, and Warm Reconnect nudge.
2. **Cue Studio** (`CueStudioScreen`): Proportional Run-of-Show pacing ribbon, warm icebreakers, 2x2 star-able Cue Cards (`Starred` for Pocket Glance), immutable `v1`/`v2` revision switcher, and sticky lavender `Tune on the fly` Brief Co-Pilot.
3. **Relationship Journal** (`RelationshipJournalScreen`): Two-column Relationship Atlas pairing Counterpart Folios (approved keepsakes, earlier-notes toggle, and conversation timeline) with `My Coaching Style` defaults, calendar sync settings, and runtime health.

- **Desktop / Tablet (`TopBarShell`)**: Sticky off-white bar with `BrewLogo` (`"brew."`) on the left, centered 3-space segmented pill (`#FFE9DE` active indicator + coral pending-keepsakes badge), `+ Quick Spark` coral pill CTA, and circular `#E9DFFC` user initial avatar on the right.
- **Mobile (`MobileDock`)**: Floating pill dock (`Clubhouse`, `Studio`, `Journal`) paired with a circular `#EF8B70` coral `+` Quick Spark action button.

### 5.2 Focused Rituals (`FocusedTopBar`)
When entering a focused ritual, both `TopBarShell` and `MobileDock` unmount in favor of `FocusedTopBar` (`← Back` pill + centered `BrewLogo` or eyebrow) so navigation chrome never competes with the primary task:
- **Conversation Setup (`QuickSparkSetupScreen`)**: Calendar slot picker, single-row pastel Mad-Libs controls (`duration`, `tone`, `purpose`), objective input, illustrated Pacing Blueprint, and `Synthesize Cue Deck` CTA.
- **Pocket Cue Cards (`PocketCueCardsScreen`)**: Phone-friendly live-chat glance deck displaying proportional time blocks, warm icebreaker, starred cue cards (`localStorage` per `brief_id`), closing prompt, and fixed bottom Quick-Tune bar.
- **Debrief & Keepsakes (`DebriefKeepsakesScreen`)**: Post-chat guided reflection pad paired with Human-in-the-Loop Suggested Keepsake cards (`Stamp Keep`, `Edit`, `Toss`, and supersession indicators).

---

## 6. Illustration Art Direction & Asset Catalog

All decorative artwork belongs to a single cohesive flat-vector editorial family:
- **Character Styling**: Friendly hand-drawn proportions with smooth digital curves, warm skin tones (`#E39E7D`, `#C7825F`), dark cocoa-brown hair (`#322022`), minimal facial features (tiny tapered smiles, small dot eyes, subtle `#F08A7E` rosy cheeks), soft pastel clothing (`#EF8B70` coral-peach, `#C6B1F5` lavender, `#DDF3E7` mint), and slight pose asymmetry.
- **Compositional Motifs**: Overlapping pastel circles (`#FFE9DE`, `#E9DFFC`, `#DDF3E7`) with crisp `#FFFFFF` cutout borders, white speech bubbles with three dark plum/purple dots (`#302731` / `#8C67BC`), and small coral-orange (`#EF8B70` / `#E9785B`) radiating strokes.
- **Asset Execution**: All four primary v2 screen illustrations are generated via Gemini image generation in the Playful Social Club flat-vector style and processed with true outer alpha transparency, paired with fallback `.svg` scenes in the same character family.
- **Reusable Project Skill (`generate-illustration`)**: When adding or refreshing illustrations, invoke the workspace skill at [`.agents/skills/generate-illustration/SKILL.md`](../.agents/skills/generate-illustration/SKILL.md) (or type `/generate-illustration`), which wraps scene briefs in the canonical Playful Social Club prompt and runs [`generate_brew_illustration.py`](../.agents/skills/generate-illustration/scripts/generate_brew_illustration.py) for automated outer-margin alpha extraction and edge verification.

| Asset File | Scene Description | Primary Placement |
| :--- | :--- | :--- |
| [`chat-setup-hero.png`](../web/src/assets/illustrations/chat-setup-hero.png) | Smiling woman and friendly man chatting warmly across an open pale-ivory `"brew."` laptop (`898x571` alpha PNG). | `ClubhouseScreen` Up-Next Hero, `QuickSparkSetupScreen` Pacing Blueprint, & `AuthSignInGate` |
| [`cue-studio-copilot.png`](../web/src/assets/illustrations/cue-studio-copilot.png) | Friendly conversation co-pilot holding starred pale-ivory cue cards framed by pastel shapes (`722x603` alpha PNG). | `CueStudioScreen` Brief Co-Pilot & `PocketCueCardsScreen` header |
| [`debrief-keepsake-journal.png`](../web/src/assets/illustrations/debrief-keepsake-journal.png) | Smiling woman writing reflections into an open pastel journal alongside floating keepsake cards (`1072x812` alpha PNG). | `DebriefKeepsakesScreen` desktop banner & mobile header |
| [`relationship-folio-circle.png`](../web/src/assets/illustrations/relationship-folio-circle.png) | Three smiling colleagues standing together with a coral relationship folio and pastel circles (`1081x671` alpha PNG). | `RelationshipJournalScreen` companion card & `ClubhouseScreen` Warm Reconnect |

---

## 7. Reusable Component System

Located under [`web/src/components/shell/`](../web/src/components/shell/), [`web/src/components/ui/`](../web/src/components/ui/), and [`web/src/components/domain/`](../web/src/components/domain/):

- **Brand & Contextual Shell**: `BrewLogo`, `TopBarShell`, `MobileDock`, `FocusedTopBar`
- **Editorial Containers & Artwork**: `PastelHero`, `Illustration`, `SectionHeader`, `IconTile`, `PastelCard`
- **Interactive Controls & Forms**: `PrimaryButton`, `PillButton`, `SegmentedChoice`, `FormField`, `ContactAvatar`
- **Domain Cards & Ribbons**: `PacingRibbon` (`RunOfShowRibbon`), `CueQuestionCard`, `KeepsakeProposalCard`, `ApprovedKeepsakeCard`
- **Feedback & States**: `EmptyState`, `LoadingSkeleton`, `StatusBanner`

Every component enforces semantic HTML landmarks (`<header>`, `<main>`, `<nav>`, `<section>`, `<aside>`), single `<h1>` per screen, explicit `<label htmlFor>` bindings, `aria-invalid` / `role="alert"` field validation messages, visible `#8C67BC` `:focus-visible` outlines, WCAG 2.1 AA contrast (`0` critical/serious `@axe-core/playwright` violations in live Chrome), and `prefers-reduced-motion` compliance.
