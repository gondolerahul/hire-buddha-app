# UI Kit — Hire Buddha Marketing Site

Interactive, high-fidelity recreation of the **Hire Buddha** marketing landing page. Premium zen-tech: warm near-black, metallic gold accents, the Roblox logotype, and the dotted-B mark as watermark.

## Run
Open `index.html`. React + Babel are loaded from CDN; tokens come from `../../colors_and_type.css`. Lucide provides icons.

## Files
- `index.html` — entry; loads React, Babel, Lucide, then the scripts below.
- `marketing.css` — all kit styles (nav, hero, sections, agent gallery, modal).
- `marketing-components.jsx` — `Nav, Hero, ConsolePreview, HowItWorks, AgentGallery, Closing, Footer, DesignModal`, plus the `AGENTS` data and the `Icon` wrapper.
- `app.jsx` — mounts `App`, wires the reveal-on-scroll animation and the Tweaks panel.
- `tweaks-panel.jsx` — the Tweaks shell + controls.

## Interactions
- **Design your Buddha** (nav, hero, closing) opens the **DesignModal** — name a role, set a goal, toggle tools, pick a model, and "hire" it (success state).
- **Agent cards** in the gallery open the modal pre-filled with that role.
- Scroll reveals sections.

## Tweaks (toolbar → Tweaks)
- **Hero → Direction:** `centered` · `split` (with live console preview) · `mark` (spinning gold medallion).
- **Accent → Gold style:** `solid` · `metallic` (animated specular sweep on CTAs).
- **Theme → Surface:** `dark` · `light` (paper mode).

## Notes
This is a cosmetic recreation, not production code. Copy lives in `marketing-components.jsx`; swap freely. No real backend.
