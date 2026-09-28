# Intelligence, experience, and scale

These capabilities improve the same business platform rather than define a competing product. Basic versioning, permissions, cost control and quality checks already belong in the foundation; advanced optimization does not postpone those essentials. Specific model/provider names in the outlines are research candidates, not endorsements or claims of current availability.

## E31 — Model routing and multimodal work

**Outcome:** an operator can choose an eligible model or use evaluated automatic selection without losing quality, policy or cost control. **Baseline:** vendor adapters and static task defaults exist; dynamic routing and unified async media are new. **Sources:** RF §3/§6.4/§8; RT §§3–5; LP/TL defects. **Dependencies:** E01/E02/E04/E05/E08/E12; E32 for learned preferences.

### E31-F01 — Model policy, selection and fallback

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E31-S01 | As an administrator, I can restrict models by required capability and data policy. | Registry exposes supported modalities/context/tools and approved usage policy; tenant constraints filter before selection; pinning an ineligible/unavailable model produces an explicit failure or configured eligible fallback; no fallback bypasses data restrictions. | H2 |
| E31-S02 | As an owner, I can choose Auto and understand its quality/cost tradeoff. | Routing considers task class, modality, context, latency, cost ceiling and measured performance; decision and realized cost are attributed; no eligible model yields a visible blocked/degraded state; routing is tested against the current static baseline before use. | H5 |

### E31-F02 — Reliable provider and media jobs

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E31-S03 | As an operator, I can recover from provider failures without duplicated business effects. | Bounded timeouts/retries distinguish model generation from executed tools; fallback retains context and does not repeat confirmed effects; cancellation settles known usage; provider failures and tool-schema incompatibility have actionable outcomes. | H2 |
| E31-S04 | As a content author, I can request media and follow its progress without blocking other work. | Image/video/edit/audio jobs expose queued/running/completed/failed/cancelled states, preview, artifact and attributed cost; asynchronous provider completion is verified; unsupported options fail clearly; retries do not charge or publish duplicate outputs accidentally. | H3 |

### E31-F03 — Evaluation and modality quality

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E31-S05 | As a quality owner, I can admit or retire a model based on relevant tasks. | Independent task cohorts test quality, tool/schema accuracy, cost, latency and policy compliance; changed model versions require regression evidence; rollback and affected-workflow reporting exist; benchmark scores alone cannot enable production use. | H5 |
| E31-S06 | As a voice or media owner, I can select a validated provider for a supported use case. | Compare actual language, interruption, tool, latency and artifact requirements; quality thresholds are agreed per use case; a mid-call failure follows a tested transfer/closure plan rather than assuming transparent voice failover; new providers need capability-specific acceptance. | H5 |

### E31-F04 — Required provider and media catalog

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E31-S07 | As an administrator, I can enable the required text-model providers. | Adapters and capability profiles are validated for Gemini, Claude, OpenAI, GLM, Qwen and Kimi; credentials are tenant-scoped; model/version, region, modality and data-policy constraints are explicit; an unavailable provider fails clearly and cannot be selected by implication. | H2 |
| E31-S08 | As a content owner, I can create video with the supported providers. | Veo, Seedance and Wan are represented as asynchronous video capabilities with provider status, cancellation, policy checks, usage attribution, artifact persistence and retry/duplicate-publication protection. | H3 |
| E31-S09 | As a content owner, I can create images with the supported providers. | Gemini Image, GPT Image, Qwen Image and Kling expose capability-specific options, safety checks, previews, artifacts, cost attribution and deterministic failure handling; unsupported combinations are rejected before spend. | H3 |
| E31-S10 | As a platform owner, I can replace or add a model without rewriting business workflows. | Provider adapters implement a common contract; version pinning, fallback eligibility, routing decisions and migration/rollback are recorded; intelligent routing is evaluated against the static incumbent before production use. | H5 |

## E32 — Evaluated learning and self-improvement

**Outcome:** changes earn deployment through evidence and remain reversible. **Baseline:** partial memory/reflection/Board machinery with integration defects; complete promotion cycle new. **Sources:** SK §11; GTM §11 evaluation; RF §§5,10,12; RT §§7,9,22; MI/MC/PC defects. **Dependencies:** E02–E05/E08/E12; relevant business metrics. No agent may approve its own modification.

### E32-F01 — Feedback and evaluation evidence

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E32-S01 | As a quality owner, I can relate human feedback and business outcomes to the version that produced them. | Run/Skill/model/policy versions link to success, edits, rejections, complaints, cost and delayed outcomes; missing labels remain unknown; consent/access restrictions apply to feedback; metrics can compare equivalent cohorts. | H3 |
| E32-S02 | As a workflow owner, I can assess a candidate before changing the incumbent. | Independent curated and incumbent-golden cases include negative/adversarial scenarios; test-budget exhaustion and skips cannot count as passes; human spot checks complement automated scoring; report includes regression and cost/latency deltas. | H3 |

### E32-F02 — Skill and instruction improvement

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E32-S03 | As a capability owner, I can turn repeated successful work into a reusable Skill proposal. | Candidate links observed patterns and examples, names intended scope and proposed scripts/instructions, checks reuse before creating a duplicate, and passes E08 authoring and E32 evaluation; it remains inactive until promotion is authorized. | H5 |
| E32-S04 | As a workforce owner, I can test and adopt improved instructions or routing preferences. | Proposal names evidence and expected gain; approved canary compares against incumbent under bounded exposure; regressions restrict/roll back automatically under predefined rules; original versions and decisions remain auditable; no guaranteed calendar-based improvement claim. | H5 |

### E32-F03 — Generated-code repair and optimization

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E32-S05 | As a service owner, I can request a missing or repaired capability without allowing live self-modification. | Generated code runs only in the approved isolated runtime; independent tests, permissions, metering and adversarial checks apply; sensitive primitives cannot be rewritten by ordinary tenant Skills; exact diff and impact are presented for independent human approval. | H5 |
| E32-S06 | As an operator, I can promote or roll back a reviewed capability safely. | Promoter is distinct from author/proposer; active-version change is atomic and distributed workers converge; in-flight pinned runs have explicit handling; canary failure disables affected effects and restores a known version; rollback cannot undo real-world effects and instead raises reconciliation tasks. | H5 |

## E33 — Generative and adaptive experience

**Outcome:** a new frontend helps people operate their business through appropriate conversational and structured interfaces. **Baseline:** new; existing frontend must remain usable in earlier releases. **Sources:** owner-confirmed D05; RF §11/RT §8. **Dependencies:** the APIs and authorization of the supported capabilities, E10's account-manager flow, E06 schema metadata. Design Gate must precede implementation.

### E33-F01 — Dedicated Design Gate

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E33-S01 | As a product owner, I can approve a distinctive, complete experience direction before development. | Design/brainstorming deliverables include owner/operator/reviewer/admin journeys, information architecture, interaction prototypes, visual language, accessibility, mobile behavior and failure states; review tests realistic work and records decisions; the new frontend's build does not start before explicit design acceptance. | H5 |
| E33-S02 | As a reviewer or operator, I can understand how generated views preserve control. | Prototypes demonstrate record detail/edit, activity feeds, approvals, budgets, workflow configuration and Pragya handoff; consequential actions have stable discoverable controls; unsupported generation has a usable fallback; research validates comprehension, not only visual appearance. | H5 |

### E33-F02 — Controlled rendering and migration

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E33-S03 | As a user, I can receive a task-appropriate view and keep my preferred arrangement. | Generated manifests choose from approved components and validated bindings; backend authorization governs every data/action request; no arbitrary executable UI or extra access is granted; preferences are editable/resettable; stale/incompatible schema produces a useful recovery state. | H5 |
| E33-S04 | As an existing user, I can move to the new frontend without losing essential workflows. | Parity checklist covers authentication, records, execution, artifacts, approvals, integrations, budgets and account administration; migration is staged with telemetry and rollback; current UI remains available until replacements pass; accessibility and task success are measured. | H5 |

## E34 — Product packaging and organizational scale

**Outcome:** a company can adopt useful workflows incrementally and expand organizational scope safely. **Baseline:** tenant/partner hierarchy exists; modular packaging and business-unit governance new. **Sources:** GTM tenant-zero/commercial questions; useful adoption/scale needs from BP; owner D01 rejects inherited bundle/Loop counts. **Dependencies:** E01/E04/E06/E09/E12 and the capabilities actually packaged.

### E34-F01 — Capability-based onboarding and commercial readiness

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E34-S01 | As a buyer, I can understand exactly which outcomes a package supports and what it needs. | Package lists supported workflows, integrations, required human roles, autonomy, limitations and usage estimates; no fixed count of agents is a value promise; activation checks prerequisites and creates only needed configurations; failed setup has a recoverable state. | H3 |
| E34-S02 | As a commercial owner, I can price and support a package using measured economics. | Tenant-zero evidence includes actual workload, outcomes, variable cost, idle storage cost, reviewer effort and support burden; commercial model/free allowance is explicitly chosen under O04; plan changes preserve entitlement and records; no invented per-seat/per-outcome price is treated as approved. | H3 |

### E34-F02 — Business units and partner administration

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E34-S03 | As a group owner, I can manage business units with different budgets, policies and data access. | Parent visibility is explicit; approved policies inherit downward, aggregate metrics upward, and no sibling data is shared by default; model/residency requirements are actually satisfied by storage/processing placement; separate legal entities/currencies are not merged into misleading totals. | H6 |
| E34-S04 | As a partner administrator, I can support assigned businesses without crossing their boundaries. | Assignment and delegated roles determine access; pricing/branding privileges are bounded; support actions have audit attribution and time-limited access where applicable; tenant offboarding revokes delegation and preserves export rights. | H4 |

## E35 — BabyBuddha and OmniBuddha research

**Outcome:** in-house models may reduce cost or improve task quality if evidence supports them. **Baseline:** research aspiration, not shipped capability or a blocker for the business product. **Sources:** RF §3.1/§8.1; RT §§3,5. Retained as a proposed later research option, not an owner-approved investment. **Dependencies:** E31/E32 and explicit data-usage permission. Gate H6 is an investment decision, not a promised launch.

### E35-F01 — Permitted training and comparative research

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E35-S01 | As a data owner, I can choose whether eligible traces may be used in model development. | Explicit opt-in and permitted purpose/data categories are recorded; tenant secrets/PII restrictions and withdrawal apply to future collection; data lineage and retention are reviewable; operational memory is not treated as implied training consent. | H6 |
| E35-S02 | As a research sponsor, I can decide whether post-training an open-weight model is worthwhile. | Document licensing/serving constraints, approved dataset, incumbent baselines, task cohorts and full cost; compare tool-use/reasoning or multilingual speech quality as appropriate; decide continue/stop using evidence rather than the model's brand name. | H6 |

### E35-F02 — Conditional admission to product

| Story | User need | Acceptance criteria | Gate |
|---|---|---|---|
| E35-S03 | As a model owner, I can propose BabyBuddha for eligible text/tool workloads. | Fast/reasoning profiles pass independent quality, safety, tool reliability, latency and cost gates against the incumbent; limited canary and eligible fallback exist; absent evidence leaves current providers as default. | H6 |
| E35-S04 | As a voice owner, I can propose OmniBuddha for a validated speech workload. | Tests cover supported languages/code-switching, interruption, tool calls, consent handling, latency and funded safe closure; a failed call has tested handoff/termination behavior; production admission and rollback use E31/E32 controls. | H6 |
