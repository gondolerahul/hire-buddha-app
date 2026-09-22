# 11. UX Review & Visual Design

> **Covers:** a screen-by-screen UX audit of the shipped Android app, the redesign that answers it, the added
> functionality, and how the Buddha Cognitive Lab brand becomes a mobile system.
> **Mockups:** [`wireframes/index.html`](wireframes/index.html) — 26 high-fidelity screens, open it in a browser.
> **Created:** 2026-09-21

---

## 1. What this reviews

The audit is against the code on `fresh-main`, not against docs 01–10. Everything below is traceable to a file:

| Area | Source |
|------|--------|
| Screens & navigation | [`ui/MainNavigation.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/MainNavigation.kt), `ui/*/` |
| Run behaviour | [`run/CallOrchestrator.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/run/CallOrchestrator.kt), [`run/RunModels.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/run/RunModels.kt) |
| Theme | [`ui/theme/Theme.kt`](../../mobile/android/app/src/main/java/com/hirebuddha/dialer/ui/theme/Theme.kt) |
| Server-side limits | `MOBILE_CALLING_HOURS_*`, `MOBILE_REP_DAILY_ATTEMPT_CAP` in [10 §3](10-implementation-and-deployment.md#step-2--configuration-backendenv) |
| Brand | [`buddha-cognitive-lab-design-system/`](../../buddha-cognitive-lab-design-system/) |

The app is functionally complete and the state machine is good. The problems are all at the surface: what the rep
is told, when, and how much they can act on it.

---

## 2. Findings

Ordered by how much they cost a real rep on a real shift.

### 2.1 Blocking — the rep cannot do something the design promises

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F1 | **Skip is unreachable.** `UserCommand.SKIP` exists and the orchestrator handles it, but no composable ever sends it. FR-E7 lists skip as required. | `RunModels.kt:42`; `RunScreen.kt:106` renders `InCallControls` only when `s.step == Step.IN_CONVERSATION`; nothing sends `SKIP` | Skip lives on every run state, screens 14–16 |
| F2 | **No controls before the merge.** Between `CONNECTING_AI` and `IN_CONVERSATION` — 20–60 s of every lead — the screen has a stepper and nothing else. If the AI leg hangs or the lead rings out, the rep can only wait for a timeout. | `RunScreen.kt:106`, `CallOrchestrator.kt:347` | Skip / Cancel call / Stop run present from the first state |
| F3 | **Pause and Stop are weaker than they look.** The header offers both, then a grey line says they take effect after the current call. A rep in a hurry taps Stop and keeps talking to a lead. | `RunScreen.kt:146` | Pause is an icon in the run app bar; a full Paused screen (19) makes the state unambiguous |

### 2.2 High — the rep is surprised by something the system already knew

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F4 | **Calling hours and the 150/day cap are invisible** until the server refuses a lease mid-run. Both are configured and enforced today. | `.env` `MOBILE_CALLING_HOURS_START/END`, `MOBILE_REP_DAILY_ATTEMPT_CAP=150` | Introduced once on screen 06, live on 07 and 13 |
| F5 | **No pre-flight.** Battery saver, a lost dialer role, a removed SIM, an agent without credits — each is discovered as a failed call. `DialerRole.isHeld` is already checked, just not before a run. | `OnboardingScreen.kt:recheck()`; docs 05 §3 "detect this in `onResume` and on run start" | Screen 13 |
| F6 | **Verification is a 40-second black box.** Three DTMF rounds plus a 20 s caller-ID tail, reported through one mutable `status` string. This is the step most likely to fail on a new carrier, and the hardest to debug from a support call. | `OnboardingScreen.kt:112–184` | Screen 05 shows the rounds and the fallback |
| F7 | **The unidentified-lead dialog has a hidden 15 s timer** that auto-skips. The dialog says nothing about it. | `OrchestratorConfig.mergeDecisionTimeoutMs = 15_000` | Screen 17 shows the countdown and its default |
| F8 | **Identification success is never shown at a useful moment.** It appears as ` · identified via cli` appended to a completed step label. | `RunScreen.kt:169` | Screen 15 leads with it, in words |

### 2.3 Medium — the work is harder than it needs to be

| # | Finding | Fix |
|---|---------|-----|
| F9 | **The rep's own read of the call is never captured.** Disposition comes only from the model. The one human who heard the conversation is not asked. | Wrap-up sheet, screen 18 |
| F10 | **No live transcript**, although the gateway streams turns and the app already holds a push socket. The rep cannot tell when to unmute. | Screen 16 |
| F11 | **Lead context is truncated to four fields** with no way to see the rest — `fields.entries.take(4)`. | Screen 15 shows the full set, framed as what the agent knows |
| F12 | **The campaign list is the home screen.** There is no answer to "what should I do now?" | New Today tab, screen 07 |
| F13 | **A run ends by popping the back stack.** No summary, no next step. | Screen 20 |
| F14 | **Empty state and error state are the same composable.** "No campaigns are assigned to you yet" is rendered by `ErrorState`, centred in the viewport, indistinguishable from a network failure. | Distinct empty / error / blocked treatments |
| F15 | **The update prompt is a permanent `Snackbar`** in the Campaigns scaffold, so it sits over the list indefinitely and disappears on other tabs. Private APK distribution makes updating important. | Settings row + notification, screens 23 and 26 |
| F16 | **No search or lead detail** on a 320-row campaign. | Search in the app bar, screen 09 |

### 2.4 Brand

| # | Finding |
|---|---------|
| F17 | **The theme is stock Material 3 indigo** (`Indigo = 0xFF3D5AFE`) with a light default. Nothing in the app is Hire Buddha or Buddha Cognitive Lab. |
| F18 | **There is no splash.** The token check renders a blank Compose surface. For an APK a rep sideloads from a link, this is the entire first impression. |
| F19 | **Status colours are web-safe primaries** (`0xFF1B8A5A`, `0xFFC62828`) rather than the brand's deliberately desaturated sage and terracotta. |

---

## 3. What the redesign adds

Nine screens have no counterpart in the app today. They are marked in the mockups.

| Screen | Addition | Why it earns its place |
|--------|----------|------------------------|
| 01 | **Splash** | Both brands, correct hierarchy; covers the refresh-token check that already happens |
| 05 | **Live verification** | Turns the highest-risk onboarding step into something a rep and support can both read |
| 06 | **Ready** | The one place to introduce calling hours and the daily cap before they bite |
| 07 | **Today** | Cap, window, today's numbers, the paused run, callbacks due |
| 13 | **Pre-flight** | Six checks that already exist, moved from failure time to before the run |
| 16 | **Live transcript** | The reason to keep the phone in hand instead of in a pocket |
| 18 | **Wrap-up** | Rep disposition, note, callback — inside the gap that already exists |
| 20 | **Run summary** | Closes the loop; the screenshot moment |
| 26 | **Notification design** | The foreground service is the app for minutes at a time (FR-E8) |

### 3.1 New functionality worth discussing

These change the backend contract and are the main thing to brainstorm:

1. **Rep disposition** — a `disposition_source` (`ai` \| `rep`) on `campaign_calls`, with the rep's value winning in analytics. Cheapest large gain in data quality.
2. **Callbacks** — "call back at 16:00" currently has nowhere to go. Needs a `callback_at` column, a queue, and a local notification. Today's version of this is the rep writing on paper.
3. **Do-not-call from the run screen** — the DNC exclusion list exists server-side; there is no way to add to it from the phone, which is where the request actually arrives. This is also a TCCCPR posture improvement (see [08 §1.1](08-risks-compliance-and-spikes.md)).
4. **Headset recommendation** — the rep is auto-muted for most of a call (D4). Speakerphone in a noisy office is the worst case for an unmute decision.
5. **Battery-optimisation exemption** — `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, prompted once at setup. The commonest cause of a run dying in the background on Xiaomi and OnePlus.
6. **Sample sheet + upload reuse** — the server already keeps uploads 24 h.
7. **Send diagnostics** — `mobile_client_logs` already receives everything; a button makes it usable during a pilot.

### 3.2 Deliberately not added

- **Contacts, call history, voicemail.** Holding `ROLE_DIALER` does not oblige a full phone replacement, and doc 05 §3 is right to keep the dialer minimal.
- **In-app agent editing, billing, number purchase.** Non-goals in 01 §5; nothing here changes that.
- **A light theme.** Sales reps work outdoors. A single high-contrast dark theme with a brightness-aware boost is a better answer than two half-tuned themes — see §5.4.

---

## 4. Information architecture

```
Splash ──┬── Login ── Role gate ── Setup (3 steps) ── Verify ── Ready
         └── (session) ─────────────────────────────────────┘
                                   │
                        ┌──────────┴──────────┐
                        │      Home tabs      │
                        └──────────┬──────────┘
        ┌────────────┬─────────────┼─────────────┬──────────────┐
      Today      Campaigns      Insights      Settings
        │            │
        │            ├── Create (1 list → 2 report → 3 who calls)
        │            └── Campaign detail ── Lead list ── Call detail
        │                      │
        └──────────────────────┴── Pre-flight ── Run ── Wrap-up ── Run summary
```

Two changes from `MainNavigation.kt`:

- **Four tabs instead of three.** Today is added; Campaigns keeps the FAB.
- **The run is a destination, not a tab.** It is reachable from Today, the Campaigns list bar, campaign detail and
  the notification, and it always opens the same single live run. This already matches `RunController` being a
  singleton — the UI just has to stop treating it as a page you navigate away from.

---

## 5. Visual system

The design system is built for a wide, calm desktop canvas. Three things have to change on a 412 dp screen.

### 5.1 What carries over unchanged

| Token | Value | Use on mobile |
|-------|-------|---------------|
| `--bg` | `#0a0908` | Every screen. No light default. |
| `--accent` | `#edab48` | Primary action, active tab, progress, eyebrows, live states |
| `--surface` → `--surface-3` | `#141210` → `#241f1b` | Cards, inputs, chips — depth from steps, not colour |
| `--positive` / `--negative` | `#7bb487` / `#d4664f` | Replaces the Material greens and reds in `StatusColors` |
| `--r-lg` / `--r-2xl` / `--r-pill` | 16 / 30 / 999 | Cards / sheets & docks / buttons & chips |
| Type | Space Grotesk · Hanken Grotesk · JetBrains Mono | Headings & figures · body & UI · timers, numbers, IDs |

### 5.2 What changes for mobile

- **Space is compressed, not abandoned.** The brand's `--s-9`/`--s-10` section padding becomes a 20 px gutter and a
  20–24 px rhythm between blocks. Air is spent on the one thing each screen is for.
- **A mobile type ramp.** Screen title 27/1.14, section 21, body 14/1.55, caption 12.5, micro 11, eyebrow 10 mono.
  The desktop `--text-6xl`/`5xl` steps are not used; big figures cap at 34.
- **Touch first.** 48 px minimum target, 56 px for primary run actions, 66 px keypad rows. Every destructive control
  is at least one target away from a constructive one.
- **Gold stays precious.** At most one gold surface per screen. It marks the live thing: the primary action, the
  active lead, the running timer. The metallic gradient is reserved for exactly two buttons — *Start the run* and
  *Resume* — so "the call is about to happen" has a look of its own.

### 5.3 Liquid glass, used sparingly

Only where content moves underneath it: the bottom tab bar, the in-call control dock, the sticky Continue bar in
the create flow, and the notification actions. Flat surfaces remain the default. Under
`prefers-reduced-transparency` these fall back to `--surface` with a hairline, exactly as `styles.css` specifies.

### 5.4 Field conditions

This app is used standing up, outdoors, one-handed, often mid-conversation.

- **Sunlight, and a correction to the neutrals.** The desktop ramp does not survive a phone held outdoors.
  Measured against `--surface` `#141210`: `--fg-subtle` `#7c746b` is **4.06:1** and `--fg-faint` `#544d46` is
  **2.25:1**. Both fail WCAG AA for the 11–12.5 px sizes they would carry here. The mockups shift the two lower
  steps one notch lighter — `--fg-subtle` → `#968d82` (5.72:1), `--fg-faint` → `#8b8277` (4.95:1) — and add
  `--fg-disabled` `#544d46` for things that never carry information. The four-level hierarchy is unchanged; only
  the floor moves. Everything else already passes: `--fg` on `--bg` is 17.7:1, `--fg-muted` on `--surface` 8.2:1,
  gold on `--bg` 10.0:1, `--on-accent` on gold 8.2:1, sage 7.8:1, terracotta 5.2:1.
  **This is a proposed amendment to the design system, not a local override** — the same argument applies to any
  small text in the web app.
- **Brightness.** Beyond contrast, a "bright sunlight" toggle that lifts every surface one step
  (`--surface` → `--surface-2`) is a token remap, not a second theme.
- **One hand.** Everything a rep taps during a call sits in the bottom third. The run app bar is informational.
- **Motion.** Fades and 8–16 px rises, `--ease-out`, 120–640 ms. The dotted-B loading motif is the only looping
  animation and it respects `prefers-reduced-motion`.
- **TalkBack.** Run state changes announce as live regions ("Meenal answered, merging"), because a rep may be
  listening rather than looking.

### 5.5 The brand motif

The dotted-B is used three ways, all of them from the SVGs in `assets/` and never redrawn:

1. **Lockups** — Hire Buddha on splash and login; Buddha Cognitive Lab as the signature on splash and settings.
2. **Watermark** — the mark at 5–6 % opacity, bleeding off an edge, on splash, empty states and the run summary.
3. **Loading** — a row of gold dots lighting in sequence. It is the app's only spinner: splash, "connecting your
   Buddha", "sending code", "ringing". One motif for every wait.

---

## 6. Copy

The brand voice ("calm, confident, concrete, with one philosophical lift") maps onto this app better than most:
a rep under pressure wants plain sentences. Rules applied throughout the mockups:

- **Machine states become human sentences.** `WAITING_AI` → "Telling her who she is calling". `merge_failed` →
  "We couldn't join the calls".
- **The agent has a name and a pronoun.** "Ananya is joining", not "Connecting AI agent". It is how reps already
  talk about them, and it matches the design system's "your support Buddha" vocabulary.
- **Consequences, not codes.** "Ananya will introduce herself but won't know Arjun's name, locality or budget" —
  not "lead unidentified".
- **Sentence case everywhere.** Uppercase only for mono eyebrows. No emoji.
- **One lift, once.** The run summary gets "108 calls, 5 hours of your voice saved." Nothing else reaches for it.

---

## 7. Open questions for the brainstorm

1. **Does the wrap-up sheet fit the shift?** It adds ~4 s per call inside a 5 s gap. Always on, on for interested
   calls only, or off by default with a swipe-up?
2. **Live transcript** — worth the data and the battery? It is the single biggest change to the run screen.
3. **Callbacks** need a backend contract. In scope for v1, or a v1.1 that ships after the pilot?
4. **Four tabs or three?** Today is genuinely useful, but it is also a second place campaigns appear.
5. **Do-not-call from the phone** — product and compliance both have a view here.
6. **Assisted mode** (doc 05 §3, not built) has no screens yet. Design it now, or wait for spike S3 to say whether
   reps actually refuse the dialer role?
7. **The 412 dp target.** Most reps will be on cheaper 360 dp phones. Everything here reflows, but the run screen
   dock and the wrap-up grid are the two places to check first.

---

## 8. What shipped

All of it, on `fresh-main`. 38 Android unit tests pass (15 existing orchestrator tests
unchanged, 8 new ones covering Skip, wrap-up and the live transcript); the backend's 105
unit tests pass.

| Layer | Change |
|-------|--------|
| Tokens & type | `ui/theme/Tokens.kt`, `Type.kt`, `Theme.kt` — every Material 3 role mapped onto a brand token, dark-only, Space Grotesk / Hanken Grotesk / JetBrains Mono bundled in `res/font` |
| Brand assets | `ic_logo_mark`, `ic_logo_hire_buddha`, `ic_logo_bcl` generated from the design system SVGs; system splash (`Theme.HireBuddha.Splash`) hands off to the in-app one |
| Icons | 67 Lucide-style drawables generated from the mockups' own symbol set, so app and mockups cannot drift |
| Components | `ui/common/Brand.kt` (primitives) and `Components.kt` (composites) |
| Screens | All 26, across `splash/`, `login/`, `onboarding/`, `home/`, `campaigns/`, `run/`, `calls/`, `analytics/`, `settings/`, `telecom/` |
| Orchestrator | Skip honoured in every phase; live transcript collected; wrap-up state; a gap the rep can hold open |
| Backend | `mobile_dialer_002.sql`; `GET /mobile/preflight`, `GET /mobile/callbacks`, `PATCH /mobile/campaign-calls/{id}/disposition`; `attempt.transcript` push from the gateway |

### Decisions worth knowing

- **`rep_disposition` is a separate column from `disposition`.** The rep's answer also
  writes `disposition` so every existing report picks it up, but it is preserved on its
  own so a later LLM or voicemail-detection pass can never silently overwrite what the
  human said. The LLM path in `websocket_handler.py` already only fills `disposition`
  when it is NULL, so a rep who answers first wins there too — no change needed to the
  hot call path.
- **Do-not-call needs no new table.** The leasing query already excludes any phone with a
  `do_not_call` disposition in the same company, so the wrap-up's DNC button is the same
  endpoint as every other disposition. A partial index was added for that subquery,
  which had been a sequential scan.
- **The neutral ramp was lightened** (`--fg-subtle` → `#968d82`, `--fg-faint` → `#8b8277`)
  as §5.4 argues. This is a proposed amendment to the design system, not a local override.
- **A wrap-up minimum window.** A rep who sets the gap to zero would otherwise see the
  sheet appear and vanish in the same frame, so it holds for at least 5 s when there is
  something to answer. Found by a test, not by inspection.
- **BCL lockup is flat gold, not gradient.** 86 gradients for dots a few pixels wide is
  pure cost; it is indistinguishable at the size the lockup is ever drawn.
- **New endpoints degrade to "hide the feature".** The APK is sideloaded, so app and
  server versions drift by design; `preflight` returning 404 falls back to the checks the
  phone can make on its own.

### Field fixes, 2026-09-22 (first install on a real handset)

Three things came back from the first real test on a Samsung SM-A356E. All three were
the same shape: a state the server understood and the app could not show or escape.

| Reported | Root cause | Fix |
|----------|-----------|-----|
| "The call is not initiating." | Testing at 02:27 IST. The lease endpoint refused every lead with `outside_calling_hours` (window is 09:00–21:00), so the run started and paused on its first lead. The pre-flight *detected* it and still let the run start, because at that point every check was advisory. | Pre-flight now separates a **warning** (battery saver — the rep may know better) from a **blocker** (calling window, cap, credits, DID, unverified phone — the server refuses *every* lease). Blockers disable Start and name the reason. |
| "No way to stop a running campaign." | Stop only existed on the pre-merge panes. Once a call connected the only controls were Mute / Take over / **End call**, and End call ends the lead, not the run. | A run-options sheet on the run app bar, reachable in every state, offering Skip, Pause, Stop after this call, and Hang up and stop now. |
| "Two campaigns running, no calls, and resuming says another campaign is already running." | The live run is held in memory only. A crash, a force-stop or a reinstall (which mints a new device row) strands it: the campaign reads "running" forever and `start_run` refuses the device with `device_busy`, with nothing in the UI able to clear it. Three such runs were found on the live DB, two from reinstalled devices. | Three layers: `GET /mobile/runs/active` so the app can always find a stranded run; a recovery card on Today and on campaign detail that stops it; and `device_busy` now names the blocking run so the error becomes "stop it and start this one". Housekeeping also closes runs with no attempt for 6 h and completes campaigns with nothing left to call. |

**Operational note.** `MOBILE_CALLING_HOURS_START/END` in `backend/.env` is a compliance
setting (TRAI), not a convenience one, so it was left at 09:00–21:00. Testing outside
those hours needs it widened deliberately and the API restarted — the app will otherwise
correctly refuse to start.

### Still open

- Assisted mode (docs 05 §3) has no screens — deliberately, pending spike S3.
- Callbacks have no reminder notification yet; they surface on Today and jump the queue
  when due.
- `DISPOSITION_PRIORITY` in `campaign_models.py` has no rank for `callback`, `wrong_number`
  or `do_not_call`, so those sort last in the *web* report and Excel export. Cosmetic, and
  `do_not_call` already behaved that way.

---

## 9. Build notes

The mockups are HTML; the app is Compose. The mapping is direct:

| Mockup | Compose |
|--------|---------|
| `:root` tokens | A `HireBuddhaTheme` with a `darkColorScheme` (`primary = 0xFFEDAB48`, `background = 0xFF0A0908`, `surface = 0xFF141210`) plus a `LocalBrand` CompositionLocal for the tokens Material 3 has no slot for (gold gradient, glass, eyebrow colour) |
| `--font-display` / `--font-body` / `--font-mono` | Space Grotesk, Hanken Grotesk, JetBrains Mono as `FontFamily`s bundled in `res/font`. **Do not ship the Roblox substitute** — the lockups are SVG and need no logotype face. |
| Logos | `assets/logo-hire-buddha-gold.svg`, `logo-buddha-cognitive-lab-gold.svg`, `logo-mark-gold.svg` → vector drawables |
| Icons | Lucide-style, 24 dp grid, 1.75 dp stroke, `currentColor`. Replace `Icons.Filled.*`, which are heavier and off-brand. |
| `.glass` | `Modifier.hazeChild` or a `RenderEffect.createBlurEffect` backdrop (API 31+) with a solid `--surface` fallback below 31 |
| `.sheet` | `ModalBottomSheet` with `shape = RoundedCornerShape(30.dp, 30.dp, 0, 0)` |
| `.dots` | One `InfiniteTransition` driving three alpha animations, gated on `LocalAccessibilityManager` |

Font substitution stands as flagged in the design system README: Space Grotesk, Hanken Grotesk and JetBrains Mono
are stand-ins until the real faces arrive, and Lucide stands in for a house icon set.
