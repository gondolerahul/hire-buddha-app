---
name: buddha-cognitive-lab-design
description: Use this skill to generate well-branded interfaces and assets for Buddha Cognitive Lab and its product Hire Buddha — for production or throwaway prototypes/mocks/decks. Contains essential design guidelines, colors, type, fonts, logos, and UI-kit components for prototyping toward "digital enlightenment."
user-invocable: true
---

Read the `README.md` file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## What's here
- `README.md` — brand & product context, voice & tone, visual foundations, iconography, and a file index. **Start here.**
- `ICONOGRAPHY.md` — icon approach (Lucide), the dotted-B motif, icon vocabulary.
- `colors_and_type.css` — the single source of truth for tokens (gold/black/white palette, type scale, spacing, radii, shadows) and `@font-face`. Link this (or `styles.css`) in any HTML you build.
- `styles.css` — global entry: reset, semantic typography, brand utilities (buttons, chips, surfaces).
- `fonts/` — the self-hosted **Roblox** logotype substitute.
- `assets/` — brand SVGs (the dotted-B mark + both wordmark lockups), each in gold / white / black.
- `preview/` — small specimen cards for every token group (color, type, spacing, components, brand).
- `ui_kits/` — interactive, high-fidelity recreations: `marketing/` (landing page), `app/` (workforce console), `docs/` (docs & blog). Each has its own README.

## Brand in one breath
Frontier AI lab; product lets anyone design & employ autonomous AI "employees" (Buddhas). Premium, calm, zen-tech. Warm near-black canvas, a single precious gold (`#edab48`, sampled from the logo gradient), angular Roblox logotype + Space Grotesk headings + Hanken Grotesk body + JetBrains Mono. Generous space. Voice: calm, confident, concrete with one philosophical lift. No emoji. Tagline: **"Towards digital enlightenment."**

## ⚠️ Substitutions to flag
The wordmark font is custom and was delivered as outlines only — **Roblox** (logotype), **Space Grotesk** (display), **Hanken Grotesk** (body) are the closest available substitutes; **Lucide** stands in for icons. Tell the user these are placeholders and ask for the real font/icon files when producing anything final.
