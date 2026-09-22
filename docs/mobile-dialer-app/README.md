# HireBuddha Mobile Dialer App — Development Docs

> **Status:** In development. [ADR-001](03-adr-001-lead-identification.md) **Accepted** 2026-09-17; product decisions D1–D4 recorded below.
> **Created:** 2026-09-17
> **Owner:** HireBuddha engineering

## What we are building

An Android app for tenant users and tenant admins that:

1. Logs in with existing HireBuddha credentials.
2. Creates a campaign from an uploaded `.csv` / `.xlsx` lead list.
3. Validates the list server-side and lets the user run the campaign.
4. For each lead, uses **the rep's own phone** to call the lead, calls the tenant's AI-agent number (DID), and **merges both into a carrier conference** so the AI agent talks to the lead with the rep on the line.
5. Shows call analytics in the app **and** in the existing web frontend.

## The core problem

When the rep's phone calls the tenant DID, the AI agent sees an **inbound call from the rep's mobile number**, not from the lead. The existing system identifies the lead in campaigns through Smartflo's `custom_identifier` (see [12 — Voice §8.1](../current/12-voice-and-telephony.md#81-outbound--click-to-call)), and that only works when the backend places the call. Without extra work, the AI has no name, no CSV row, and no campaign context, and the transcript can't be linked to a lead.

[02 — Lead identification options](02-lead-identification-options.md) compares ten approaches. [ADR-001](03-adr-001-lead-identification.md) records the recommendation.

## TL;DR of the recommendation

**Layered identification with gated AI start:**

1. **Call intent + caller-number match (primary).** Before dialing, the app registers a short-lived *call attempt* with the backend. When the call reaches the DID, the backend matches the caller's number (captured once when the device is verified) to the open attempt.
2. **DTMF token (confirmation and fallback).** Once the AI leg connects, and before the lead is merged in, the app sends a short keypad code such as `*4821#`. Smartflo forwards it as a `dtmf` event. It confirms the match, and settles it when caller ID is missing or ambiguous.
3. **Gated start.** The backend holds off starting the speech model until the lead is identified, or until a timeout, so the existing contact-data injection works unchanged.
4. **AI-first dial order (recommended default).** The app connects the AI leg first, puts it on hold, dials the lead, and merges when the lead answers. The lead never waits on hold during the 5–27 s AI setup.

**Fallback architecture** if compliance or carrier spikes fail: the server-side bridge (Option H). The backend dials rep, lead and AI through Smartflo using a compliant 140/1600-series number, and identification is solved trivially.

## Reading order

| # | Document | Read if you are… |
|---|----------|------------------|
| 01 | [Requirements & scope](01-requirements-and-scope.md) | everyone |
| 02 | [Lead identification — options analysis](02-lead-identification-options.md) | deciding / reviewing the approach |
| 03 | [ADR-001: Lead identification](03-adr-001-lead-identification.md) | everyone — the decision |
| 04 | [System architecture & call flows](04-system-architecture.md) | backend + Android devs |
| 05 | [Android app design](05-android-app-design.md) | Android devs |
| 06 | [Backend changes & API contract](06-backend-changes-and-api.md) | backend devs, Android devs (API) |
| 07 | [Analytics (web + mobile)](07-analytics.md) | backend + frontend + Android devs |
| 08 | [Risks, compliance & validation spikes](08-risks-compliance-and-spikes.md) | product, legal, tech lead — **before build starts** |
| 09 | [Delivery plan, epics & acceptance criteria](09-delivery-plan.md) | tech lead, PM |
| 10 | [Implementation status & deployment runbook](10-implementation-and-deployment.md) | anyone deploying or picking up the code |
| 11 | [UX review & visual design](11-ux-and-visual-design.md) | product, design, Android devs — includes the [high-fidelity mockups](wireframes/index.html) |

## Product decisions (2026-09-17)

| # | Question | Decision |
|---|----------|----------|
| D1 | May reps call campaign leads from personal 10-digit SIMs (TRAI TCCCPR 2025)? | **Yes** — confirmed by product. In-app guardrails in [08 §1.1](08-risks-compliance-and-spikes.md#11-trai-tcccpr--commercial-calls-from-10-digit-numbers--blocking) remain. |
| D2 | Dial order | **AI-first only.** Lead-first is not built in v1. |
| D3 | Distribution | **Private only, entirely outside the Play Store** (signed APK sideloaded / MDM). No public release. |
| D4 | Rep audio after the merge | **Auto-muted by default**, with an Unmute control the rep can use to speak. |

## Related existing docs

- [12 — Voice, telephony & messaging](../current/12-voice-and-telephony.md) — the audio pipeline, Smartflo integration, and campaign dialer this app builds on.
- [04 — Auth, RBAC & tenancy](../current/04-auth-rbac-tenancy.md) — roles and JWT flow the app reuses.
- [13 — Gateway & realtime](../current/13-gateway-and-realtime.md) — where the WebSocket handlers run.
