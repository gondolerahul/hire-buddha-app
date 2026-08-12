# Increment 3 — Pragya v1 — Charter Stub

> **Status:** Stub — deepened just-in-time. A clarifying-questions round with Rahul precedes the full docs.
> **Parent:** [build_roadmap.md](../build_roadmap.md) §4, Increment 3 (L). **Prerequisite:** Increment 2 (the wizard + dashboards Pragya replaces conversationally; SIG for her reporting).

## Goal

The "talk to your account manager" experience, safely authenticated, running a consulting-grade onboarding.

## Scope (from the roadmap)

* **AUTH** — inward-channel authentication (technical §11.3, design done): enrolled channel bindings, T0–T3 command tiers sharing the §20 authority taxonomy, passkey/OTP step-up, out-of-band confirmation for critical commands, Pragya-can't-approve-herself rule.
* **PRAGYA v1** — the **nine-stage engagement flow** (functional §4.3): baseline research → working assumptions → deep ingestion → revised analysis → solution engineering → blueprint finalization → integration → test/deploy → operate. Implemented as conversational orchestration over the same APIs the Inc-2 wizard uses. Stages 1–5 need per-stage scripts/prompts (built here; the protocol closed C8).
* `account_manager_sessions` (+ `auth_level`, `elevated_until`), channel adapters over shipped voice/WhatsApp/email paths.

## Register findings to close here

C4 (autonomy demotion triggers), C6 (KPI metric definitions — Pragya reports them, so they must be defined).

## Known open questions

1. Which channel ships first for Pragya (frontend console vs phone vs WhatsApp)?
2. Passkey/FIDO2 infrastructure choice for step-up (platform-built vs provider).
3. Stage 1–5 scripts: drafted from the Blueprint's discovery protocol — who reviews consulting quality?
