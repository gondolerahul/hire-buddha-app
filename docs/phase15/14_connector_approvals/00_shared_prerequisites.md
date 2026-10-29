# 00 — What every provider asks for (do these first)

> **Researched:** 2026-10-28 · **Status:** Open — nothing below is done yet.
> **Why first:** Meta, Google, LinkedIn and Microsoft all read the same public pages and check the same legal identity. Both websites fail today (§2 and [08](08_website_readiness.md)), so any submission would be rejected before a reviewer looks at the product.

Each requirement has an ID. Each provider's document refers to these IDs instead of repeating them. Update **Status** as you close each one (Open → In progress → Done).

---

## 1. Legal identity and accounts

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| SH-01 | **One identity sheet**: the legal name exactly as on the certificate of incorporation, *including the suffix* ("Buddha Cognitive Lab Private Limited" or whatever the certificate says, character for character), CIN, GSTIN, PAN, registered address as printed on the GST certificate, a business phone number that is on an official record. Use these exact values in every form. | Owner | The sheet exists, and the Meta business portfolio, LinkedIn form, Partner Center and website footer all use the same values | Open |
| SH-02 | **Monitored mailboxes on `hirebuddha.com`**: `admin@` (provider accounts), `support@` (shown to users on consent screens), `privacy@` (already named in the privacy page), `security@` (vulnerability reports, CASA, incident contact). Never a Gmail or Outlook address: Meta, LinkedIn and Microsoft reject personal addresses. **Today hirebuddha.com has no MX record**, so no address on it receives mail, including `privacy@`, `hello@` and `enterprise@`, which the site already shows. Add the domain to the Google Workspace that runs buddhalab.in (WEB-02). | Owner | Each address receives mail. Verification mails go to spam and social/promotions tabs, so check those too | Open |
| SH-03 | **Domain verified** with each provider: Google Search Console (by a project owner), Meta Business (Brand safety → Domains), Microsoft Entra (custom domain), GitHub organisation (verified domain). All by TXT record at GoDaddy. hirebuddha.com has no TXT records yet, so none of the DNS checks is done (WEB-07). | Owner | Each console shows `hirebuddha.com` verified | Open |
| SH-04 | **Two admins with 2FA** on every provider account: Meta business portfolio, Google Cloud projects (owners), Partner Center, LinkedIn Page (super admins), X, GitHub organisation. | Owner | A second person can sign in to each one | Open |
| SH-05 | **The company's LinkedIn Page** (`linkedin.com/company/buddha-cognitive-lab`, already linked from hirebuddha.com) shows the legal name of SH-01 and the company's website, and presents HireBuddha as its product. LinkedIn's vetting and Meta's business verification both check that the company presented online matches the registration. | Owner | Name and website match SH-01 and [08](08_website_readiness.md) §2 | Open |

## 2. The public websites (not ready)

What the sites serve today (checked 28 Oct 2026). The full check of both sites, and the fixes WEB-01…WEB-15, are in [08](08_website_readiness.md). The replacement Privacy, Terms and Data deletion pages for both sites are drafted in [11](11_website_content/README.md), with the site-wide changes.

* hirebuddha.com's `/privacy` is a **template**. It says it is template content to replace before launch. It names no provider data (Google, Meta, LinkedIn, Microsoft, X, GitHub), has no Google "Limited Use" statement, lists no sub-processors and gives no retention periods.
* `/terms` is a **template** too, with the same wording. It doesn't say which entity contracts, which law governs, or who is responsible for AI-generated output.
* `/data-deletion` returns **404**. Meta requires a deletion URL or callback.
* The homepage and `/contact` show no legal name statement (only "© 2026 Buddha Cognitive Lab"), no postal address, no phone and no support address. Meta's business verification and LinkedIn's vetting both look for these.
* **hirebuddha.com can't receive mail**: it has no MX record, so the addresses the site shows bounce.
* **buddhalab.in**, the company site, has template legal pages with a San Francisco placeholder address and a contact domain nobody owns, template office addresses, endorsements and *partner* labels that a reviewer can't verify, and a broken link to HireBuddha.
* `app.hirebuddha.com` is a **Vite development server** on the old Google Cloud server (WEB-01).

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| SH-06 | **Homepage**: public, no sign-in; says what HireBuddha does *including the connectors* ("AI employees that read and answer your business's email, post to your Pages, reply to WhatsApp customers"); footer with legal name, registered address, `support@`, links to Privacy, Terms and Data deletion, and a *Sign in* link to the production app. Only claims that can be backed up (WEB-09). Google rejects a homepage that doesn't describe the app or sits behind a login. | Owner + Eng | Live on `hirebuddha.com` (WEB-03, WEB-09, WEB-11) | Open |
| SH-07 | **Privacy policy** (replace the template; counsel to review). It must be on `hirebuddha.com`, the same domain as the homepage (Google requires this). Sections: who we are (SH-01); what we collect; **one section per provider** (what HireBuddha reads, why, where it's stored, how long, who it's shared with); **AI model providers named as sub-processors** (Google Vertex AI for Gemini and Claude, Azure OpenAI, OpenAI, Anthropic: whichever are enabled in production); no sale and no ads; human access (§7 of [02](02_google.md)); deletion and disconnecting; DPDP/GDPR rights; the website's own data (the Pragya chat and voice, the lead form); contact; last-updated date. **Verbatim statements** to include are in §5 below. | Owner + Counsel | Published; each provider section matches what the code does | Open |
| SH-08 | **Terms of service** (replace the template): the contracting entity, governing law (India), acceptable use that carries the providers' rules through to businesses (no spam, no unsolicited bulk messaging; WhatsApp: no general-purpose AI assistant, opt-in before business-initiated messages; X: no duplicate posting across accounts), the business's responsibility for what its AI employees send and for approvals, third-party services, suspension. Also: people who connect YouTube agree to the YouTube Terms of Service (YouTube requires this sentence), and the business is the advertiser for any Google Ads its AI employees run ([09](09_youtube_and_google_ads.md)). | Owner + Counsel | Published | Open |
| SH-09 | **Data deletion page** `/data-deletion`. It must explain how a business disconnects a connector (*Connections → Disconnect*) and what HireBuddha deletes then, how to ask for full deletion (in the product: *Settings → Data & closing*; or `privacy@`), how long it takes, and how an end customer of a business asks (through the business; `privacy@` as fallback). Meta requires it; Google and LinkedIn read it. | Owner + Eng | `https://hirebuddha.com/data-deletion` returns the page | Open |
| SH-10 | **Sub-processor list** (a page or a section of SH-07), and a **security page** with `security@`, also named in `/.well-known/security.txt` (WEB-12). CASA assessors and enterprise buyers ask for both. | Owner | Published | Open |
| SH-11 | **The app's logo**: 1024 × 1024 PNG (Meta), 120 × 120 square (Google), plus 512 × 512. No provider marks in it: Meta forbids its trademarks and LinkedIn forbids "Linked"/"In" or its logo in the app's name or icon. | Owner | Files in the shared drive | Open |

## 3. Production hostnames

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| SH-12 | **Decide the hostnames customers will use** before registering any redirect URI or recording any video. The provider guide uses `app.hirebuddha.com` and `gateway.hirebuddha.com`. Production answers today on `app.azprod.hirebuddha.com` and `gateway.azprod.hirebuddha.com` (`infra/k8s/env/prod/hb-platform.yaml`), while `app.hirebuddha.com` and `gateway.hirebuddha.com` still point at the old Google Cloud server, where `app.` is a Vite development server ([08](08_website_readiness.md) §5, WEB-01). The OAuth callback is `<CONNECTIONS_PUBLIC_URL or the gateway>/oauth/callback/<provider>`. Google's demo video must show the **production** OAuth client, so the hostname in the video is the one being reviewed. | Owner + Eng | One decision recorded; `CONNECTIONS_PUBLIC_URL` set; the same URLs registered with every provider | Open |

## 4. Reviewer access, test accounts, recordings

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| SH-13 | **In-product disclosure on every connect screen**: before sending the person to the provider, the screen names the data HireBuddha will read and what AI employees do with it, links the privacy policy, and asks the person to continue. Google's Workspace developer policy requires disclosure *during normal use*, not only in the privacy policy; Meta and LinkedIn reviewers look for it in the recording. | Eng | Each connector's connect dialog shows it | Done (code) |
| SH-14 | **Reviewer accounts on HireBuddha**: a test business per provider review, with a person whose password is in the vault and **no MFA** on that account (reviewers can't receive codes), one AI employee already set up per connector, and step-by-step written instructions. Never your own personal provider credentials (Meta forbids it). | Eng | The instructions work from a fresh browser | Open |
| SH-15 | **The review environment stays up.** Azure dev is stopped outside Monday–Saturday 09:00–21:00 IST (`logic-hb-dev-start` / `-stop`, 09 §8), and reviewers work in other time zones. "Unable to access the app" is a standard rejection. Review on production (the platform's own test business, connector in *Preview*), or keep dev running for the whole review window. | Owner + Eng | The environment answers at any hour during each review | Open |
| SH-16 | **Test accounts at each provider**: a Facebook Page, an Instagram professional account linked to it (with *Allow access to messages* on), a WhatsApp test number; a LinkedIn test Page you are super admin of; a consumer Gmail account and a Google Workspace mailbox; a Microsoft 365 developer-tenant mailbox and an outlook.com mailbox; an X account; a GitHub test organisation; a phone-verified YouTube channel and a Google Ads account with billing (YT-06). Make each one look real: Meta and LinkedIn reviewers reject recordings of empty assets. | Owner | Credentials in the vault, listed by name in the tracker | Open |
| SH-17 | **Recording rules**: see the table below. Record **after** the engineering items of that provider are done, on the environment of SH-15, starting from a disconnected state. | Eng | — | Open |

| | Meta | Google | LinkedIn |
|---|---|---|---|
| Videos | One per permission | One video (all scopes; each consent flow shown) | One screencast covering every use case in the form |
| Resolution | 1080p or higher, screen width ≤ 1440 px | Readable; full consent screen visible | High resolution, downloadable file |
| Language | English UI; captions and tooltips | English consent screen (toggle bottom-left) | English |
| Audio | None (captions instead) | Narration optional, recommended | Narration recommended |
| Must show | Login, the permission granted, the feature using it, the result on Facebook/Instagram/WhatsApp | App name on the consent screen, **the OAuth client ID in the address bar**, every scope in use | The full OAuth flow, each use case, which member data is shown |
| Hosting | Uploaded in App Review | YouTube, *Unlisted* | Uploaded with the form |

## 5. Statements the privacy policy must carry

Have counsel adapt the wording. These are the commitments the providers check for.

* **Google (all Google data):** that HireBuddha's use and transfer of information received from Google APIs follows the Google API Services User Data Policy, *including the Limited Use requirements* (Google gives this sentence as its example).
* **Google Workspace data and AI:** that HireBuddha does not use, transfer or sell data from Google Workspace APIs to develop, improve or train generalised or non-personalised AI or ML models, and keeps no such data for that purpose. Google asks for this affirmative statement during verification.
* **Model providers:** which AI providers receive connected-account data to produce a feature, that they process it under terms that forbid training on it, and that HireBuddha keeps no copy for training.
* **Meta:** what is read from Pages, Instagram and WhatsApp (posts, comments, messages, insights), what it is used for, and how to ask for deletion (link to SH-09).
* **LinkedIn:** that member data (comments, mentions, profile fields of people engaging with a Page) is shown only to people of that Page's business, kept no longer than LinkedIn allows (48 hours for member activity, 24 hours for member profile data), and never used for sales, recruiting or advertising.
* **X:** that X content is deleted when it is deleted on X, and is never used to train models.
* **YouTube:** that HireBuddha uses YouTube API Services; a link to the Google Privacy Policy (`https://policies.google.com/privacy`); what YouTube data HireBuddha uses and how; that people can revoke HireBuddha's access on Google's security settings page (`https://security.google.com/settings/security/permissions`); and that YouTube data is deleted within 7 days of disconnecting ([09](09_youtube_and_google_ads.md) §2).
* **Google Ads:** that HireBuddha reads and changes campaigns only in the accounts a business connects, makes changes that spend money only after a person approves them, and uses the data only for that business.
* **Retention and deletion:** what is deleted when a business disconnects a connector or closes its account (the offboarding of 13), and within what time.

## 6. Engineering items shared by several providers

| ID | Requirement | Providers | Done when | Status |
|----|-------------|-----------|-----------|--------|
| SH-E1 | **Disconnect deletes, not just forgets.** On *Disconnect*: revoke at the provider where it offers revocation (Google, X: `revoke_endpoint`; Meta: today only unsubscribes webhooks, add `DELETE /me/permissions` for the user token; GitHub: the installation; Microsoft and LinkedIn have no revocation endpoint, so delete the tokens), delete the sealed secret, and delete or expire what was derived from the account (rule SH-E2). Write down the time it takes; the privacy policy and SH-09 quote it. | All | A test: connect, run, disconnect → no token, provider data purged per SH-E2 | Partly done (code) |
| SH-E2 | **Retention by source.** Mark data that came through a connector (tool outputs and run traces, CORTEX memory, records written by agents) with its connector, and apply each provider's limits: LinkedIn member activity 48 h and member profile data 24 h ([03](03_linkedin.md)); X content deleted within 24 h of its deletion on X ([05](05_x.md)); YouTube data deleted or refreshed within 30 days, and its analytics kept only while the authorisation is re-checked every 30 days ([09](09_youtube_and_google_ads.md)); Google data only as long as the feature needs it ([02](02_google.md)). A nightly job enforces them. | LinkedIn, X, YouTube, Google | The job runs; a test puts a LinkedIn comment in a trace and finds it gone after 48 h | Open |
| SH-E3 | **Prompt-injection screening** of untrusted content from connectors (mail bodies, documents, comments, DMs) before it reaches the planner, and marking such content as untrusted in prompts. Google's Workspace developer policy now **requires** protection against prompt injection ("Model Armor or equivalent"). Nothing in the code does this today. On Azure, Azure AI Content Safety *Prompt Shields* is the nearest equivalent. | Google (required); all (recommended) | A screening step in the run loop for connector content, with a test that a planted instruction in an e-mail is flagged | Done (code) |
| SH-E4 | **A person confirms outbound actions on connected accounts by default**: sending or drafting mail, changing Drive files, posting, replying and messaging. Google's policy requires explicit confirmation of each agentic action with granular control. X requires its prior approval for AI-generated replies. YouTube requires the person's express consent before each upload, edit or comment, and Google Ads changes that spend money need the same gate ([09](09_youtube_and_google_ads.md)). Reviewers of every provider ask "who decides what gets sent?". Build it on the existing HITL approvals (`ai/governance/hitl_gate.py`) as a **platform rule per connector action**, not an option each agent's builder may forget. | Google and YouTube (required), X, Meta, LinkedIn, Google Ads | A connector action without an approval cannot run unless staff have relaxed it for that action; the approval screen shows the exact content | Done (code) |
| SH-E5 | **Security baseline for CASA** (needed for Gmail; strengthens every review): OWASP ASVS checks on the gateway, API and worker; dependency and container scanning in CI; TLS and security headers on `app.` and `gateway.`; OAuth `state` and PKCE checked (PKCE is on for Google, Microsoft and X); tokens sealed with AES-256-GCM under each business's key in Key Vault (`connections/crypto.py`). Google asks for keys "in an HSM or equivalent", so confirm the key type in the tenant-keys vault. Add an incident-response note naming `security@` and Google's `security@google.com`. | Google; all | A pre-assessment scan with no high findings ([02](02_google.md) §6) | Open |
| SH-E6 | **Support staff don't read connected-account content without consent.** Staff "Work in this business" and see its runs, so they see e-mail bodies, DMs and comments in traces. Google forbids human access to user data without the user's affirmative agreement (other exceptions: security, law, aggregated data). Either redact connector content in traces for staff, or show it only under a time-boxed access the business grants (like the partner grants of M15.4). | Google (required); all | The rule is in code and in the privacy policy | Open |

## 7. Obligations that recur

| What | When | Provider |
|------|------|----------|
| Data Use Checkup (and data handling questions) | Every year, when the developer dashboard asks | Meta |
| CASA security reassessment (Letter of Validation) | Every 12 months after approval | Google (Gmail) |
| Brand re-verification | After any change to name, logo, homepage or domains | Google |
| Client secret renewal | Microsoft: secret expiry (set 24 months, diary it); others when rotated | Microsoft, all |
| LinkedIn API version | Before the version in use is sunset (each lasts about a year) | LinkedIn |
| X credits and spending limit | Monthly | X |
| Policy alerts | Meta developer alerts; Google e-mails to project owners and editors; LinkedIn and X developer changelogs | All |
| YouTube API compliance audit | When YouTube asks; resubmit the form if the use case changes; use the project at least once every 90 days | YouTube |
| Google Ads API version | Four major versions a year, each lasting about a year | Google Ads |
| The websites' claims and legal pages (the checks of [08](08_website_readiness.md) §7) | Before every submission | All |
