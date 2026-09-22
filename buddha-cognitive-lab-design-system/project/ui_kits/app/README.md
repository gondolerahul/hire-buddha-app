# UI Kit — Hire Buddha Product App (Workforce Console)

The logged-in product surface: a calm console for managing your **autonomous workforce** of Buddhas — see who's employed, what they're doing, what needs you, and design new ones.

## Run
Open `index.html`. React + Babel + Lucide from CDN; tokens from `../../colors_and_type.css`.

## Files
- `index.html` — entry (`data-theme`, `data-accent` on `<html>`).
- `app.css` — all console styles (shell, sidebar, KPIs, Buddha cards, detail, activity, inbox, design drawer).
- `app-components.jsx` — data (`WORKFORCE, ACTIVITY, INBOX, MODELS, ALL_TOOLS`) + `Icon, Sidebar, Topbar, KPIs, BuddhaCard, WorkforceView`.
- `app-views.jsx` — `AgentDetail, ActivityView, InboxView, SimpleView, DesignDrawer`.
- `app-main.jsx` — `App` state machine + mount + Tweaks.
- `tweaks-panel.jsx` — Tweaks shell.

## Screens & interactions
- **Workforce** (default) — KPI row + grid of employed Buddhas with live status (running / idle / paused / needs you). Filter `All · Active · Attention`. Click a card → detail.
- **Agent detail** — live activity timeline, weekly sparkline + stats, connected tools. **Pause/Resume** updates status live.
- **Activity** — a unified feed across the workforce.
- **Inbox** — items needing a human decision; **Approve / Dismiss** to clear (reaches "inbox zero").
- **Hire a Buddha** (sidebar / topbar / hire tile) opens the **Design drawer** — name, goal, tools, model → employ (success state).
- **Tools / Models / Settings** — light placeholder views.

## Tweaks
- **Theme → Surface:** `dark` · `light`.
- **Accent → Gold style:** `solid` · `metallic`.

## Notes
Cosmetic recreation; state is in-memory and resets on reload. Data is illustrative (workspace "Northwind Co.").
