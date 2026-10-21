# Production manual test plan (Phase 14)

> **For:** the owner, testing HireBuddha on Azure production before real businesses use it.
> **Written:** 21 Oct 2026, for the release that the pipeline promotes after `0559689`.
> **Environment:** `https://app.azprod.hirebuddha.com` (screens) and `https://gateway.azprod.hirebuddha.com` (API).
> Today's `app.` / `gateway.` names move to Azure when you switch over from GCP (by hand, decision of 21 Oct).

The plan walks through every product area as each kind of person who uses it: the platform admin
(you), a business (**tenant 0: Buddha Cognitive Lab**), a partner (**Durwankur Technologies**) and
the partner's own client (**Durwankur Demo Client**). Each step says what to do and what you should
see. Write the outcome in the results table at the end (§14); anything marked ✗ is a defect to report
with the time, the screen and what you saw.

---

## 0. Before you start

### 0.1 What is and is not ready

| Area | State in production | In this plan |
|------|--------------------|--------------|
| Gemini (text, reasoning, vision, embeddings, speech, music, Veo video) | Ready (Google federation, no key) | §3–§6 |
| GPT through Microsoft Foundry | You add it (§2.1) | §2.1, §5.3 |
| Claude | Off until you enable it in Vertex AI Model Garden | skip; §2.4 says how to add it later |
| E-mail (sign-up confirmation, password reset, notification mails) | You add `smtp-system` (§2.2) | §2.2, §4.2 |
| Twilio calls and numbers | You add credentials later | §11 (later) |
| Connecting Meta, Google, Microsoft, LinkedIn, X, GitHub accounts | After HireBuddha's provider apps are registered | §9.3 (later) |
| Code sandbox, tenant apps, built-in Git (WS6) | After slice 4 is deployed | §12 (later) |

### 0.2 What you need

* A desktop browser and **three separate browser profiles** (or one normal window, one private window
  and a second browser), so the platform admin, the tenant admin and the partner admin stay signed in
  at the same time without sharing a session.
* The platform admin's password. It exists only in Key Vault:
  Azure portal → Key Vaults → `kv-hb-prod-e7b3` → Secrets → `app-admin-password` → current version → **Show secret value**.
  (Or: `az keyvault secret show --vault-name kv-hb-prod-e7b3 -n app-admin-password --query value -o tsv`.)
  Change it after the first sign-in if you prefer (§1.3).
* Three e-mail addresses you can read, for the people you create (e.g. `owner@buddhalab.in`,
  `admin@durwankur…`, `client-admin@…`). Without SMTP (§2.2) the platform cannot send them mail; you
  set their passwords yourself when you create them.
* Two small files to upload: a PDF or DOCX of a few pages (a policy or price list) and a PNG/JPG (an avatar).

### 0.3 Conventions

* **Platform admin** = `admin@hirebuddha.com` (company *HireBuddha*, role `app_admin`).
* **Tenant admin** = the owner of Buddha Cognitive Lab (role `tenant_admin`).
* **Partner admin** = the owner of Durwankur Technologies (role `partner_admin`).
* **"Working in"** = the company selector at the bottom of the sidebar for platform and partner
  people; a yellow banner says which company's data you are looking at.

---

## 1. Smoke test (platform admin) — 10 minutes

| # | Do | Expect |
|---|----|--------|
| 1.1 | Open `https://gateway.azprod.hirebuddha.com/api/v1/health` | JSON with `"status":"ok"`, `worker.status` `ok` with a worker on `arq:queue`, `children`, `events`, `provisioning`; `models.status` `ok` |
| 1.2 | Open `https://app.azprod.hirebuddha.com` | The sign-in page, padlock valid (Let's Encrypt) |
| 1.3 | Sign in as the platform admin. Optional: Profile → change password | The dashboard; the sidebar shows Platform Hub, Partner Dashboard, AI Workspace, … and **Working in** with "My own company" |
| 1.4 | Admin → **Tenants** (`/admin/tenants`) → *Check health* | One tenant (the HireBuddha company, key `hhhhsdav6b`): `active`, healthy, schema current |
| 1.5 | AI Configuration (`/ai-config`) | Task defaults: text, reasoning, vision → Gemini 4 Argon; goal checks → Gemini 3.5 Flash-Lite; embeddings → text-embedding-005 |

---

## 2. Platform settings (platform admin)

### 2.1 GPT through Microsoft Foundry

System Integrations (`/integrations`) → **Add integration**, once for input tokens and once for output tokens:

| Field | Value |
|-------|-------|
| Service Category | LLM |
| Provider Name | `azure_openai` |
| Model Name | your **deployment name** in Foundry (e.g. `gpt-5-mini`) |
| Service SKU | `<deployment>-in` (input row) / `<deployment>-out` (output row) — unique |
| Component Type | input token / output token |
| Internal Cost / Cost Unit | the model's list price per million tokens (Foundry's price page) / `per_million_tokens` |
| API Key | the Foundry resource's key (Foundry portal → the resource → Keys and Endpoint) |
| Service Metadata | `{"azure_endpoint": "https://<resource>.services.ai.azure.com/", "api_version": "2025-01-01-preview"}` — a classic `https://<resource>.openai.azure.com/` endpoint also works |

**Without a key** (managed identity instead): leave API Key empty, add `"auth": "managed_identity"` to the
metadata, and give the API and worker identities the role on your Foundry resource first —
Azure portal → the Foundry resource → Access control (IAM) → Add role assignment →
**Cognitive Services OpenAI User** → Managed identity → `id-hb-prod-api` and `id-hb-prod-worker`
(and `id-hb-dev-api`, `id-hb-dev-worker` for dev).

| # | Do | Expect |
|---|----|--------|
| 2.1.1 | Save both rows | Both listed, active |
| 2.1.2 | AI Configuration → set *text generation* to the GPT model for a moment, or leave Gemini and choose GPT per agent (§5.3) | Saved |
| 2.1.3 | Test it with an agent (§5.3) | The run's trace shows the GPT model and a cost |

### 2.2 E-mail (`smtp-system`)

System Integrations → **Add integration**: Service SKU `smtp-system`, Provider Name your mail provider
(e.g. `zoho`, `sendgrid`), category the one for e-mail/notifications, API Key = the SMTP password, Service
Metadata `{"smtp_host": "smtp.<provider>.com", "smtp_port": 587, "smtp_user": "<user>", "smtp_from": "HireBuddha <no-reply@hirebuddha.com>"}`.

| # | Do | Expect |
|---|----|--------|
| 2.2.1 | Sign out → *Forgot password* with the platform admin's address | A reset mail arrives within a minute; its link opens `app.azprod…/reset-password` |
| 2.2.2 | Self sign-up (§4.2) | A confirmation mail arrives |

### 2.3 Automation and connector switches

| # | Do | Expect |
|---|----|--------|
| 2.3.1 | Admin → **Platform Automation** (`/admin/automation`) | Every limit "No limit" (decision D47); state Running |
| 2.3.2 | Admin → **Connector approvals** → *Connectors* | The catalog: OAuth connectors "Coming soon", API key / mailbox / MCP available |
| 2.3.3 | Connector approvals → **HireBuddha's provider apps** | Six providers, all "Not yet" (§9.3 later) |

### 2.4 Claude later (when you are ready)

Google Cloud console → Vertex AI → Model Garden → each Claude model → **Enable** (accept Anthropic's terms)
in project `hirebuddha-production`. Then System Integrations → add the Claude rows (provider `anthropic`,
`service_metadata.provider: "vertex"`). No key: the same federation Gemini uses.

---

## 3. Companies and people (platform admin)

### 3.1 Tenant 0 — Buddha Cognitive Lab

| # | Do | Expect |
|---|----|--------|
| 3.1.1 | Platform Hub (`/platform-management`) → Tenants → **Add Tenant**: "Buddha Cognitive Lab", no partner, default daily credits | Created |
| 3.1.2 | Admin → Tenants → refresh within a minute | A new tenant key, status `requested` → `active`; open it: every step `succeeded` (database, migrated, identity, keys, namespace, storage), *data_api* `skipped` |
| 3.1.3 | Platform Hub → Users → **Add User**: the owner's name and e-mail, company Buddha Cognitive Lab, role **tenant_admin**, a password of 12+ characters | Created (admin-created users need no confirmation mail) |
| 3.1.4 | Billing / Wallet: give Buddha Cognitive Lab a starting balance (e.g. $20) | The wallet shows it |

### 3.2 Partner — Durwankur Technologies

| # | Do | Expect |
|---|----|--------|
| 3.2.1 | Platform Hub → Partners → **Add Partner**: "Durwankur Technologies" | Created; Admin → Tenants shows its own database becoming `active` too |
| 3.2.2 | Add User: partner admin, company Durwankur Technologies, role **partner_admin** | Created |

---

## 4. Signing in, sign-up and the workspace

| # | Do | Expect |
|---|----|--------|
| 4.1 | Profile 2: sign in as the Buddha Cognitive Lab owner | Their dashboard; no Platform Hub; no "Working in" selector (they see only their company) |
| 4.2 | (After §2.2) Profile 3: `/register` with a new address | "Check your e-mail"; the mail's link confirms; signing in shows **Setting up your workspace** for under a minute, then the dashboard (its database was made at sign-up) |
| 4.3 | Profile 2: Settings → **Business settings** (`/settings/tenant`) → time zone Asia/Kolkata | Saved; schedules and reports use it |

---

## 5. Agents and runs (tenant admin, Buddha Cognitive Lab)

### 5.1 Build an agent

Entity Library (`/ai/entities`) → **Create Entity** → type AGENT, name "Research Assistant".

| Tab | Do | Expect |
|-----|----|--------|
| Basics | Role, description; upload the avatar image | The avatar shows (served from Blob storage by a signed link) |
| Brain | Instructions ("You research a topic and write a short summary"); model left on the default | — |
| Capabilities | Grant `web_search` (if a search key is configured) or none, and `pdf_generator` | Listed as granted |
| Automation | Leave "Runs from triggers" on | — |
| Records | Tick **Read** and **Create** for Contacts | Read is ticked by itself when you tick Create |
| Safeguards | Max cost $0.50 | — |

Save, set status **ACTIVE**.

### 5.2 Run it

| # | Do | Expect |
|---|----|--------|
| 5.2.1 | Run the agent: "Summarise the benefits of solar rooftops for small offices in India and make a one-page PDF" | The run page shows live steps (planning, model calls, tools) while it runs; it ends COMPLETED |
| 5.2.2 | Open the PDF from the run's artifacts | Downloads; the address is `sthbprode7b3.blob.core.windows.net` with a short-lived signature |
| 5.2.3 | Executions (`/ai/executions`) | The run with its cost; the wallet went down by the billed amount |
| 5.2.4 | Run it again and press **Cancel** while it runs | Status CANCELLED within a few seconds; billed only what it used |
| 5.2.5 | CSAT: thumbs up on the finished run | Saved |

### 5.3 A second model

Create "GPT Writer" with the GPT model of §2.1 chosen on its Brain tab; run "Write a 3-line welcome
message for new clients". **Expect:** COMPLETED; the trace names the GPT deployment.

### 5.4 Approvals (human in the loop)

| # | Do | Expect |
|---|----|--------|
| 5.4.1 | Research Assistant → Safeguards → add a checkpoint **before** the PDF step (or "before any tool") | Saved |
| 5.4.2 | Run it | The run pauses (PAUSED); the bell shows a notification |
| 5.4.3 | Guardian Oversight (`/ai/approvals`) → approve with a note | The run resumes and completes |
| 5.4.4 | Run again and **reject** | The run ends; the reason is in its trace |

### 5.5 Templates

Template Marketplace (`/ai/templates`) → clone a template into Buddha Cognitive Lab → run it.
**Expect:** the clone is your company's own agent; editing it does not change the template.

---

## 6. Knowledge and files (tenant admin)

| # | Do | Expect |
|---|----|--------|
| 6.1 | Knowledge Base (`/knowledge`) → upload the PDF/DOCX, for all agents | Status processing → completed |
| 6.2 | Search a phrase from it | The right passage, with the file name |
| 6.3 | Ask the Research Assistant a question only the document answers | It answers from the document |
| 6.4 | Rename the document, then delete it; ask again | After delete it no longer finds it |
| 6.5 | Artifacts (`/artifacts`) | The PDFs and uploads of this company only; each downloads |
| 6.6 | Memory Trees (`/cortex`) | The agent's and the company's knowledge trees |

---

## 7. Records — the business's own data (tenant admin)

| # | Do | Expect |
|---|----|--------|
| 7.1 | Records (`/records`) | Tabs Accounts, Contacts, Activities, Consents (the base pack) |
| 7.2 | Contacts → New: a name, e-mail, phone, lifecycle "lead" | Saved; open it: **History** shows who created it |
| 7.3 | Edit it in two tabs at once, save both | The second says "this record changed — reload" |
| 7.4 | Records → **Schema** → Propose change: a new table "Product" with fields Name, Stock (integer), Price (money) | A preview of the change; apply → the Product tab appears |
| 7.5 | Add three products, one with Stock 5 | Listed |
| 7.6 | Run an agent with Records access ("Add a contact named Test Lead from Pune") | A new contact, history "by an agent's run" |
| 7.7 | Give an agent **May propose changes** (Records tab) and ask it to "add a City field to contacts" | Guardian Oversight shows the proposal with the agent's reason; approve → the field exists |
| 7.8 | Records → **API keys** → create a key for Contacts read; copy it once | The key is shown once; listed by prefix afterwards; revoke works |
| 7.9 | (Optional) `curl -H "Authorization: Bearer <key>" https://gateway.azprod.hirebuddha.com/data/v1/contact` | JSON list of contacts; after revoke: 401 |
| 7.10 | `https://gateway.azprod.hirebuddha.com/data/.well-known/jwks.json` | One RSA public key (tokens are signed by Key Vault) |

---

## 8. Automation (tenant admin)

| # | Do | Expect |
|---|----|--------|
| 8.1 | Control Room (`/automation`) → New trigger → **On a schedule**: every 5 minutes, run the Research Assistant, input "Write one line of news about AI" | The preview lists the next ten times in Asia/Kolkata |
| 8.2 | Press **Run now** on it | An event in the log with decision "started" and its run |
| 8.3 | Wait for the schedule to fire | One run per 5 minutes; switch the trigger off afterwards |
| 8.4 | New trigger → **When an agent finishes**: when Research Assistant completes, run GPT Writer with "Rewrite: {{ event.data.output }}" | A Research run starts GPT Writer by itself |
| 8.5 | New trigger → **On a schedule, if the records say so**: every hour, if the number of Products where Stock < 10 is more than 0, run an agent "Re-order low stock" | Run now: the decision is "started" (one product has stock 5); set that product's stock to 20 and Run now again: "skipped — condition false" |
| 8.6 | Control Room → **Pause all** → Run now on any trigger | The event is held ("parked"); **Resume** releases it |
| 8.7 | Settings → **Automation** (`/settings/automation`): set "runs at the same time" to 1 | A second run waits its turn while one runs |
| 8.8 | Give an agent "May schedule work" (Automation tab) and ask it to "remind me to call Test Lead in 10 minutes" | A timer trigger "made by agent" appears in the Control Room and fires once |
| 8.9 | Bell (sidebar) | Notifications for paused runs / failures, marked read when opened |

---

## 9. Connections (tenant admin)

| # | Do | Expect |
|---|----|--------|
| 9.1 | Connections (`/connections`) → **Your own key for a service HireBuddha uses**: provider `serpapi` (or any) and a test key | Connected; details show who may use it; Disconnect removes it |
| 9.2 | **Mailbox (IMAP)**: a mailbox with an app password | Connected and tested; an Event trigger on `email.received` then starts an agent when a mail arrives (within 2 minutes) |
| 9.3 | (After the provider apps are registered) Facebook Pages, Gmail, GitHub … | The provider's consent window; choose accounts; connected |

---

## 10. Partner flows (partner admin, Durwankur Technologies)

| # | Do | Expect |
|---|----|--------|
| 10.1 | Profile 3: sign in as the partner admin | Partner Dashboard; "Working in" shows "My own company" |
| 10.2 | Partner Dashboard / Platform Hub → add a tenant "Durwankur Demo Client" | Created under the partner; its database becomes active (platform admin can watch in Admin → Tenants) |
| 10.3 | Add a tenant_admin user for the demo client | Created |
| 10.4 | Working in → **Durwankur Demo Client** | The yellow banner; the Entity Library is the client's (empty) |
| 10.5 | Build and run an agent while working in the client | The run belongs to the **client** and is paid from the **client's** wallet, not the partner's (decision D54) — check both wallets |
| 10.6 | Working in → back to my company | The partner's own data again |
| 10.7 | Portfolio Analytics (`/reports/analytics/partner-admin`) and Tenant health | Each of the partner's tenants with its runs and wallet |
| 10.8 | Try Working in → Buddha Cognitive Lab | Not in the list (not the partner's tenant) |

---

## 11. Isolation spot checks (two browsers side by side)

The automated isolation suite runs on dev, not production (owner, 21 Oct). By hand:

| # | Do | Expect |
|---|----|--------|
| 11.1 | As Buddha Cognitive Lab, open an agent; copy its address (`/ai/entities/edit/<id>`). As the demo client's admin, open the same address | "Not found" |
| 11.2 | The same with a run (`/ai/executions/<id>`) and a record | Not found |
| 11.3 | As the demo client, the Records, Knowledge Base, Artifacts and Control Room pages | None of Buddha Cognitive Lab's rows |
| 11.4 | Platform admin: Working in → Buddha Cognitive Lab → its agents | Visible (staff may act for any company) |

---

## 12. Reports, billing and platform views

| # | Do | Expect |
|---|----|--------|
| 12.1 | Tenant admin: Operations Analytics | Runs, success rate, model costs of their company only |
| 12.2 | Platform admin: Platform Analytics with "all companies" | Totals across every business database (Buddha Cognitive Lab + the demo client + the platform) |
| 12.3 | Platform admin: Admin → Tenants → Check health | Every tenant healthy, schema current |
| 12.4 | Wallet / Billing: top up the demo client; run there | Balance and billing events match |
| 12.5 | Platform admin: Agent kernel → KPI, Cost, Feature flags | Pages load; KPI fills after the hourly roll-up |

---

## 13. Later items (when their prerequisites exist)

### 13.1 Voice (after Twilio credentials)

System Integrations → Twilio (Account SID, Auth Token) → Phone Numbers → **Sync** → assign a number to a
voice agent → in Twilio point the number's voice webhook at
`https://gateway.azprod.hirebuddha.com/webhooks/voice/twilio/incoming` and its status callback at
`…/webhooks/voice/twilio/status`. **Expect:** a call to the number is answered by the agent; Streaming
Sessions shows the call and transcript; a campaign of two contacts dials both and records outcomes.

### 13.2 Code sandbox and tenant apps (after slice 4)

* An agent with the code tools runs Python in the sandbox (the first run after an idle spell waits a few
  minutes while the sandbox node starts).
* Apps → New app from a template (static site, site + form, CRM) → a pull request with checks → approve and
  merge → a build → preview → publish on `<app>-<business>.apps.<domain>`; a custom domain with its DNS
  records verified.

### 13.3 Deploys and operations

| # | Do | Expect |
|---|----|--------|
| 13.3.1 | After a push to the Phase 14 branch: GitHub → Actions → deploy-azure; the **prod** job waits for you → *Review deployments* → Approve | Tests, images and the dev deploy pass; production updates to the same images; `/api/v1/health` stays `ok` |
| 13.3.2 | Azure portal → Application Insights `appi-hb-prod` → Transaction search | Requests and dependencies from your test runs |
| 13.3.3 | Sunday after 02:00 IST: Storage `sthbprode7b3` → containers `platform/backups/<week>/` and `t-<key>/backups/<week>/` | The weekly database exports (decision D45) |
| 13.3.4 | Cost Management → Budgets | `budget-hb-prod-monthly` (₹55,000) and `budget-hb-dev-monthly` (₹50,000), each counting only its own resource groups |

---

## 14. Results

| § | Step | Result (✓ / ✗ / skipped) | Notes (time, what you saw) |
|---|------|--------------------------|----------------------------|
| 1 | Smoke | | |
| 2.1 | GPT via Foundry | | |
| 2.2 | E-mail | | |
| 3 | Companies and people | | |
| 4 | Sign-in, sign-up, workspace | | |
| 5 | Agents and runs | | |
| 6 | Knowledge and files | | |
| 7 | Records | | |
| 8 | Automation | | |
| 9 | Connections | | |
| 10 | Partner | | |
| 11 | Isolation | | |
| 12 | Reports and billing | | |
| 13 | Later items | | |

When something fails, note the run id or record id from the address bar; the API logs are in Azure portal →
Kubernetes service `aks-hb-prod` → Workloads → `hb-api` → Logs (or Application Insights, searching that id).
