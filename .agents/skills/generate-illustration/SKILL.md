---
name: generate-illustration
description: >-
  Generates and post-processes cohesive "Playful Social Club" 2D flat-vector editorial
  illustrations with true outer alpha transparency for the Brew web app. Use this skill
  whenever the user asks to create, regenerate, or add an illustration, hero artwork,
  character scene, or empty-state visual for Brew, or invokes /generate-illustration.
---

# Generate Brew Illustration (`Playful Social Club`)

Use this workflow to create original, alpha-transparent `.png` editorial illustrations that match [`chat-setup-hero.png`](../../../../web/src/assets/illustrations/chat-setup-hero.png) and [`docs/DESIGN.md`](../../../../docs/DESIGN.md).

## Resources in This Skill

- **Helper CLI**: [`scripts/generate_brew_illustration.py`](./scripts/generate_brew_illustration.py) — Wraps a scene brief in Brew's canonical Playful Social Club prompt, generates the artwork via Vertex AI (`gemini-2.5-flash-image`), flood-fills the outer `#FFFFFF` margin to true alpha transparency via ImageMagick, trims/pads the sticker cutout, and optionally renders a pastel backdrop preview for visual QA.
- **Style & Cast Guide**: [`references/style-guide.md`](./references/style-guide.md) — Exact hex tokens (`#EF8B70` coral, `#E9DFFC` lavender, `#DDF3E7` mint, `#FFE9DE` pale peach, `#302731` dark plum), recurring character descriptions, compositional motifs, and negative constraints. Read it before drafting a new scene brief.

---

## Step-by-Step Workflow

### 1. Draft the Scene Brief
1. Read [`references/style-guide.md`](./references/style-guide.md) to align character clothing, hair/skin tones, and pastel props with existing screens.
2. Choose a descriptive kebab-case asset slug (e.g., `mentorship-checkin-hero`, `followup-note-sent`).
3. Write a 2–4 sentence `--scene` description covering:
   - Waist-up characters, expressions, and hand gestures anchored on a minimal pastel desk/ground strip.
   - Foreground prop(s) (pass `--include-brew-laptop` **only** when the scene features an open laptop with the `"brew."` coral-dot wordmark; otherwise allow zero text).

### 2. Generate & Extract the Transparent PNG

Choose **Path A** (single-step Vertex AI CLI—recommended when Vertex AI project credentials are configured in `.env`) or **Path B** (built-in `image-generator` subagent + local cutout extraction):

#### Path A — Vertex AI CLI (`gemini-2.5-flash-image` + Auto Cutout)
Run the helper script from the repository root (store `--save-raw` and `--preview-out` in your active conversation scratch directory, never in the repo):

```bash
uv run python .agents/skills/generate-illustration/scripts/generate_brew_illustration.py \
  --name "<asset-slug>" \
  --scene "<2-4 sentence scene description>" \
  --preview-out "<scratch-dir>/<asset-slug>-peach-check.png" \
  --preview-bg "#FFE9DF"
```
*(Note: If the terminal sandbox blocks Google Cloud ADC/network access, re-run this single generation command with `BypassSandbox: true`.)*

#### Path B — Built-in `image-generator` Subagent + Sandbox Cutout
1. Print the canonical prompt in the sandbox:
   ```bash
   uv run python .agents/skills/generate-illustration/scripts/generate_brew_illustration.py \
     --name "<asset-slug>" \
     --scene "<2-4 sentence scene description>" \
     --print-prompt-only
   ```
2. Invoke the `image-generator` subagent with that prompt and save the raw output to `<scratch-dir>/<asset-slug>-raw.png`. *(If `image-generator` returns `503 MODEL_CAPACITY_EXHAUSTED`, fall back immediately to Path A.)*
3. Run the deterministic cutout & compression step inside the standard sandbox (`BypassSandbox: false`):
   ```bash
   uv run python .agents/skills/generate-illustration/scripts/generate_brew_illustration.py \
     --name "<asset-slug>" \
     --from-raw "<scratch-dir>/<asset-slug>-raw.png" \
     --preview-out "<scratch-dir>/<asset-slug>-peach-check.png" \
     --preview-bg "#FFE9DF"
   ```

### 3. Visual Quality Gate (Mandatory)
View `<scratch-dir>/<asset-slug>-peach-check.png` using `read_file` and verify:
- **Clean Alpha Cutout**: The white sticker halo sits cleanly against `#FFE9DF` with no rectangular white corners, jagged fringes, or accidentally erased interior whites (speech bubble, laptop, smile). If faint outer white pixels remain, re-run `--from-raw` with `--fuzz-percent 6`.
- **Family Consistency**: 2D flat-vector editorial look, warm skin tones, dark cocoa-brown hair, minimal dot/arc eyes, subtle rosy cheeks, soft pastel clothing, and zero coffee cups, 3D shading, or garbled text.

### 4. Wire into `Illustration.tsx` & Validate
1. Import `../../assets/illustrations/<asset-slug>.png` in [`web/src/components/ui/Illustration.tsx`](../../../../web/src/components/ui/Illustration.tsx), extend `IllustrationName`, and provide a descriptive `defaultAlt`.
2. Add the new asset to the Illustration Asset Catalog table in [`docs/DESIGN.md`](../../../../docs/DESIGN.md).
3. Run frontend validation checks (`npm --prefix web test`, `npm --prefix web run typecheck`, `npm --prefix web run lint`, `npm --prefix web run build`).
