# Iconography — Buddha Cognitive Lab

## Approach
No icon set, icon font, or SVG icon library was provided (no codebase or Figma). The system therefore standardizes on a single CDN line-icon set chosen to match the brand's calm, premium, geometric feel.

## Standard icon set — Lucide *(substitution — flagged)*
- **Library:** [Lucide](https://lucide.dev) via CDN.
- **Why:** thin, consistent 1.5–2px strokes, rounded joins, geometric construction. It reads calm and refined rather than playful or heavy — the right register for "premium zen-tech." It is the closest widely-available match to the brand's restraint.
- **This is a substitution.** If Buddha Cognitive Lab has its own icon set, please share it and we will swap Lucide out.

**Load (CDN):**
```html
<script src="https://unpkg.com/lucide@latest"></script>
<!-- usage -->
<i data-lucide="sparkles"></i>
<script>lucide.createIcons();</script>
```
Or per-icon SVG from `https://unpkg.com/lucide-static@latest/icons/<name>.svg`.

## Usage rules
- **Stroke weight:** 1.75px nominal at 24px. Keep one weight across a surface.
- **Size:** 16 / 20 / 24px in UI; up to 32px for feature/marketing. Hit target ≥ 44px.
- **Color:** icons inherit `currentColor` — default to `--fg-muted`; use `--accent` (gold) only for active/selected or a single focal icon. Never fill icons with gold wholesale.
- **No emoji.** The brand never uses emoji. Where a product might reach for an emoji, use a Lucide line icon or a mono glyph instead.
- **Mono glyphs** (·, →, ↗, ⌘, /, ✓) are used inline in mono-set technical text and CTAs ("Design your Buddha →"). These are typographic, not icons.

## The brand's own visual device — the dot / halftone motif
The logo mark is built from a field of dots forming a "B"/seated figure. This **dotted/halftone motif is the brand's signature graphic device** and should be used in place of decorative iconography:
- Faded, enlarged mark as a **watermark** behind heroes/section breaks (very low opacity, gold or neutral).
- **Sparse dot fields** as texture in empty space.
- The mark as a **loading / "thinking" indicator** for agents (dots animating in sequence) — a natural fit for an AI-agent product.

Mark assets for this device live in `assets/` (`logo-mark-gold.svg`, `logo-mark-white.svg`, `logo-mark-black.svg`).

## Suggested icon vocabulary (Hire Buddha)
| Concept | Lucide icon |
|---|---|
| Agent / employee | `bot`, `user-round` |
| Design / shape an agent | `sparkles`, `wand-2` |
| Hire / employ | `briefcase`, `badge-check` |
| Tools / integrations | `plug`, `puzzle` |
| Run / automate | `play`, `workflow`, `repeat` |
| Tasks / queue | `list-checks`, `inbox` |
| Logs / tracing | `terminal`, `activity` |
| Model / lab | `brain`, `cpu`, `flask-conical` |
| Goals / outcomes | `target`, `trending-up` |
| Settings / training | `sliders-horizontal`, `graduation-cap` |
