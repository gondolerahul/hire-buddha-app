# 08 — Website readiness: buddhalab.in and hirebuddha.com

> **Checked:** 2026-10-28, from outside: HTTPS and certificates, DNS, every page linked from hirebuddha.com's homepage, and the main pages of buddhalab.in rendered in a browser (§7) · **Status:** Not ready. Neither site would pass a provider's review today, and the old app hostnames expose a development server (§5).
> **Why it matters:** Meta's business verification, LinkedIn's vetting and Microsoft's Partner Center compare the legal name, address and contact details on the website with the registration documents. Google reads the homepage, privacy policy and terms on the app's own domain. Each fix below (WEB-01…) closes part of an SH requirement of [00](00_shared_prerequisites.md).

---

## 1. Verdict

| Check | buddhalab.in (company) | hirebuddha.com (product) | Who looks |
|---|---|---|---|
| Loads over HTTPS | Yes | Yes | All |
| `www.` address | **Certificate error** | **Certificate error** | Anyone who types it |
| Legal name "Buddha Cognitive Lab Private Limited" | No: "© 2023 Buddha Cognitive Lab" | No: "© 2026 Buddha Cognitive Lab" | Meta, LinkedIn, Microsoft |
| Registered address | **Placeholder addresses** (§4) | None | Meta, LinkedIn |
| A contact address that receives mail | `contact@buddhalab.in` | **None**: the domain has no MX record, so the advertised `privacy@`, `hello@` and `enterprise@hirebuddha.com` can't receive mail | All |
| Privacy policy | Generic template; its contact is on a domain nobody owns | Template that says so | All |
| Terms | Generic template; San Francisco placeholder address | Template that says so | All |
| Data deletion page | — | 404 | Meta (required), Google, LinkedIn |
| Says what the app does with connected accounts | — | Only in general terms | Google |
| Company and product link to each other | **Broken link** to the product | Names the company, no link | Meta, LinkedIn, Google |
| Claims that can be backed up | **No** (§4) | Partly (§3) | All reviewers; consumer law |
| Domain verification records for Google, Meta, Microsoft | None found (no TXT record or meta tag) | None found (no TXT records at all) | Google, Meta, Microsoft |

## 2. How the two sites should fit together

The legal entity is **Buddha Cognitive Lab Private Limited**: its site is buddhalab.in and its mail runs on Google Workspace at buddhalab.in. The app every provider reviews is **HireBuddha**, on hirebuddha.com. Reviewers go from the registration documents (the company) to the app (the product), so both sites must make that chain obvious:

* **Accounts in the company's name:** the Meta business portfolio, the LinkedIn Page (`linkedin.com/company/buddha-cognitive-lab`, already linked from hirebuddha.com), Microsoft Partner Center, and Google Cloud's organisation and billing.
* **Apps named HireBuddha**, with the homepage, privacy policy and terms all on hirebuddha.com. Google requires them on the app's verified domain.
* **Each site names and links the other.** buddhalab.in's HireBuddha page and buttons link to `https://hirebuddha.com`. hirebuddha.com's footer says "HireBuddha is a product of Buddha Cognitive Lab Private Limited", with the registered office and CIN, and links to buddhalab.in.
* **Mail on hirebuddha.com** (WEB-02). Until it works, provider contacts must be `@buddhalab.in` addresses. That domain differs from the app's, which Microsoft's publisher verification rejects (MS-07), and Meta can then verify the business by e-mail only for buddhalab.in.
* **One domain per form.** In each provider form, use the same domain for the website, the e-mail and the domain check. Once WEB-02 is done, use hirebuddha.com everywhere. If Meta's business verification has to start sooner, use buddhalab.in, after WEB-03, WEB-04 and WEB-09 have fixed its pages.

## 3. hirebuddha.com (the product site)

A Next.js site, prerendered, on a Google Cloud VM (34.60.58.173, Apache 2.4.58). The same server also hosts buddhalab.in, `app.hirebuddha.com` and `gateway.hirebuddha.com` (§5). HTTP redirects to HTTPS.

**What works:** all 25 pages linked from the homepage answer, and they are prerendered, so crawlers and reviewers see the content without JavaScript. The homepage is public, explains the product and links *Privacy* and *Terms* in the footer. Basic security headers are set (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`). No analytics or advertising trackers on the pages checked, so no cookie banner is needed for them.

| # | Finding | Fix |
|---|---|---|
| 1 | `/privacy` and `/terms` are templates that say so: "Template content for demonstration. Replace with your reviewed legal policy before launch." The terms also say the binding contract "is provided during onboarding", but sign-up is self-serve, so there is none | WEB-04 |
| 2 | `/data-deletion` returns 404 (so do `/security` and `/legal`) | WEB-05 |
| 3 | **No MX record.** `privacy@hirebuddha.com` (named in the privacy page), `hello@` and `enterprise@` (the contact page's links) can't receive mail. No SPF or DMARC either, so anyone can send mail as hirebuddha.com, and the platform's own mail from `noreply@hirebuddha.com` has nothing to vouch for it ([07](07_connectors_without_review.md), MAIL-E5) | WEB-02 |
| 4 | No TXT records at all, and no verification meta tag on the homepage: hirebuddha.com hasn't been verified by DNS with Google Search Console, Meta or Microsoft | WEB-07 |
| 5 | No legal identity on any page: only "© 2026 Buddha Cognitive Lab", with no "Private Limited", registered address, CIN, phone or support address. `/contact` has only a lead form | WEB-03 |
| 6 | `www.hirebuddha.com` resolves, but the certificate covers only `hirebuddha.com` and `hirebuddha.in`, so browsers show a security error | WEB-06 |
| 7 | No way into the product: every *Get Started* opens the lead form (`/contact`, which posts to `/api/lead`). There's no *Sign in* or *Sign up* link to the app | WEB-11 |
| 8 | Integrations the product doesn't have: "Works with … Stripe · Plaid · DocuSign · Slack · Microsoft Teams" (homepage); "Salesforce", "Slack · Teams" with "Slack/Teams approval workflows", "Stripe · Plaid · Wise" and "DocuSign · Gusto" (`/for/enterprise`); "Slack / Teams", "Jira / Linear", "Apollo / Clearbit" (`/product/tools`); "SharePoint, Notion" (`/pragya`). Of all these, only HubSpot is a connector; none of the others is a connector or a tool in the code | WEB-09 |
| 9 | Customer names under "Trusted by companies…" (Saraswat Bank among them), and "India's first AI-native legal firm runs on HireBuddha" labelled "Illustrative deployment". Production had no live customers on 25 Oct (Phase 15 status) | WEB-09 |
| 10 | Copy that reads as training on customer data: "improve reliability through the Learning System" (privacy page), "Every run makes the system smarter", and "BabyBuddha — our flagship hybrid LLM, post-trained for agentic execution". Google asks whether Workspace data trains models, and Meta and LinkedIn ask the same | WEB-10 |
| 11 | Pragya (text and voice chat on the site) sends visitors' conversations to `wss://api.fluidbuddha.com`. The privacy policy doesn't mention the chat, voice recording or that service | WEB-04 |
| 12 | The counters render as "0+ industries", "0 arcs" and "0 attrition" until JavaScript animates them, so a crawler or an early screenshot shows zeros | WEB-09 |
| 13 | No `robots.txt` or `sitemap.xml` (404); `/.well-known/security.txt` answers 403 | WEB-12 |
| 14 | No `Strict-Transport-Security` or `Content-Security-Policy`; `Server: Apache/2.4.58 (Ubuntu)` and `X-Powered-By: Next.js` disclose versions. CASA's scans report all of these | WEB-13 |
| 15 | No cancellation and refund page (`/refund-policy` 404). No connector requires one, but Indian payment gateways such as Razorpay ask for it, together with the terms, privacy and contact pages | WEB-04 |

## 4. buddhalab.in (the company site)

A single-page React app built with Lovable, on the same server. The HTML it serves is an empty `<div id="root">`, so only browsers that run JavaScript see any content.

**What works:** Google Workspace mail on buddhalab.in with SPF and DMARC (`p=quarantine`). `/contact` gives `contact@buddhalab.in` and +91 93102 31302. `/about/company` names the founder and the head office in Nagpur.

| # | Finding | Fix |
|---|---|---|
| 1 | `/Privacy` and `/Terms` are generic templates whose contact is `privacy@buddhacognitive.com`, `legal@buddhacognitive.com` and "123 AI Boulevard, San Francisco, CA 94105". `buddhacognitive.com` isn't registered (no DNS), so that mail bounces, and whoever registers the domain would receive it | WEB-04, WEB-15 |
| 2 | The contact page's addresses come from a template: Noida "101 Market Street, Suite 1500", Navi Mumbai "550 Madison Avenue", Bengaluru "Roppongi Hills Mori Tower, 6-10-1 Roppongi" (an address in Tokyo), with opening hours in PT, ET, GMT and JST. Meta and LinkedIn compare the address with the documents | WEB-03 |
| 3 | "© 2023 Buddha Cognitive Lab": no "Private Limited", CIN or GSTIN, and an old year | WEB-03 |
| 4 | Both *Visit website* buttons for HireBuddha go to `https://www.hire.buddhalab.in/`, which doesn't exist | WEB-08 |
| 5 | Claims a reviewer can't verify, several of which look like template content: testimonials from "Sarah Johnson, CFO, UBS", "Rajesh Mehta, CTO, Aditya Birla Capitals" and "Michael Chen, Head of Analytics, QuantMutual"; "Trusted by industry leaders" with UBS, Bajaj Finance, BankBazaar, PolicyBazaar and others; "Forbes Top 10 AI Startups 2023", although the About page says the company was founded in 2024; "15 Patents \| 50+ Papers"; "Leading hospitals using our AI"; a case study for "AutoCorp" | WEB-09 |
| 6 | "Partner" labels for programmes the company hasn't joined: "Intelligence Partner: OpenAI, Anthropic, Google, Microsoft, Meta, Deepseek", "Communication Partner: … WhatsApp", "Cloud Partner: Google Cloud Platform, Microsoft Azure". Meta's policies forbid implying a partnership with or endorsement by Meta, Facebook, Instagram or WhatsApp, and Meta's partner badge is only for partners it has approved. Google and Microsoft have the same rule for their names | WEB-09 |
| 7 | `www.buddhalab.in` resolves, but the certificate covers only `buddhalab.in` and `buddhacognitivelab.com` | WEB-06 |
| 8 | Share previews are broken: the meta description reads "Todards Digital Enlightment", and the `og:image` URL returns the HTML page instead of the image, so LinkedIn and WhatsApp previews show no picture | WEB-14 |
| 9 | No DKIM key at Google's default selector (`google._domainkey.buddhalab.in`), so DMARC rests on SPF alone, and forwarded mail fails it | WEB-02 |

## 5. The app hostnames point at the old server

* `app.hirebuddha.com` and `gateway.hirebuddha.com` resolve to the same Google Cloud VM as the websites, not to production on Azure (`app.azprod.hirebuddha.com` and `gateway.azprod.hirebuddha.com`, 4.213.163.10).
* **`app.hirebuddha.com` is served by the Vite development server**: the page loads `/@vite/client` and `/src/main.tsx`, and both return code. A development server publishes the frontend source, and several 2025 Vite advisories let a dev server that is reachable from the network be made to return other files from its machine.
* `gateway.hirebuddha.com/health` answers as an old build ("unified-gateway" 2.0.0).
* The provider guide registers redirect URIs and webhooks on `gateway.hirebuddha.com`, which today is this old server. SH-12 decides the hostnames. WEB-01 removes the exposure now, whatever SH-12 decides.

## 6. Fixes

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| WEB-01 | **Take the development server off the internet now**: stop it, or point `app.` and `gateway.hirebuddha.com` at production (SH-12). Look on that server for secrets the dev server could read (`.env` files, keys) and rotate any you find | Eng | `app.hirebuddha.com` no longer serves `/src/` or `/@vite/client` | Open |
| WEB-02 | **Mail on hirebuddha.com**: add the domain to the existing Google Workspace as a secondary domain; MX, SPF, DKIM and DMARC records at GoDaddy; groups for `support@`, `privacy@`, `security@`, `admin@`, `hello@` and `enterprise@` (SH-02). Turn on DKIM for buddhalab.in too | Owner | A test mail to each address arrives, and DMARC passes for both domains | Open |
| WEB-03 | **Legal identity on both sites** (footer and contact page): "Buddha Cognitive Lab Private Limited", the registered office as on the certificate of incorporation and GST, CIN, GSTIN, phone and support e-mail; real offices only, with Indian opening hours. On hirebuddha.com, add "HireBuddha is a product of Buddha Cognitive Lab Private Limited" linked to buddhalab.in (SH-01, SH-06) | Owner + Eng | The values match SH-01 character for character | Open |
| WEB-04 | **Replace the legal pages.** On hirebuddha.com, `/privacy` and `/terms` as SH-07 and SH-08 describe (counsel to review), covering the website chat (Pragya, `api.fluidbuddha.com`), voice and the lead form too. On buddhalab.in, rewrite `/Privacy` and `/Terms` with the real entity and contacts, or redirect them to hirebuddha.com's. Add a cancellation and refund page | Owner + Counsel | No template wording or placeholder address is left on either site | Open |
| WEB-05 | `/data-deletion` on hirebuddha.com (SH-09) | Eng | The page answers | Open |
| WEB-06 | Certificates for `www.` on both sites, with a redirect to the bare domain | Eng | `https://www.hirebuddha.com` and `https://www.buddhalab.in` redirect without a warning | Open |
| WEB-07 | Domain verification records for Google Search Console, Meta and Microsoft (SH-03); buddhalab.in too if Meta's business verification uses it (§2) | Owner | Each console shows the domain verified | Open |
| WEB-08 | buddhalab.in's HireBuddha buttons link to `https://hirebuddha.com` | Eng | — | Open |
| WEB-09 | **Remove or back up every claim.** On buddhalab.in: testimonials, client logos, awards, patent and paper counts and case studies that aren't real and permitted; "Partner" labels become "Built with" or "Uses models from" unless an agreement says otherwise. On hirebuddha.com: integrations that aren't built (Stripe, Plaid, Wise, DocuSign, Gusto, Salesforce, Slack, Teams, Jira, Linear, Apollo, Clearbit, SharePoint, Notion): drop the names, or say plainly that the Meta Agent can build a tool for a system; and customer logos without written permission. Render the counters' final values on the server | Owner | Each remaining claim has a source noted in the tracker | Open |
| WEB-10 | **Say what HireBuddha's learning does with customer data**, on the homepage, the product pages and in the privacy policy: learning is per business, and connected-account data (Gmail, Drive, YouTube, Meta, LinkedIn, X) never trains BabyBuddha or any shared model (SH-07 §5, GOOG-E6) | Owner + Counsel | The copy matches GOOG-E6's data-flow note | Open |
| WEB-11 | **Homepage, for Google's review**: name the connections and what each one does ("reads and answers your Gmail", "publishes to your YouTube channel", …), and add *Sign in* to the production app (SH-06, SH-12) | Owner + Eng | — | Open |
| WEB-12 | `/.well-known/security.txt` naming `security@`; a security page with the sub-processor list (SH-10); `robots.txt` and `sitemap.xml` | Eng | — | Open |
| WEB-13 | Headers: HSTS on both sites and the app hostnames, a Content-Security-Policy, and no `Server` version or `X-Powered-By` (SH-E5) | Eng | A header scan shows them | Open |
| WEB-14 | Company site: pre-render the pages (the Lovable build serves an empty page to anything that doesn't run JavaScript); fix the meta description and the `og:image` | Eng | `curl https://buddhalab.in` returns the page's text | Open |
| WEB-15 | Register `buddhacognitive.com`, named in the old legal pages, so nobody else can receive mail sent to it (or confirm it's held) | Owner | — | Open |

## 7. How this was checked

* Status codes, redirects and headers with `curl`; certificate names with `openssl s_client`.
* DNS (MX, TXT, DMARC, DKIM, A records) against a public resolver (8.8.8.8).
* hirebuddha.com's text from the HTML the server sends, because its pages are prerendered. buddhalab.in's text from the in-app browser, because the page needs JavaScript.
* Pages: all 25 linked from hirebuddha.com's homepage; on buddhalab.in, the homepage, `/Privacy`, `/Terms`, `/contact`, `/about/company` and `/products/hirebuddha`; on both, the links in the footers. Also `/data-deletion`, `/security`, `/legal`, `/refund-policy`, `robots.txt`, `sitemap.xml` and `security.txt` on hirebuddha.com.
* Integration claims against `backend/src/connections/catalog/` and `backend/src/ai/tools/`.
* Re-run these checks before each provider submission. Reviewers see the live site on the day they look.
