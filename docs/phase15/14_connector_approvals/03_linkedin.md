# 03 — LinkedIn: LinkedIn Page (Community Management API)

> **Researched:** 2026-10-28 · **Status:** Not submitted (catalog: `linkedin_org` is `planned`, approval `not_submitted`).
> **App:** one LinkedIn developer app, `HireBuddha`, associated with HireBuddha's LinkedIn Page (`oauth-app-linkedin`). How to create it: [provider guide §6](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md).
> **Lead time:** Development tier vetting, then a Standard tier review with a screencast: several weeks in total. **Cost:** free.
> **One-shot warning:** if either tier's request is rejected, you **can't re-apply from the same app**. You create a new app and start again at the Development tier. Close every item in A and B before submitting.

---

## 1. What LinkedIn checks

**Development tier** (the access request form): an approved use case, a verified business e-mail, a verified organisation (a registered legal entity with commercial use), a verified website and domain, and the app verified by a super admin of the organisation's LinkedIn Page. Personal e-mail addresses fail the vetting.

**Standard tier** (needed to serve Pages other than your own): an approved use case, a valid privacy policy, compliance with the Marketing API Terms, restrictions, security and **data storage requirements**, and a screencast that shows every use case named in the form. You also provide a company and product overview and test credentials.

Rules that apply to both:

* The app's name and logo must not contain any part of the LinkedIn or Microsoft names or logos ("Linked", "In").
* **Community Management API must be the only product on its app.** Don't add *Sign In with LinkedIn* or *Share on LinkedIn* to it; LinkedIn refuses the request otherwise.
* LinkedIn monitors approved apps and can suspend access for non-compliance after approval.

HireBuddha's use cases in LinkedIn's terms: **Page Management** (posting to the business's own Page) and **Page Analytics** (how the Page's posts perform). Not Brand Engagement, Executive Management or Employee Advocacy (those cover members' personal profiles).

## 2. LinkedIn's data rules that bind the product

| Data | May be kept | Applies to |
|---|---|---|
| Members' social activity: comments, mentions, members' posts and their metadata | **48 hours** | A comment on the business's post, read by an agent |
| Other members' profile data: name, headline, photo of someone who reacted or commented | **24 hours of caching**; never stored | Anything an agent shows about a commenter |
| Organisation's own posts (the authenticated organisation) | Six months | The business's own posts |
| Organisation profile data (authenticated organisation) | Eight weeks | The Page's name, logo, description |
| Page admin and reporting data (followers, post statistics; no member-level data) | One year | Analytics |
| IDs and URNs (posts, organisations, people) | No limit | References |

Restricted uses (Marketing API Terms and LinkedIn's restricted-use page): member data may not be used for **sales, recruiting or advertising**, including leads, CRM enrichment and audience lists; may not be **exported or transferred** (including to the business itself as a file); may not be **combined** with other data to build or enrich profiles; is shown only to people of that Page's business; and may not feed a website or intranet "social feed".

## 3. Requirements

### A. Eligibility and the app

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| LI-01 | The legal entity (SH-01) on the website with its address (SH-06), a real privacy policy (SH-07) and terms (SH-08). LinkedIn's identity vetting checks that the organisation is legally registered and active, and that the website is the organisation's own | Owner | SH-01, SH-06, SH-07 done | Open |
| LI-02 | Business e-mail on `hirebuddha.com` (SH-02); verify it when LinkedIn writes (check spam, social and promotions tabs) | Owner | Verified in the form | Open |
| LI-03 | The company's LinkedIn Page (SH-05) and a **super admin** ready to verify the app | Owner | — | Open |
| LI-04 | A **new app** with only *Community Management API* requested; name `HireBuddha`; logo without LinkedIn marks (SH-11); privacy policy URL | Owner | App created, no other product on it | Open |
| LI-05 | *Settings → Verify*: the Page's super admin approves the app | Owner | App shows *Verified* | Open |
| LI-06 | *Auth*: redirect URLs for the SH-12 hostnames; scopes `r_organization_social`, `w_organization_social`, `rw_organization_admin` once granted | Owner | Client ID handed to engineering | Open |

### B. Engineering before the Standard tier recording

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| LI-E1 | **API version past its sunset.** The connector sends `LinkedIn-Version: 202409` (hard-coded `LinkedInProvider.api_version`) and the LinkedIn tools send `LINKEDIN_API_VERSION = "202509"`. 202509 was sunset on 15 Sep 2026, 202409 a year earlier, and 202511 goes on 16 Nov 2026. Calls with a sunset version fail. Move both to **one setting** with a current version (202610 or newer), and warn at start-up when it is more than ten months old | `connections/providers/oauth.py`, `common/config.py`, `ai/tools/social/linkedin.py` | Listing organisations, posting and analytics work on dev | Done (code) |
| LI-E2 | **Retention** of §2 through SH-E2: LinkedIn member activity out of traces, tool outputs, memory and records after 48 h; member profile fields never stored, cached at most 24 h | Retention job, trace store, CORTEX memory | SH-E2's test with a LinkedIn comment | Done (code) |
| LI-E3 | **Restricted uses** in code: LinkedIn member data never written to records (CRM), partner leads, memory or exports (report CSV/XLSX/PDF, Data API); shown only inside that business | Tool output handling, records engine writes, report exports | A test: an agent asked to save a commenter as a lead is refused | Done (code) |
| LI-E4 | **What the screencast must show** exists in HireBuddha: posting to the Page (the tools post), how a comment on that post is shown to the business and which member fields appear, and the post's performance (the tools read `postStatistics` and `organizationalEntityShareStatistics`). If HireBuddha doesn't show comments, say so in the recording | Run view or a Page view; reports | Each step of §5 can be done on dev | Done (code); the screencast is open |
| LI-E5 | **One LinkedIn client.** The connector (`connections/providers/oauth.py`) and the older social tools (`ai/tools/social/linkedin.py`, with the legacy `social_connection_service` refresh) both call LinkedIn; the tools should use the connector's token and version only | `ai/tools/social/linkedin.py`, `connections/client.py` | No LinkedIn call outside the connector's credential path | Done (code) |
| LI-E6 | **Token life**: member access tokens last 60 days; approved apps may get programmatic refresh tokens. Without a refresh token, remind the business to reconnect before expiry | `connections/service.py`, notices | A notice 7 days before expiry | Done (code) |
| LI-E7 | Disconnect deletes the token and LinkedIn data (SH-E1; LinkedIn has no revocation endpoint) | `connections/service.py` | SH-E1's test with LinkedIn | Partly done (code) |

### C. Development tier

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| LI-10 | Access request form, every field exact: legal name and registered address (SH-01), website, privacy policy, business e-mail, the use case (§4) | Owner | Submitted | Open |
| LI-11 | Complete LinkedIn's vetting **survey within 21 days** of receiving it ([guide §6](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)) | Owner | Survey sent | Open |
| LI-12 | Development tier granted: test with HireBuddha's own and test Pages (SH-16) | Eng | Connect, post and analytics work | Open |

### D. Standard tier

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| LI-20 | Fully integrated (B done) on an environment that stays up (SH-15). Apply within a year of the Development tier: a practitioner guide reports access is removed for inactivity after twelve months without a Standard tier request | Owner + Eng | — | Open |
| LI-21 | Form (*My Apps → Products*): company and product overview, the use case (§4), **test credentials** for the reviewer (SH-14) | Owner | Submitted | Open |
| LI-22 | Screencast (§5): high resolution, a downloadable file, only HireBuddha's screens, narration | Eng | Uploaded with the form | Open |

### E. After approval

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| LI-30 | Connector to *Preview*, then *Available*; approval recorded on *Platform Console → Connectors* | Eng | Catalog row `approved` | Open |
| LI-31 | Upgrade the API version before each sunset (each version lasts about a year); read LinkedIn's deprecation notices | Eng | Calendar entry | Open |
| LI-32 | A change to the product's LinkedIn functionality may need a new review; ask before shipping one | Owner | — | Open |

## 4. Draft use case (form text)

> HireBuddha, by Buddha Cognitive Lab, is a workspace in which a company's AI employees draft posts for the company's own LinkedIn Page and report how those posts perform. A Page administrator connects the Page by signing in with LinkedIn. A person on the company's team approves every post before HireBuddha publishes it. HireBuddha shows the Page's post statistics (impressions, reactions, comments) to that company's team only. We do not use LinkedIn member data for sales, recruiting, advertising or lead generation, we do not export or combine it with other data, and we keep it no longer than LinkedIn's data storage requirements allow. Use cases: Page Management and Page Analytics.

## 5. Screencast script (Standard tier)

LinkedIn lists what each use case's recording must demonstrate. Narrate each step.

1. **OAuth**: in HireBuddha (reviewer business), *Connections → LinkedIn Page → Connect* → the in-app disclosure → LinkedIn sign-in → LinkedIn's consent screen → choose the Page (the organisations the member administers).
2. **Posting**: an AI employee drafts a post → the approval screen → *Approve* → **the post on the LinkedIn Page**.
3. **A member's comment on that post**: comment from a second account → an AI employee lists the post's comments (`linkedin_manage_comments`, action *list*) → open that run in *Work history*: the comment shows **the commenter's member URN, the text, the time and the like count, and no profile fields** (name, headline, photo are not read). Say that it stays in that run only: removed after 24 hours, never saved to records or memory (LI-E2, LI-E3), and that the AI employee's reply to it waits for a person's approval.
4. **Page analytics**: the post's performance (`linkedin_get_analytics`, *post*, the share statistics: impressions, clicks, reactions, comments, shares) in the run, matching LinkedIn; say that the statistics are the Page's own and no member-level data is shown.
5. **Any other use of member data**: say there is none, and show it: an AI employee asked to save the commenter as a lead is refused ("This run read data from LinkedIn Page, which may not be saved to records").
6. *Disconnect*: HireBuddha's *after disconnecting* note; what the runs read through the Page is removed on the next hourly pass.

## 6. Common rejections and how they were resolved

Sources: LinkedIn's app review page (official), Microsoft Q&A, practitioner write-ups (§7). Reddit could not be opened from this environment.

| Rejection or symptom | Usual cause | What fixed it |
|---|---|---|
| "Identity vetting failed: we were unable to verify that your organization is a legally registered, active entity" | The website given wasn't the organisation's own (one developer gave a documentation site); or the company is too new to appear in the business databases LinkedIn checks | Give the corporate website that shows the legal name and address (SH-06). For a new company, contact LinkedIn Developer Support with registration documents. One reported appeal was auto-rejected while the company was missing from those databases |
| Vetting fails on the e-mail | A personal address, or the verification mail never confirmed | SH-02, LI-02 |
| App not verified | The Page's super admin didn't approve it | LI-05 |
| "This API product requires that it be the only product on the application" | Sign In with LinkedIn or Share on LinkedIn added to the same app | A new app with only Community Management API (LI-04) |
| Use case unsupported | Described as lead generation, CRM sync, social listening of other Pages, a website feed, or posting to members' profiles | Describe Page Management and Page Analytics of the business's own Page only (§4) |
| Name or logo refused | Contains "Linked", "In" or the LinkedIn logo | SH-11 |
| Standard tier rejected for the screencast | A use case from the form not shown, or not fully integrated | Record every step of §5; integrate first (LI-20) |
| Wanting to fix and resubmit | Not possible with the same app | New app, new Development tier request (the one-shot warning above) |
| API calls fail with a version error | A sunset `LinkedIn-Version` | LI-E1 |

## 7. Sources

* LinkedIn (official, Microsoft Learn): [Community Management app review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review?view=li-lms-2026-10); [Restricted uses](https://learn.microsoft.com/en-us/linkedin/marketing/restricted-use-cases); [Data storage requirements](https://learn.microsoft.com/en-us/linkedin/marketing/data-storage-requirements); [Versioning](https://learn.microsoft.com/linkedin/marketing/versioning); [Recent changes (sunset dates)](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/recent-changes); [Community Management overview](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview)
* Forums and write-ups (secondary): [Identity vetting fails for a newly incorporated company (Microsoft Q&A)](https://learn.microsoft.com/en-us/answers/questions/5963210/community-management-api-identity-vetting-fails-fo); [LinkedIn API approval rejected: what they require (Richard Fu)](https://www.richardfu.net/linkedin-api-approval-rejected-organizational-website/); ["Only product on the application" error (Stackposts)](https://doc.stackposts.com/docs/stackposts-v9/problems-solutions/linkedin-this-api-product-requires-that-it-be-the-only-product-on-the-application-for-legal-and-security-reasons-15917/); [LinkedIn API approval process (SocialMeAI)](https://socialmeai.com/blog/linkedin-api-approval-process); [Community Management API access (singhamandeep)](https://singhamandeep.com/linkedin-community-management-api-access/)
* This repository: `backend/src/connections/catalog/linkedin_org.yaml`, `backend/src/connections/providers/oauth.py` (`LinkedInProvider`), `backend/src/ai/tools/social/linkedin.py`, `backend/src/common/config.py` (`LINKEDIN_API_VERSION`)
