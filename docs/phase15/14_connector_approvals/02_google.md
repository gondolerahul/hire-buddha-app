# 02 — Google: Gmail and Google Drive

> **Researched:** 2026-10-28 · **Status:** Not submitted (catalog: `gmail`, `google_drive` are `planned`, approval `not_submitted`).
> **App:** Google Cloud project `hirebuddha-connect` (production, reviewed) and `hirebuddha-connect-dev` (left in *Testing*), OAuth client `oauth-app-google`. How to create them: [provider guide §4](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md). YouTube and Google Ads use a third project, `hirebuddha-marketing` ([09](09_youtube_and_google_ads.md) §4).
> **Lead time:** brand verification 2–3 business days; Drive (non-sensitive scope) days; Gmail (restricted scope) about 6 weeks for the review **plus** the CASA security assessment, so 6–12 weeks end to end for a first submission. **Cost:** Drive free; Gmail needs a CASA assessment by an authorised lab every 12 months (TAC Security's list prices: US$540–1,800 for the lab-reviewed level, US$4,500 for the lab-tested one).

---

## 1. What Google checks

1. **Brand verification:** app name, logo, support e-mail, homepage, privacy policy and terms on verified domains. An automated check usually finishes in minutes, a manual one in 2–3 business days. A passed check is valid for 7 days, so publish the branding right after.
2. **Data access verification** for sensitive and restricted scopes: a justification per scope ("why a narrower scope won't do"), the permitted application type, and a demo video. Google rejects scopes broader than the feature needs.
3. **Restricted scopes (all Gmail read scopes):** the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy) with its *Limited Use* rules, and a **CASA security assessment** by an empanelled lab, renewed every 12 months, because HireBuddha's servers process the data.
4. **The [Google Workspace API user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)**, which now has rules for AI agents (§2).

## 2. Rules in Google's Workspace developer policy that bind an AI agent product

| Rule | What it means for HireBuddha | Requirement |
|---|---|---|
| No training of AI/ML models beyond the user's own personalised one, on raw **or derived** Workspace data; no databases built for training | Gmail and Drive content stays inside that business's use; never in platform-wide learning, evaluation sets or cross-company pattern mining | GOOG-E6 |
| **Protection against prompt injection** "using Google Cloud Model Armor or equivalent" | Screen mail and document content before the planner sees it | SH-E3 |
| Users **explicitly confirm each agentic action** (tools, MCP, skills), with granular control; permissions requested in context (incremental) | A person approves each send, draft or Drive write; each connector asks only for its own scopes when it is connected | SH-E4, GOOG-E2 |
| Gmail **sending** is approved for user-facing clients where people compose, send, read and process mail through a UI | The approval screen is where the person sees and sends the e-mail. Don't describe it as "the agent sends on its own" | SH-E4, §4 |
| Drive restricted-scope access limited to actions through the app's UI | Not triggered by `drive.file` (non-sensitive), but the same spirit: the person picks files | GOOG-E4 |
| **In-app disclosure** during normal use naming the data and its use; affirmative consent before any collection | The connect screen | SH-13 |
| No human reads user data without the user's affirmative agreement (or for security, the law, or aggregated data) | Staff working in a business mustn't see e-mail bodies in traces without a grant | SH-E6 |
| Tokens encrypted at rest with keys in an HSM or equivalent; HTTPS; incidents reported to `security@google.com` | Already sealed per business in Key Vault; confirm the key type | SH-E5 |
| A privacy policy, a Limited Use statement, help pages on managing and deleting data | SH-07 §5, SH-09 | SH-07, SH-09 |

## 3. The scope decision for Gmail: fix this first

**Found in the code.** The Gmail connector asks for `gmail.modify` and `gmail.send` (`connections/catalog/gmail.yaml`). But the product reads and sends Gmail over **IMAP and SMTP with XOAUTH2** (`connections/client.py` `email_credentials`, `automation/pollers/mailbox.py`, `ai/tools/email/email_tool.py`). Google allows IMAP, POP and SMTP only with `https://mail.google.com/`. So a Gmail connection made with today's scopes would fail at the IMAP login.

| Option | Scopes | Google review | Code change | Verdict |
|---|---|---|---|---|
| **A. Gmail REST API** | `gmail.modify` (read, label, draft, send; no permanent delete) | Restricted + CASA | The poller and the e-mail tools call the Gmail API for Gmail connections (`history.list` / `messages.get`, `drafts.create`, `messages.send`) | **Recommended.** One restricted scope with a clear justification |
| A′. Send only first | `gmail.send` | Sensitive, **no CASA** | Sending through the Gmail API; no inbox triggers or reading | A useful first launch while CASA runs; reading stays on the IMAP connector |
| B. Keep IMAP/SMTP | `https://mail.google.com/` | Restricted + CASA, and the hardest to justify: Google says to request it only if the app must permanently delete mail, and recommends migrating to the Gmail API | Scope change only | Not recommended |
| C. The Mailbox connector with the person's app password | None: IMAP and SMTP sign in with the app password | **None** (HireBuddha's OAuth app isn't involved) | None: `imap_mailbox` exists | Works now where the person can create an app password and the Workspace admin allows IMAP. Google discourages app passwords, and changing the account's password revokes them ([07](07_connectors_without_review.md) §1). **The bridge while A is reviewed**, not the long-term Gmail connector |

Drop `gmail.send` when `gmail.modify` is requested: `gmail.modify` already covers sending, and overlapping scopes count as over-asking.

**Drive.** `drive.file` is non-sensitive (no CASA), but it only reaches files HireBuddha created or files the person **chose in the Google Picker**. The connector's `read_file` and `update_file` actions on existing files need the Picker (GOOG-E4).

## 4. Requirements

### A. Projects and brand

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-01 | Projects as in the guide: production `hirebuddha-connect` (the one reviewed), dev `hirebuddha-connect-dev` in *Testing* (up to 100 test users; their refresh tokens last 7 days). Both apart from the Vertex AI project. YouTube and Google Ads get their own project (YT-01), so this one's restricted-scope review never holds them up | Owner | Both exist; APIs enabled (Gmail, Drive, Picker) | Open |
| GOOG-02 | `hirebuddha.com` verified in Search Console **by a project owner** (SH-03). Every domain on the branding page and in redirect URIs must be verified; `hirebuddha.com` covers `app.` and `gateway.` | Owner | Search Console shows it | Open |
| GOOG-03 | **Branding**: name `HireBuddha` (the same on the homepage, the consent screen and in the video), logo (SH-11), support e-mail (SH-02), homepage (SH-06), privacy (SH-07), terms (SH-08), authorised domain → *Verify branding* → publish | Owner | Branding *Verified* and published | Open |
| GOOG-04 | Audience **External**, publishing status **In production**: Google verifies only production apps | Owner | — | Open |
| GOOG-05 | At least two project owners and a developer contact that is a group address read every day: Trust & Safety writes there, and every question restarts the wait | Owner | — | Open |
| GOOG-06 | Data access lists exactly the scopes of §3 after GOOG-E1/E2 (`openid`, `email`, `drive.file`, `gmail.modify`). Declare nothing the video doesn't show | Owner | — | Open |
| GOOG-07 | Web OAuth client in the production project with the production redirect URI only (SH-12); the dev client in the dev project | Owner | Client ID handed to engineering | Open |

### B. Engineering before recording

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-E1 | **Gmail through the Gmail API** (option A of §3): reading new mail for `email.received` (history or list polling; Pub/Sub push optional), reading a message, saving a draft, sending; IMAP/SMTP stay for the `imap_mailbox` connector only | `automation/pollers/mailbox.py`, `ai/tools/email/email_tool.py`, `connections/client.py` | A Gmail connection reads, drafts and sends on dev with `gmail.modify` alone | Done (code) |
| GOOG-E2 | **Scopes**: `gmail.yaml` → `openid`, `email`, `gmail.modify`; `google_drive.yaml` stays `openid`, `email`, `drive.file`. Each connector asks only when it is connected (incremental; `include_granted_scopes=true` is already sent) | `connections/catalog/*.yaml` | — | Done (code) |
| GOOG-E3 | **Granular consent**: people can untick scopes on Google's consent screen. Compare the token's granted `scope` with what the connector needs; if a scope is missing, say which feature won't work and offer to grant again. Ask again only when the person acts. Today `exchange` stores what was granted but never compares it | `connections/providers/oauth.py`, `connections/service.py`, connect UI | A test with a partial grant shows the message | Done (code) |
| GOOG-E4 | **Google Picker for Drive**: a "Choose files" step (Picker API with the project's API key and project number) so agents can read the files a person picks; files HireBuddha creates are reachable anyway. Or remove `read_file`/`update_file` on existing files from the connector until it exists | Frontend connect/use flow, `google_drive.yaml` | A picked file is read by an agent on dev | Open |
| GOOG-E5 | The Workspace developer policy rules of §2: SH-E3 (prompt injection), SH-E4 (a person approves each send, draft and Drive write; the approval shows the exact e-mail), SH-13 (disclosure), SH-E6 (staff access) | See the SH items | The SH items are done | Partly done (code) |
| GOOG-E6 | **No training, no cross-business use**: Gmail- and Drive-derived content (traces, CORTEX memory, records) stays in that business; excluded from platform-wide learning, failure-pattern mining across companies and evaluation sets; model providers used with no training on prompts (confirm the settings of any direct OpenAI or Anthropic key) | `ai/` memory and learning services, provider settings | A written data-flow note for the CASA lab and the privacy policy | Open |
| GOOG-E7 | **Token lifecycle**: every connect sends `prompt=consent` and so issues a new refresh token. Google keeps 100 per Google account per client and silently drops the oldest. On `invalid_grant`, mark the connection expired and tell the business; never loop reconnects | `connections/service.py` | A test of the expired path | Done (code) |
| GOOG-E8 | Disconnect revokes (`oauth2.googleapis.com/revoke`, present) and deletes derived data (SH-E1, SH-E2) | `connections/service.py` | SH-E1's test with Gmail | Done (code) |
| GOOG-E9 | Security baseline (SH-E5) and the pre-assessment scan of §6 | CI, infra | No high findings | Open |

### C. The submissions

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-10 | **Drive first**: brand verification and `drive.file`. Non-sensitive scopes need no justification or video, but the brand must pass | Owner | Drive connector *Available* | Open |
| GOOG-11 | **Gmail**: *Verification Centre → Prepare for verification*: the justification (§5), the permitted application type (*What features will you use?*: choose the matching one, or none and Google decides), up to three documentation links (the help page on connecting Gmail, the data deletion page, the privacy policy), the demo video (§5) | Owner + Eng | Submitted | Open |
| GOOG-12 | Confirm the Limited Use and AI statements when Google asks (SH-07 §5); reply to every Trust & Safety e-mail within a day | Owner | — | Open |
| GOOG-13 | If the Verification Centre says to reply to an e-mail that never came, check every owner's and editor's spam, then raise it on the Google Developer forum or with Cloud support. Developers have reported weeks lost this way | Owner | — | Open |

### D. CASA security assessment (Gmail)

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-20 | Wait for Google's e-mail that starts the assessment (labs can't start without it), then choose an authorised lab from the Verification Centre's list. Google assigns the level: **AL1** (we run the required tests, the lab reviews the evidence) or **AL2** (the lab tests the running app). Self-scans are no longer accepted | Owner | Lab engaged | Open |
| GOOG-21 | Scope of the assessment: everything Gmail data passes through (gateway, API, workers, storage, the tenant databases) and the data-flow note of GOOG-E6 | Eng | Scope agreed with the lab | Open |
| GOOG-22 | Pass: no finding on a high-likelihood CWE (at recertification, none on a medium one either); fix and rescan | Eng | Letter of Validation | Open |
| GOOG-23 | Renew 12 months after the letter; a new restricted scope may need a new assessment | Owner | Calendar entry | Open |

### E. Sign in with Google (the login, not a connector)

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-30 | The project that holds `GOOGLE_CLIENT_ID` (`auth/router.py`) needs **brand verification only**: `openid`, `email` and `profile` are non-sensitive. Keep it out of the Gmail project so a Gmail review never touches sign-in | Owner | Branding verified on that project | Open |

### F. After approval

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GOOG-40 | Connectors to *Preview*, then *Available*; approval recorded on *Platform Console → Connectors* | Eng | Catalog rows `approved` | Open |
| GOOG-41 | Re-verify the brand after any change to name, logo, homepage or domains; keep owners' contacts current | Owner | — | Open |
| GOOG-42 | **Customers' Workspace admins** can block or restrict third-party apps (*Security → API controls*). Add a help article: how an admin marks HireBuddha as trusted by its client ID | Eng + Owner | Article linked from the Gmail and Drive connect screens | Open |

## 5. What to submit

**Justification for `gmail.modify`** (draft):

> HireBuddha is a workspace where a business's AI employees handle its customer e-mail, with a person in charge. With gmail.modify, HireBuddha reads new messages in the mailbox the person connected so the business's workflow can start (for example, preparing a reply to a customer's question), labels the messages it has handled, saves the AI's reply as a Gmail draft and sends it only after a person approves it in HireBuddha's approval screen. Narrower scopes don't cover this: gmail.readonly can't label, draft or send; gmail.send can't read; gmail.compose can't read or label. HireBuddha never deletes mail. Mail content is used only for that business's own features, is not used to train AI models, and is deleted when the mailbox is disconnected.

**`drive.file`** (no justification required; describe it anyway in the app description): agents read the files a person picks with the Google Picker and save the files they produce (reports, drafts) to the person's Drive.

**Demo video** (YouTube, *Unlisted*, English, production client; one take, about 4 minutes, captions naming the scope in use at each step):

1. HireBuddha in the browser, signed in as the reviewer business; the address bar shows the production hostname.
2. *Connections → Gmail → Connect*: the in-app disclosure (SH-13) → *Continue*.
3. Google's sign-in and **consent screen in English**: the app name `HireBuddha`, the scopes listed; zoom on the address bar to show `client_id=` (the production client ID) → *Continue*.
4. The connection appears with the mailbox address.
5. From another account, send an e-mail to the mailbox → it arrives in HireBuddha and starts the AI employee (`gmail.modify`: read).
6. The AI employee's reply waits on the approval screen, showing the full e-mail → *Approve* → open Gmail: the message is in *Sent* and in the recipient's inbox; the original carries HireBuddha's label (`gmail.modify`: draft, send, label).
7. *Connections → Google Drive → Connect*: the second consent screen (`drive.file`) → the Picker → choose a file → the AI employee summarises it → the summary file appears in Drive.
8. *Disconnect* both → Google Account *Third-party access* no longer lists HireBuddha.

## 6. Pre-assessment for CASA

Run before the lab does, and fix what it finds: dependency and container scans of the API, worker and gateway images; a dynamic scan of `app.` and `gateway.` (OWASP ZAP baseline); TLS and security headers; OAuth `state`, PKCE and redirect-URI checks; secrets out of images and logs; the access-control tests of the partner and tenancy suites as evidence. Keep the CASA questionnaire answers next to the evidence.

## 7. Common rejections and how they were resolved

Sources: Google's verification and demo-video help (official), Google Developer forum threads, practitioner write-ups (§8). Reddit could not be opened from this environment.

| Rejection or symptom | Usual cause | What fixed it |
|---|---|---|
| "Your demo video does not show the OAuth consent screen workflow" | The video starts already connected, or the consent screen isn't in English or doesn't show every scope | Record from disconnected; switch the consent screen to English; show every scope |
| "Your demo video does not show the same application you submitted" | Recorded on localhost or with the dev client; name or logo differs | Record on production with the reviewed client (its ID visible in the address bar), same name and logo |
| "The video does not sufficiently demonstrate the functionality" | A scope requested but not shown in use | Show each scope doing visible work, as in §5; drop scopes the video can't show |
| "We are unable to access the video" | Private video or broken link | YouTube *Unlisted*; reply to the review e-mail with the link |
| "Request minimum scopes" | `https://mail.google.com/` for IMAP, or `gmail.modify` **and** `gmail.send` | §3: Gmail API with `gmail.modify` alone; explain why each narrower scope fails |
| Homepage rejected | Behind a login, doesn't describe the app, or no privacy link | SH-06 |
| Privacy policy rejected | Generic, on another domain, no Limited Use or AI statement | SH-07 with §5 of 00 |
| Domain not verified | A redirect or homepage domain missing from Search Console | GOOG-02 |
| Branding out of compliance | Logo or name changed after verification | Re-verify after every change (GOOG-41) |
| "Apps in testing are not applicable for verification" | Publishing status *Testing* | GOOG-04 |
| Review stalls with no e-mail | Mail to an owner who left, or to spam | GOOG-05, GOOG-13 |
| CASA can't start | The lab needs Google's assessment e-mail first | GOOG-20: wait for it, then book |
| Users see "Google hasn't verified this app"; new users capped at 100 | Not verified yet | Expected until approval; use test users on dev |
| A feature breaks for some users | They unticked a scope (granular consent) | GOOG-E3 |
| Connections die after many reconnects | The 100-refresh-token limit per account and client | GOOG-E7 |

## 8. Sources

* Google (official): [Submitting your app for verification](https://support.google.com/cloud/answer/13461325?hl=en); [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification); [Restricted scopes list](https://support.google.com/cloud/answer/13464325); [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes); [IMAP/SMTP XOAUTH2](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol); [Demo video](https://support.google.com/cloud/answer/13804565?hl=en); [Application use cases (AI/ML)](https://support.google.com/cloud/answer/13805798?hl=en); [API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy); [Workspace API user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy); [Choose Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth); [Granular consent in web apps (Nov 2025)](https://workspaceupdates.googleblog.com/2025/11/granular-oauth-consent-in-webapps.html)
* Forums: [Restricted-scope review with no e-mail for 3+ weeks; CASA assessor blocked](https://discuss.google.dev/t/restricted-scope-oauth-verification-no-first-email-3-weeks-after-submission-casa-assessor-blocked/378566); [Missing e-mail at "Request minimum scopes"](https://discuss.google.dev/t/missing-oauth-verification-email-unable-to-respond-to-minimum-scopes-review/408506)
* Practitioners (secondary): [Google OAuth verification and CASA for AI agent startups (Agentic Fabriq)](https://www.agenticfabriq.com/blog/google-oauth-verification-casa); [CASA levels and costs (DeepStrike)](https://deepstrike.io/blog/google-casa-security-assessment-2025); [CASA providers and pricing (Switch Labs)](https://www.switchlabs.dev/post/casa-tier-2-tier-3-security-review-providers-pricing-and-the-cheapest-option); [Refresh-token limit (Formstack)](https://help.formstack.com/hc/en-us/articles/44593146748051-Google-Account-Token-Limitations)
* This repository: `backend/src/connections/catalog/{gmail,google_drive}.yaml`, `backend/src/connections/providers/oauth.py`, `backend/src/connections/client.py`, `backend/src/automation/pollers/mailbox.py`, `backend/src/ai/tools/email/email_tool.py`
