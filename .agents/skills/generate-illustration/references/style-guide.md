# Brew "Playful Social Club" Illustration Style Guide

This reference defines the visual DNA shared by every illustration in **Brew** (see [`docs/DESIGN.md`](../../../../docs/DESIGN.md)). Use these specifications when writing `--scene` briefs for [`generate_brew_illustration.py`](../scripts/generate_brew_illustration.py).

---

## 1. Visual Identity & Tone

Brew is an **AI-powered Coffee Chat & Professional Relationship Companion**—never a cafe ordering app or coffee e-commerce store. Every illustration should feel warm, human, contemporary, gently playful, and editorial:
- **2D Flat-Vector Editorial Aesthetic**: Hand-drawn warmth with crisp digital contours, smooth rounded shapes, and slight pose asymmetry.
- **Sticker-Cutout Framing**: Group the scene over overlapping pastel circular backdrops enclosed by a clean white sticker-cutout halo on a pure `#FFFFFF` outer margin so outer flood-fill produces a crisp alpha-transparent PNG.
- **Minimalist Expressive Faces**: Small dark plum dots or gentle arcs for eyes, tiny curved smiles, subtle rosy cheeks, and relaxed postures.

---

## 2. Canonical Color Palette

Always anchor clothing, backdrops, and props in Brew's exact pastel tokens:

| Element | Hex Token | Usage in Illustrations |
| :--- | :--- | :--- |
| **Coral Peach** | `#EF8B70` | Primary character knitwear/tops, radiating excitement strokes, `"brew."` period dot, notebook covers |
| **Vibrant Coral** | `#E9785B` | Subtle secondary accents, checkmarks, ribbon bookmarks |
| **Pale Peach** | `#FFE9DE` | Soft background circles, warm surface highlights |
| **Lavender** | `#E9DFFC` / `#C6B1F5` | Background circles, collared shirts, journal accents |
| **Purple Accent** | `#8C67BC` | Speech-bubble middle dot, journal bindings, subtle collar details |
| **Mint** | `#DDF3E7` | Overlapping background circles, cardigans, desk surface strips |
| **Pale Yellow** | `#FFF2CD` | Small floating accent dots or warm sticky-note shapes |
| **Dark Plum / Cocoa** | `#302731` / `#322022` | Hair silhouettes, thin round glasses frames, minimal linework, speech-bubble dots |
| **Pale Ivory** | `#FFF9F2` | Laptop lids, open notebook pages, speech bubbles (`#FFFFFF`) |

---

## 3. Recurring Character Cast (Optional Continuity)

Using recurring characters across screens reinforces visual cohesion, though you may adapt poses, props, or introduce new peers in the same style:

1. **Character A (The Expressive Connector)**:
   - Young adult woman, warm medium-tan skin, long wavy dark cocoa-brown hair styled partly into a high bun, small gold hoop earrings, coral-peach (`#EF8B70`) or soft mint (`#DDF3E7`) long-sleeve top.
2. **Character B (The Thoughtful Listener)**:
   - Young adult man, warm skin tone, short fluffy curly dark-brown hair, small round dark-plum (`#302731`) glasses, soft lavender-purple (`#C6B1F5`) collared shirt.

---

## 4. Signature Compositional Motifs

Include 2–3 of these family motifs in every scene so new assets pair naturally with `chat-setup-hero.png`:
- Overlapping soft pastel **mint (`#DDF3E7`) and lavender (`#E9DFFC`) circular shapes** behind the subject.
- A crisp **white rounded speech bubble** containing **three dark plum/purple circular dots** (never text).
- Small **coral-orange (`#EF8B70`) radiating stroke lines** near speech bubbles, hands, or journals to convey warmth and insight.
- A clean minimal horizontal pastel desk or ground strip anchoring waist-up characters so figures never float awkwardly or get cut off mid-torso.

---

## 5. Strict Negative Constraints (Never Include)

- **No coffee cups, mugs, espresso machines, or latte art** (Brew is about interpersonal conversations, not beverages).
- **No embedded text, labels, or paragraphs** (the sole exception is `--include-brew-laptop`, which places the lowercase `"brew."` wordmark with a `#EF8B70` coral dot on a laptop lid).
- **No 3D/Pixar rendering, photorealism, gradients/airbrushing on skin, pixel art, anime, or emoji art**.
- **No textured, beige, or gradient outer backgrounds**—the outer margin touching all four canvas edges must remain pure uniform `#FFFFFF` for clean alpha flood-fill extraction.

---

## 6. Example `--scene` Briefs

- **Mentorship Check-In (`mentorship-growth-hero`)**:
  > `"Waist-up horizontal scene of two friendly professionals reviewing a shared pastel coral growth notebook across a minimal mint desk strip: on the left, a smiling young man with short fluffy curly dark-brown hair, round dark-plum glasses, and a lavender collared shirt points warmly to an abstract milestone card; on the right, a smiling young woman with wavy dark cocoa-brown hair in a half-up bun, gold hoop earrings, and a pale mint cardigan nods encouragingly."`
- **Follow-Up Note Sent (`followup-note-celebration`)**:
  > `"Waist-up scene of a cheerful young woman with wavy dark cocoa-brown hair in a high bun, gold hoop earrings, and a coral-peach long-sleeve top holding a folded ivory thank-you card with a tiny coral heart seal, framed by overlapping lavender and mint circles."`
