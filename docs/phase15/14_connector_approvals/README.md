# Phase 15 — Provider approvals for connectors

> **Researched:** 2026-10-28, codebase at `80537e1`; both websites checked the same day · **Status:** Requirements written; nothing submitted. Every connector that needs a review is `planned` with approval `not_submitted` (`backend/src/connections/catalog/*.yaml`).
> **Who:** the owner (accounts, legal details, consoles, submissions), engineering (the code changes and the recordings), counsel (privacy policy and terms).
> **Builds on:** [PROVIDER_APP_REGISTRATION_GUIDE.md](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md), which explains how to create each app. This folder covers what each provider checks before it approves the app, what must change in the product first, what to submit, and why submissions get rejected.

A business connects its Gmail, Facebook Page, WhatsApp number, LinkedIn Page or YouTube channel **through HireBuddha's own app** with each provider (Phase 14 WS5). Until a provider approves that app, only HireBuddha's own test accounts can connect.

## Documents

| # | Document | Connectors |
|---|----------|------------|
| 00 | [What every provider asks for](00_shared_prerequisites.md): legal identity, website pages, reviewer access, recordings, shared code changes | All |
| 01 | [Meta](01_meta.md): business verification, App Review, Tech Provider with Tata | WhatsApp Business, Facebook Pages, Instagram |
| 02 | [Google](02_google.md): brand and scope verification, CASA | Gmail, Google Drive (and sign-in with Google) |
| 03 | [LinkedIn](03_linkedin.md): Community Management API, Development then Standard tier | LinkedIn Page |
| 04 | [Microsoft](04_microsoft.md): publisher verification, admin consent | Outlook / Microsoft 365 mail |
| 05 | [X](05_x.md): no review; rules, AI-reply approval, pay per use | X |
| 06 | [GitHub](06_github.md): no review; optional Marketplace | GitHub |
| 07 | [Connectors without a review](07_connectors_without_review.md), and whether app-password mailboxes work for HireBuddha | HubSpot, Mailbox (IMAP), MCP server, API keys |
| 08 | [Website readiness](08_website_readiness.md): buddhalab.in and hirebuddha.com, checked page by page | All: every provider reads them |
| 09 | [YouTube and Google Ads](09_youtube_and_google_ads.md): OAuth verification, YouTube's audit and quota, Google Ads API access | YouTube (publishing, comments, analytics), Google Ads (YouTube ads and their performance) |
| 10 | [Code fixes](10_code_fix_plan.md): every engineering item in three waves, what was built and tested, what remains, how to deploy | All |
| 11 | [Website content](11_website_content/README.md): Privacy, Terms and Data deletion pages for both sites, and the site-wide changes | All: every provider reads them |

## Which connectors need a review

| Connector | Provider | Review | Lead time | Cost |
|---|---|---|---|---|
| WhatsApp Business | Meta | Business verification; App Review of 2 permissions; Tech Provider partner solution with Tata | 1–3 weeks | Free (messages on Tata's credit line) |
| Facebook Pages, Instagram | Meta | App Review, Advanced access to about 12 permissions | 2–6 weeks (first submissions are often rejected once) | Free |
| Google Drive | Google | Brand verification (`drive.file` is non-sensitive) | Days | Free |
| Gmail | Google | Restricted-scope verification **and** a CASA security assessment every 12 months | 6–12 weeks | Lab fee, about US$540–1,800 a year |
| YouTube (publishing, comments, analytics) | Google | Brand and sensitive-scope verification on a separate project; YouTube's compliance audit before uploads outgrow 100 a day across all businesses | About 2 weeks; the audit has no published timeline | Free |
| Google Ads (YouTube ads, ad performance) | Google | Sensitive-scope verification; the project's Google Ads API access (Explorer, then Basic minutes after brand verification; Standard is a manual review) | About 2 weeks | Free; ad spend is the business's own |
| LinkedIn Page | LinkedIn | Development tier vetting, then Standard tier with a screencast. **A rejected app can't re-apply** | Several weeks | Free |
| Outlook / Microsoft 365 mail | Microsoft | Publisher verification; **each customer's admin consents** (the default policy blocks users from granting mail access) | 1–3 weeks, then per customer | Free |
| X | X | None, but X's prior approval for AI-written replies | A day | Pay per use (about US$0.015 a post) |
| GitHub | GitHub | None | An hour | Free |

## What would fail today

Found while writing these documents. Each is a requirement in the document named. **Since 28 Oct 2026, items 2–5 and 10 are fixed in the code ([10](10_code_fix_plan.md)), not yet deployed. Items 6 and 11 are partly fixed: approvals and prompt-injection screening are built, retention and staff access are open; Microsoft mailboxes are refused on the password path, the platform's own mail is open. The pages for item 1 are drafted ([11](11_website_content/README.md)), not yet published.**

1. **The websites** ([08](08_website_readiness.md)). On hirebuddha.com, `/privacy` and `/terms` are templates that say so, `/data-deletion` is a 404, no page shows the legal name, address or a support contact, and **the domain can't receive mail** (no MX record), so the `privacy@`, `hello@` and `enterprise@` addresses it shows bounce. On buddhalab.in, the legal pages carry a San Francisco placeholder address and a contact domain nobody owns, the office addresses come from a template, testimonials and *partner* labels can't be verified, and the link to HireBuddha is broken. Every provider reads these pages (SH-06…SH-09, WEB-02…WEB-11).
2. **Gmail asks for the wrong scopes for how it works.** The product reads and sends Gmail over IMAP/SMTP, which Google allows only with `https://mail.google.com/`, the broadest Gmail scope. The connector asks for `gmail.modify` and `gmail.send`. Move Gmail to the Gmail API with `gmail.modify` alone (GOOG-E1, GOOG-E2).
3. **Outlook has the same mismatch.** IMAP/SMTP need Exchange Online scopes and a separate token, while the connector asks for Graph scopes; the account lookup also needs `User.Read`. Move Outlook to Microsoft Graph (MS-E1, MS-E2).
4. **LinkedIn's API version is past its sunset.** The connector sends `202409` and the tools send `202509`; both are retired, so calls fail (LI-E1).
5. **Meta has no data deletion callback,** and the Pages and Instagram scopes miss a dependency (`pages_read_user_content`) (META-E1, META-E2).
6. **AI-agent rules.** Google's Workspace developer policy now requires prompt-injection protection and a person's confirmation of each agent action. X requires approval for AI replies. LinkedIn and X limit how long their data may be kept, which run traces and memory don't respect yet (SH-E2…SH-E4, SH-E6).
7. **Hostnames.** The guide registers `gateway.hirebuddha.com`, but production answers on `gateway.azprod.hirebuddha.com`. Decide before registering redirect URIs or recording (SH-12).
8. **Reviewers can't reach dev at night.** Azure dev stops outside Monday–Saturday 09:00–21:00 IST (SH-15).
9. **The old app hostnames.** `app.hirebuddha.com` and `gateway.hirebuddha.com` still point at the old Google Cloud server, and `app.` is a Vite development server that publishes the frontend's source. Take it off the internet now (WEB-01).
10. **YouTube and Google Ads have tools but no connectors.** The tools read the old `social_connections` table, which goes after WS7. Google Ads calls API v18, sunset in 2025, and sends developer tokens, which Google stopped using on 9 September 2026 ([09](09_youtube_and_google_ads.md) §5).
11. **Microsoft mailboxes can't use app passwords.** The old e-mail wizard still offers *Outlook / Office 365* with an app password, which Exchange Online and Outlook.com refuse. The platform's own mail also relies on an app password, from a domain with no SPF or DKIM (MAIL-E2, MAIL-E5).

## Corrections to the how-to guides

These documents supersede these statements:

* [PROVIDER_APP_REGISTRATION_GUIDE.md](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md) §4 step 5 lists `gmail.modify` and `gmail.send`. Request `gmail.modify` only, after Gmail moves to the Gmail API ([02](02_google.md) §3).
* The same guide's §5 step 4 says the mail permissions "need no admin consent by Microsoft's defaults". Under the Microsoft-managed default policy, users can't consent to `Mail.ReadWrite`, so an admin consents ([04](04_microsoft.md) §2).
* The same guide plans two Google projects. YouTube and Google Ads need a third, `hirebuddha-marketing`, which it doesn't describe yet ([09](09_youtube_and_google_ads.md) §4 and §6 A).
* [AI_MODEL_CREDENTIALS_GUIDE.md](../../how-to/AI_MODEL_CREDENTIALS_GUIDE.md) §14 sets up the platform's own mail with a Gmail app password. Use a transactional e-mail service on hirebuddha.com instead ([07](07_connectors_without_review.md) §1, MAIL-E5).

## Order of work

1. **Today.** Take the development server at `app.hirebuddha.com` off the internet (WEB-01), and give hirebuddha.com mail (WEB-02). Until then no provider, and no customer, can reach `support@` or `privacy@`.
2. **Start the clocks (week 1).** SH-01…SH-11 with the website fixes of [08](08_website_readiness.md) (WEB-03…WEB-11; counsel on SH-07/08). As soon as the websites identify the business: Meta business verification (META-02), Microsoft Partner Program enrolment (MS-01), the company's LinkedIn Page (SH-05).
3. **Engineering, in parallel (weeks 1–4).** The small fixes first (LI-E1, MS-E2, META-E2, GOOG-E2, META-E3, MAIL-E1, MAIL-E2, GADS-E2), then the connector changes (GOOG-E1, MS-E1, META-E1, MS-E3, GOOG-E3, GOOG-E4, YT-E1, GADS-E1), then the shared rules (SH-E1…SH-E6).
4. **Submissions, as each becomes possible:**
   * WhatsApp App Review (META-11); it can use Meta's API Setup page, so it needn't wait for our screens.
   * Google brand and Drive (GOOG-10), sign-in branding (GOOG-30).
   * Microsoft publisher verification (MS-12).
   * LinkedIn Development tier (LI-10), only when A and B of [03](03_linkedin.md) are right.
   * Meta Pages and Instagram (META-13), then Gmail (GOOG-11) with the CASA lab booked.
   * LinkedIn Standard tier (LI-20).
   * YouTube and Google Ads: brand verification of the marketing project (YT-10), then the scope verification (YT-11) and Google Ads Basic access (GADS-10); YouTube's audit (YT-12) before uploads outgrow 100 a day.
   * X (X-05) and GitHub at any time.
5. **After each approval:** the connector goes to *Preview*, then *Available*, and the approval is recorded on *Platform Console → Connectors* (the catalog's `approval` field).

## Code changes found (engineering backlog)

Size: S ≤ 1 day · M ≤ 1 week · L > 1 week. What is built, and what remains, is in [10](10_code_fix_plan.md).

| ID | Change | Size |
|----|--------|------|
| WEB-01 | Take the Vite development server at `app.hirebuddha.com` off the internet; rotate any secret it could read | S (today) |
| LI-E1 | One current `LinkedIn-Version` for the connector and the tools, with a staleness warning | S |
| GADS-E2 | One current Google Ads API version (v18 is sunset), with a staleness warning | S |
| MAIL-E1, MAIL-E2 | Mailbox: stop and notify when a password is refused; no Microsoft on the password path | S |
| MS-E2, META-E2, GOOG-E2 | Catalog scopes: add `User.Read`; add `pages_read_user_content` (and the Page Insights permission); Gmail to `gmail.modify` only | S |
| META-E3 | Check the Meta login product; use `config_id` if it is Facebook Login for Business | S |
| GOOG-E3 | Compare granted scopes with required ones; explain and re-ask | S |
| X-E1, X-E3, X-E5, X-E6 | X: replies gated, duplicate guard, priced posts, rate-limit handling | M |
| GH-E1 | GitHub installation suspend and repository-removed events | S |
| GOOG-E1 | Gmail through the Gmail API (poller, read, draft, send) | M |
| MS-E1, MS-E3 | Outlook through Microsoft Graph; the admin-consent path | M |
| META-E1 | Data deletion and deauthorise callbacks with a status page | M |
| META-E4, META-E5 | Messaging window, AI disclosure, hand-off; WhatsApp rules | M |
| GOOG-E4 | Google Picker for Drive files | M |
| LI-E3, LI-E4, LI-E5, X-E7 | LinkedIn and X: restricted uses, the comment and analytics views, one client per provider | M |
| MAIL-E3, MAIL-E4, MAIL-E5 | Mailbox presets and disconnect text; platform mail through a transactional service | M |
| WEB-05, WEB-06, WEB-12…WEB-14 | Websites: the data deletion page, `www.` certificates, `security.txt`, headers, a pre-rendered company site | M |
| YT-E1, GADS-E1 | YouTube and Google Ads connectors on the marketing project | M |
| YT-E2…YT-E6 | YouTube: upload contract, approvals, large uploads and the shared quota, data rules, analytics | M |
| GADS-E3…GADS-E6 | Google Ads: Demand Gen campaigns with video ads, spending approvals, reports, limits | L |
| SH-E1, SH-E4, SH-E6 | Disconnect deletes; approvals per connector action; staff access to connector content | M |
| SH-E2 | Retention by source (LinkedIn 24/48 h, X 24 h) over traces, memory and records | L |
| SH-E3 | Prompt-injection screening of connector content | L |
| SH-E5, GOOG-20…23 | Security baseline and the CASA assessment | L |

## How to use these documents

* Every requirement has an ID (`SH-`, `WEB-`, `META-`, `GOOG-`, `YT-`, `GADS-`, `LI-`, `MS-`, `X-`, `GH-`, `MAIL-`; an `E` marks engineering), an owner, what "done" means, and a **Status** column to update as you go (Open → In progress → Done).
* Each provider document has the requirements in order, draft texts for the forms, a recording script, the common rejections with their fixes, and its sources.

## How this was researched

* **Official documentation**, fetched on 28 Oct 2026: Google Cloud and Workspace policies, Meta for Developers, LinkedIn's documentation on Microsoft Learn, Microsoft Entra and Exchange documentation, X developer guidelines, GitHub docs.
* **Community reports**: Google Developer forums, Microsoft Q&A, X developer community, and practitioners' write-ups of rejections and fixes. Each document lists its sources, and secondary sources are marked as such.
* **Reddit could not be read from this environment**: the fetch tool and the in-app browser both refuse reddit.com. The rejection patterns come from the forums and write-ups above. Some of those quote Reddit threads, for example the end of free CASA self-scans in 2024.
* **The websites**: buddhalab.in and hirebuddha.com as served on 28 Oct 2026: certificates, DNS, every linked page, and the company site rendered in a browser ([08](08_website_readiness.md) §7).
* **The codebase**: the connector catalog, the provider adapters, the mail tools, poller and platform mail, the LinkedIn, X, YouTube and Google Ads tools, and the webhooks.
* Prices, limits and dates change; each provider's console is the final word.
