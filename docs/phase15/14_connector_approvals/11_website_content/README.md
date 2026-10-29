# 11 — Website content: legal pages and site-wide changes

> **Written:** 2026-10-28 · **Status:** Drafts for counsel's review; nothing published. The website changes themselves are a separate piece of work: this folder gives the content and the list of changes.
> **Covers:** SH-06…SH-10 of [00](../00_shared_prerequisites.md) and WEB-02…WEB-15 of [08](../08_website_readiness.md).

## 1. The pages

| Site | URL | File | Replaces | Read by |
|---|---|---|---|---|
| hirebuddha.com | `/privacy` | [hirebuddha.com/privacy.md](hirebuddha.com/privacy.md) | The template that says "Replace … before launch" | Google (consent screen, Gmail, YouTube audit), Meta, LinkedIn, Microsoft, X, GitHub |
| hirebuddha.com | `/terms` | [hirebuddha.com/terms.md](hirebuddha.com/terms.md) | The template | All of them; Razorpay |
| hirebuddha.com | `/data-deletion` | [hirebuddha.com/data-deletion.md](hirebuddha.com/data-deletion.md) | Today's 404 | Meta (required), Google, LinkedIn |
| buddhalab.in | `/privacy` (redirect `/Privacy`) | [buddhalab.in/privacy.md](buddhalab.in/privacy.md) | The template with `privacy@buddhacognitive.com` and a San Francisco address | Meta and LinkedIn business checks |
| buddhalab.in | `/terms` (redirect `/Terms`) | [buddhalab.in/terms.md](buddhalab.in/terms.md) | The template with the same placeholders | Same |
| buddhalab.in | `/data-deletion` | [buddhalab.in/data-deletion.md](buddhalab.in/data-deletion.md) | New | Same |

hirebuddha.com's pages cover everything the providers check: Google's Limited Use and Workspace AI statements, YouTube API Services (the YouTube Terms of Service sentence, the Google Privacy Policy link, revocation, the 30-day and 7-day rules), Meta's deletion paths, LinkedIn's storage limits and restricted uses, X's deletion and no-training rules, WhatsApp's rules for businesses, Google Ads' advertiser terms, India's DPDP Act and IT Act (Grievance Officer), and the GDPR. buddhalab.in's pages cover only the company website and point to HireBuddha's for the product.

## 2. Before you publish

### 2.1 Values to fill

| Placeholder | Where to find it | Pages |
|---|---|---|
| `[CIN]`, `[REGISTERED OFFICE ADDRESS …]` | The certificate of incorporation, character for character (SH-01) | All six |
| `[CITY OF THE REGISTERED OFFICE]` | Same; it sets the courts and the seat of arbitration | Both terms |
| `[NAME]`, `[DESIGNATION]`, `[grievance@…]`, `[PHONE]` | The Grievance Officer the company appoints (Information Technology Act rules; DPDP Act) | All six |
| `[EFFECTIVE DATE]`, `[LAST UPDATED DATE]` | The publication date | All six |
| `[CONFIRM: …]` in privacy §5 and §9 | The AI, telephony and e-mail providers actually enabled in production | hirebuddha.com privacy |
| Pragya's transcript retention | What api.fluidbuddha.com keeps, and for how long | hirebuddha.com privacy §3 |
| `[24 MONTHS]`, `[12 MONTHS]` | The retention the company chooses for enquiries and applications | Both privacy pages |
| Analytics | What, if anything, each site measures | Both privacy pages |
| `Settings → Team` | The app's menu name for removing a user | hirebuddha.com data deletion |

### 2.2 Statements that need the product to match first

A privacy policy is a promise. Each line below is true only once its engineering item is live in production ([10](../10_code_fix_plan.md)).

| Statement | Item | State (29 Oct 2026) |
|---|---|---|
| A person approves every message, post, reply, upload or campaign change before it goes out | SH-E4 | Built |
| Disconnecting deletes the tokens and the events stored from the account | SH-E1 | Built; what runs read through it goes on the next hourly pass (SH-E2) |
| Outside content is screened for prompt injection; an attack is withheld | SH-E3 | Built. Withholding needs Prompt Shields configured in production (`CONTENT_SAFETY_ENDPOINT`, `CONTENT_SAFETY_KEY_NAME`); without it the pattern check only flags |
| Meta's deletion request gives a confirmation code and a status page | META-E1 | Built |
| Gmail through the Gmail API; Outlook through Microsoft Graph | GOOG-E1, MS-E1 | Built |
| Messenger replies only within 24 hours; automated replies say they come from an AI assistant; a person can take over | META-E4 | Built |
| LinkedIn 48 h / 24 h, X 24 h, YouTube 30 days and 7 days; LinkedIn post statistics a year | SH-E2 | Built (LinkedIn and X kept at most 24 hours; YouTube 30 days, its analytics while connected) |
| Staff don't read connected-account content without a grant | SH-E6 | Built: Settings → Support access |
| No training on customer or connected data; learning stays in each business | GOOG-E6 | Written: [12](../12_data_flow_note.md). **The owner confirms** the BabyBuddha sentence and the training settings of any direct model-provider key (12 §2) |
| WhatsApp templates only to opted-in customers; no general-purpose assistant | META-E5 | Built |
| X posts billed per post | X-E5 | Built; staff set the registry prices `x_post` and `x_post_link` |
| A published list of sub-processors | SH-10 | **Open**: publish `/subprocessors` |

### 2.3 Addresses the pages name

They must receive mail before publishing (WEB-02): `privacy@`, `support@`, `security@`, `billing@`, `legal@` and `grievance@hirebuddha.com`; `privacy@`, `contact@` and `grievance@buddhalab.in`.

## 3. Site-wide changes for both sites

1. **Footer on every page**: "© 2026 Buddha Cognitive Lab Private Limited", CIN, registered office, support e-mail and phone; links to Privacy, Terms, Data deletion and the Grievance Officer (WEB-03).
2. **Contact page**: the registered office and real offices only, opening hours in IST, an e-mail address that receives mail, the phone number, the Grievance Officer. Remove the template addresses (Market Street, Madison Avenue, Roppongi Hills) and the PT/ET/GMT/JST hours (WEB-03).
3. **Legal pages** at stable lowercase URLs, each with its "Last updated" date; keep past versions available on request (WEB-04).
4. **Mail**: hirebuddha.com added to Google Workspace with MX, SPF, DKIM and DMARC; DKIM for buddhalab.in; the groups of §2.3 (WEB-02).
5. **Certificates** for `www.` on both domains, redirecting to the bare domain; **HSTS**; a Content-Security-Policy; no `Server` version or `X-Powered-By` (WEB-06, WEB-13).
6. **`/.well-known/security.txt`** naming `security@hirebuddha.com`; `robots.txt` and `sitemap.xml` (WEB-12).
7. **Claims**: every testimonial, customer logo, award, count, case study and integration name either backed by a source (and, for customers, written permission) or removed; "Illustrative" content labelled as such; no "Partner" label for a programme not joined (WEB-09).
8. **Each site links the other**: buddhalab.in's HireBuddha buttons to `https://hirebuddha.com`; hirebuddha.com's footer "HireBuddha is a product of Buddha Cognitive Lab Private Limited" to buddhalab.in (WEB-03, WEB-08).
9. **A notice under every form** (contact, demo, newsletter, waitlist, careers, Pragya): what the data is used for, and a link to the privacy policy. Newsletter sign-up confirmed by e-mail.
10. **Cookies**: no banner is needed while neither site uses analytics or advertising cookies. If one is added, add a consent banner that blocks it until accepted, and name it in the privacy policy.
11. **Same name and logo** as the provider apps (`HireBuddha`; SH-11).

## 4. hirebuddha.com

1. Publish `/privacy`, `/terms` and `/data-deletion` from §1.
2. **Homepage** (Google's brand review reads it, WEB-11): a "Connections" section naming each connection and what it does ("reads and answers your Gmail", "publishes to your YouTube channel", "posts to your LinkedIn Page", …), and **Sign in** linking to the production app (SH-12).
3. **New pages**: `/subprocessors` (the table of privacy §9, SH-10); `/refund-policy` (Terms §8–§9 as a page: Razorpay asks for it); a short **shipping and delivery** note (HireBuddha is an online service, delivered on sign-up; nothing is shipped), which Razorpay's checks also ask for.
4. **`/product/security`**: add `security@hirebuddha.com`, how to report a vulnerability, the hosting region (Azure Central India) and a link to `/subprocessors`.
5. **Pragya**: before the microphone opens, say that the conversation is with an AI, that voice is turned into text to answer, and link the privacy policy.
6. **Learning copy** (WEB-10): change "improve reliability through the Learning System" and "Every run makes the system smarter" to say that learning stays inside each business, and that connected-account data never trains BabyBuddha or any shared model.
7. **Integrations** (WEB-09): remove Stripe, Plaid, Wise, DocuSign, Gusto, Salesforce, Slack, Teams, Jira, Linear, Apollo, Clearbit, SharePoint and Notion until each exists, or say the Meta Agent can build a tool for a system.
8. **Pricing** matches Terms §8: daily credits expire the same day, top-ups last 365 days, prices exclude GST.
9. **Counters** rendered with their final values on the server (no "0+ industries").
10. Remove the template sentence "the binding contract … is provided during onboarding" (the Terms now bind).

## 5. buddhalab.in

1. Replace `/Privacy` and `/Terms` with §1's pages (redirect the old URLs) and add `/data-deletion`.
2. **Footer**: "© 2026 Buddha Cognitive Lab Private Limited" (not "© 2023 Buddha Cognitive Lab").
3. **HireBuddha's "Visit website" buttons** → `https://hirebuddha.com` (today `www.hire.buddhalab.in`, which does not exist) (WEB-08).
4. **Testimonials and logos** ("Sarah Johnson, CFO, UBS", "Michael Chen, QuantMutual", UBS, Bajaj Finance, BankBazaar, PolicyBazaar …), **"Forbes Top 10 AI Startups 2023"** (the About page says the company was founded in 2024), **"15 Patents | 50+ Papers"**, hospital and fraud figures, the "AutoCorp" case study: keep only what is true and permitted (WEB-09).
5. **Partner labels**: "Intelligence Partner: OpenAI, Anthropic, Google, Microsoft, Meta, Deepseek", "Communication Partner: … WhatsApp", "Cloud Partner …" become "Built with" or "Uses models from", unless an agreement says otherwise (WEB-09).
6. **Pre-render** the pages (the Lovable build serves an empty page to crawlers); fix the meta description ("Todards Digital Enlightment") and the `og:image` URL (WEB-14).
7. Register `buddhacognitive.com`, which the old pages named, or confirm it is held (WEB-15).

## 6. Where each URL goes in the provider consoles

| Console | Field | URL |
|---|---|---|
| Google Cloud (both projects) → Branding | Homepage, Privacy policy, Terms of service | `https://hirebuddha.com`, `/privacy`, `/terms` |
| YouTube audit form (YT-12) | Privacy policy, Terms | `/privacy`, `/terms` |
| Meta app → Settings → Basic | Privacy policy URL, Terms of service URL | `/privacy`, `/terms` |
| Meta app → Settings → Basic → User data deletion | Data deletion request URL (callback, META-E1) | `https://<gateway>/webhook/provider/meta/data-deletion` |
| Meta app → Facebook Login settings | Deauthorize callback URL | `https://<gateway>/webhook/provider/meta/deauthorize` |
| LinkedIn app → Settings | Privacy policy URL | `/privacy` |
| Microsoft Entra → Branding & properties | Home page, Terms of service, Privacy statement | `https://hirebuddha.com`, `/terms`, `/privacy` |
| X developer console → User authentication | Website, Terms of service, Privacy policy | `https://hirebuddha.com`, `/terms`, `/privacy` |
| GitHub App → public page | Homepage, Privacy policy | `https://hirebuddha.com`, `/privacy` |
| Razorpay → Website details | Terms, Privacy, Refund and cancellation, Contact, Shipping and delivery | `/terms`, `/privacy`, `/refund-policy`, `/contact`, the delivery note |

`<gateway>` is the production API hostname that SH-12 settles.
