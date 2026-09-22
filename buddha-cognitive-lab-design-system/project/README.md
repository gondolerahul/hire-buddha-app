# Buddha Cognitive Lab — Design System

> **Towards digital enlightenment.**

This repository is the brand & product design system for **Buddha Cognitive Lab** and its first product, **Hire Buddha**. It gives design agents everything needed to produce on-brand interfaces, decks, and marketing assets: brand logos, color & type tokens, written voice, visual foundations, and high-fidelity UI-kit components.

---

## 1 · COMPANY & PRODUCT CONTEXT

**Buddha Cognitive Lab** is a **frontier AI research lab** — it researches and ships frontier AI models with practical, real-world applicability. It is the **parent brand**.

**Hire Buddha** is the lab's **first product**: a platform where business users **design their dream employees** — autonomous AI agents — and **employ them to automate entire business operations**. The thesis is bold and human: *make the one-person company possible, and let small businesses flourish* by giving anyone a full, tireless, autonomous workforce.

The brand voice sits at the intersection of **calm Eastern philosophy and frontier technology** — "Buddha" (enlightenment, clarity, mastery) meets "Cognitive Lab" (rigor, research, intelligence). The product promise: hire an agent the way you'd hire a person, and reach a state of operational *enlightenment* where the busywork runs itself.

### Brand architecture
| Brand | Role | Use |
|---|---|---|
| **Buddha Cognitive Lab** | Parent / research lab | Corporate site, research/docs, papers, hiring, investor materials |
| **Hire Buddha** | Product | The app, product marketing, onboarding, dashboards |

The **dotted "B" mark** (a halftone arc of gold dots forming a stylized *B* / meditative figure) is the shared symbol across both. The lab uses the full "Buddha Cognitive Lab" lockup; the product uses "Hire Buddha."

### Sources provided
- `uploads/Icon.svg` — the dotted-B icon mark (gold gradient)
- `uploads/Hire Buddha.svg` — Hire Buddha wordmark lockup
- `uploads/Budddha Cognitive Lab.svg` — Buddha Cognitive Lab wordmark lockup
- `uploads/Business Card Virtical.pdf` — vertical business card (vector content did not composite in any available renderer; see CAVEATS)
- Website: **https://buddhalab.in** (single-page app — copy not machine-extractable at build time)
- Tagline: **"Towards digital enlightenment"**

> **No codebase or Figma file was provided.** Product surfaces, screens, and copy in the UI kits are an **informed brand-consistent interpretation** of the product described above — not a recreation of an existing build. Treat them as a high-fidelity starting point to refine against the real product.

---

## 2 · CONTENT FUNDAMENTALS  *(voice & tone)*

The voice is **calm, confident, and quietly profound** — a frontier lab that doesn't shout. It pairs **plain, concrete product language** with **occasional philosophical lift**. Think: a brilliant, unhurried founder who has nothing to prove.

**Tone in one line:** *Serene authority. Big ideas, said simply.*

### Principles
- **Calm over hype.** State the capability; let it land. Avoid exclamation marks, "revolutionary," "game-changing," emoji-as-punctuation.
- **Concrete over abstract — then one lift.** Lead with what it does ("Design an agent that runs your support inbox"), then allow a single resonant line ("Operations, at rest.").
- **"You" for the customer, "we" for the lab.** Address the reader directly. Speak as a collective when describing the lab's work.
- **Verbs of mastery & calm.** *design, employ, delegate, orchestrate, refine, rest, flourish, attend, awaken.* Avoid frantic verbs (*crush, hustle, supercharge, blast*).
- **Sentence case everywhere** for headings and UI. Reserve **UPPERCASE** for short eyebrow labels and the wordmark only (tracked wide, in Chakra Petch).
- **Numbers stay honest.** Use real, specific figures when known; never invent stats to fill space.

### Vocabulary
- The agents are **employees / your team / your workforce** — hired, not "deployed." Each is a **Buddha** (e.g. "your support Buddha").
- Building one is **designing** or **hiring**; running them is **employing** or **delegating**.
- Outcomes framed as **enlightenment / clarity / rest / flourishing**, never "10x" or "domination."

### Emoji & casing
- **No emoji** in brand or product surfaces. The dotted-B mark and the gold are the only "ornament."
- **No ALL-CAPS sentences.** Eyebrows/kickers only, e.g. `TOWARDS DIGITAL ENLIGHTENMENT`, `RESEARCH`, `THE WORKFORCE`.

### Examples
- Hero: **"Design your dream employee. Employ them today."** · sub: *"Autonomous AI agents that run your operations — so a company of one can do the work of a hundred."*
- Eyebrow: `HIRE BUDDHA · AUTONOMOUS WORKFORCE`
- CTA: **Hire your first Buddha** · secondary **See how it works**
- Empty state: *"No Buddhas employed yet. Design your first and let the work begin."*
- Lab / research: **"Frontier models, practical minds."** · *"We research intelligence that does real work in the real world."*
- Quiet philosophical lift (use sparingly): *"The mind at rest does more. So should your business."*

---

## 3 · VISUAL FOUNDATIONS

The system is **premium, calm, zen-tech**: vast warm-black space, restrained gold, generous air, and one angular, faceted typeface that nods to the wordmark. Gold is precious — used as accent and light, never as flood fill.

### Color
- **Palette is intentionally narrow: gold + warm near-black + warm white.** No secondary brand hues.
- **Gold** is sampled directly from the logo gradient: `#fdc871 → #edab48 → #ffefd8 → #fdc871`. The primary solid gold is **`#edab48`** (`--gold-500` / `--accent`). The **signature gradient** (`--gradient-gold`) is reserved for the mark, hero words, key figures, hairline rules, and primary buttons; a richer **`--gradient-gold-metallic`** is used for premium plates, medallions, and special CTAs.
- **Canvas** is a warm near-black **`#0a0908`** (`--ink-950` / `--bg`); surfaces step up through warm charcoals (`--surface → --surface-3`).
- **Text** on dark: warm white `#f6f1e9` (primary), `#b3aaa0` (secondary), `#7c746b` (muted).
- A **light "paper"** scale exists for the business-card front and optional light docs mode.
- **Semantic colors are deliberately desaturated and warm** (sage success `#6fae84`, terracotta danger `#d4664f`) so they never compete with the gold. Use sparingly. Warning = gold.

### Typography
- **Logotype / brand & big hero words:** **Roblox** (self-hosted, in `fonts/`) — an angular, faceted display face whose chunky geometric letterforms are the closest available match to the brand's custom outlined wordmark. Used for the logotype feel, hero `h1`, and `.logotype`. A companion **Roblox Outline** cut is used for outlined hero word treatments.
- **Display / headings:** **Space Grotesk** — geometric, premium, modern; used for `display-*`, `h1`–`h3`.
- **Body / UI / reading:** **Hanken Grotesk** (300–800) — calm, legible, neutral-warm; paragraphs and all UI text.
- **Mono:** **JetBrains Mono** — eyebrows/kickers, agent IDs, data, code, terminals.
- Headings: tight tracking, balanced wrap. Body: relaxed 1.7 line-height for calm. Eyebrows: UPPERCASE mono, `0.16em` tracking, gold.
- **⚠️ Font substitution:** the brand wordmark is custom (delivered as outlines, no font file). **Roblox** (logotype), **Space Grotesk** (display), **Hanken Grotesk** (body) and **JetBrains Mono** (mono) are the closest available substitutes. The Roblox face is used purely as a visual stand-in for prototyping — **swap in the real faces when available.** See CAVEATS.

### Space & layout
- **Generous space is the brand.** Large section padding (`--s-9`/`--s-10`), wide hero margins, lots of breathing room around the mark. Zen = emptiness with purpose.
- 4px spacing grid (`--s-1`…`--s-12`). Content max-width ~1200px on marketing; comfortable 720px measure for long-form docs.
- Layouts are **calm and grid-aligned**, asymmetry used intentionally (the dotted-B often bleeds off an edge as a quiet watermark).

### Backgrounds & texture
- Predominantly **flat warm-black** — no busy gradients. Depth comes from **surface steps + hairline borders + soft shadow**, not color.
- Allowed atmospherics, used subtly: a **radial gold glow** (`--glow-gold`) behind hero content; the **dotted-B mark** at very low opacity as a large background watermark; fine **grain** is optional but light.
- **No stock photography by default.** Imagery, when used, is **dark, warm, high-contrast, slightly golden** — never cool/blue. Product UI screenshots sit in dark device frames.

### Motion
- **Calm and decisive.** Default easing `--ease-out` (`cubic-bezier(.16,1,.3,1)`) — a confident settle, no bounce. Durations 120–640ms.
- **Fades and gentle rises** (8–16px) for entrances; no spinning, no springy overshoot. Gold elements may **breathe** (a slow, subtle glow pulse) but nothing frantic. Respect `prefers-reduced-motion`.

### Interaction states
- **Hover:** surfaces lighten one step (`--surface → --surface-2`); gold buttons shift to `--accent-hover` and lift `1px`; ghost items pick up a `rgba(255,255,255,.05)` wash; metallic surfaces sweep a specular band (`--gradient-gold-shine`).
- **Press:** a small `translateY(1px) scale(.99)` — a gentle, grounded push (`--accent-press` for gold).
- **Focus:** gold focus ring `--focus-ring` (`0 0 0 3px rgba(237,171,72,.32)`). Never remove focus outlines.
- **Disabled:** drop to `--fg-faint`, reduce opacity, no shadow.

### Borders, radii & shadows
- **Borders** are warm-white at low alpha (`--border` .08 → `--border-strong` .16) so they read on any surface; gold borders (`--border-gold`) mark active/brand elements.
- **Radii** are restrained (the wordmark is angular): `--r-sm` 7 → `--r-lg` 16 for cards, `--r-pill` for pills/buttons. Scale runs `--r-xs` 4 … `--r-2xl` 30.
- **Shadows** are soft and deep (`--shadow-md/-lg`) for premium float; the **gold glow** (`--glow-gold`) and **`--shadow-gold`** mark primary/active brand moments. Avoid hard or bright shadows.

### Cards
- Default card: `--surface` fill, `1px` `--border`, `--r-lg` radius, `--shadow-md`. On hover, border → `--border-strong` / `--border-gold` and a faint lift. **Featured/brand cards** add a gold hairline (`.hairline-gold`), a metallic edge, or the `--glow-gold`.

### Transparency & blur
- Use **frosted blur** (`backdrop-filter: blur(…)`) on sticky headers and overlay menus over the dark canvas — subtle, never milky. Modals dim the page with `rgba(0,0,0,.6)` + blur.

### Liquid glass *(material)*
A first-class **"Apple liquid glass"** material, tuned to the brand: translucent warm-dark panels that **refract the gold beneath them**. The recipe is three layers — a translucent tint, a heavy backdrop blur + saturation lift, and a *lens edge* (bright top rim + base shade + soft drop) — finished with a diagonal specular sheen.
- **Tokens:** `--glass-tint` / `-light` / `-gold` / `-strong` (surfaces), `--glass-blur` / `--glass-blur-strong` (filters), `--glass-border`, `--glass-edge` / `--glass-edge-gold` (the lens), `--glass-sheen` (highlight). All have light-mode (paper) variants.
- **Utilities** (in `styles.css`): `.glass`, `.glass-gold`, `.glass-strong`, `.glass-bar`, `.btn-glass` (+ `.btn-glass-gold`), and `.glass-sheen-off`.
- **Use it for** floating chrome (nav/toolbars/command bars), overlays & modals, hero/feature cards, and controls (segmented, toggles, buttons) — **always over something colorful** (the dotted-B mark, the gold glow, or imagery) so the refraction reads. Keep it occasional and premium; flat surfaces remain the default. Falls back to a solid `--surface` under `prefers-reduced-transparency`. See the **Material** cards in the Design System tab.

---

## 4 · ICONOGRAPHY

- **Brand symbol:** the **dotted/halftone "B"** — an arc of gold-gradient dots. It is the single hero mark; never redraw it, always use the SVGs in `assets/`. It doubles as a background watermark and a loading/"thinking" motif (dots can animate in sequence).
- **UI icons:** the brand has **no custom icon font**. The system standardizes on **[Lucide](https://lucide.dev)** — thin (1.5–2px), rounded-join, outline icons whose calm geometry matches the premium-zen mood. Loaded from CDN in the UI kits. *(Documented substitution — swap if the team adopts a house set. Full vocabulary in `ICONOGRAPHY.md`.)*
- **Stroke & style:** outline only, consistent 1.75px stroke, 24px grid, currentColor (so they inherit `--fg-*` or gold). Avoid filled/duotone icons except tiny status dots.
- **No emoji, no unicode glyphs** used as icons in brand/product surfaces. Status uses small colored dots or Lucide marks, not 🔴/✅.
- Gold is used on icons only for **active/brand** states; default icons are `--fg-muted`/`--fg-subtle`.

---

## 5 · FILE INDEX  *(manifest)*

**Root**
- `README.md` — this file (context, voice, visual foundations, iconography, index)
- `SKILL.md` — Agent-Skill manifest so this system is usable in Claude Code
- `styles.css` — global entry: reset, semantic type, brand utilities (imports tokens)
- `colors_and_type.css` — all design tokens (color, type, spacing, radii, shadow, motion) + `@font-face`
- `ICONOGRAPHY.md` — icon approach, Lucide vocabulary, the dotted-B motif

**`fonts/`** — self-hosted **Roblox** logotype substitute (Regular / Light / Bold / Black + Outline cut).

**`assets/`** — brand SVGs, variants each (gold gradient · white · black; `logo-mark-*` = the icon alias used by kits):
- `logo-icon-*.svg` / `logo-mark-*.svg` — the dotted-B icon mark
- `logo-buddha-cognitive-lab-*.svg` — lab wordmark lockup
- `logo-hire-buddha-*.svg` — product wordmark lockup

**`preview/`** — Design-System-tab cards (color, type, spacing, components, brand). Each is a small standalone HTML specimen.

**`ui_kits/`** — high-fidelity, interactive recreations (see each kit's README):
- `marketing/` — Hire Buddha marketing site (hero + sections), interactive, with a Tweaks panel for hero direction variations
- `app/` — Hire Buddha product app (workforce console / dashboard)
- `docs/` — Buddha Cognitive Lab docs & blog

---

## 6 · CAVEATS  *(read me)*

- **Fonts are substitutes.** The wordmark is custom and was delivered as outlines only. **Roblox** (self-hosted, logotype), **Space Grotesk** (display), **Hanken Grotesk** (body) and **JetBrains Mono** (mono) are the closest available matches. The Roblox face in particular is a visual stand-in for prototyping only. Please share the real font files to finalize.
- **Icons are a documented substitution** — **Lucide**, chosen to match the stroke weight and calm geometry. Swap if you have a house set.
- **Business card PDF** would not composite its vector artwork in any available renderer, so card-specific colors/contact lines could not be read. The logos fully define the brand; card layout in `preview/` is reconstructed from the logos + tagline + website.
- **No product codebase or Figma** was provided. The UI kits are a brand-consistent *interpretation* of the described product, not a 1:1 recreation. They are built to be refined against the real product.
