# Registering HireBuddha's apps with Meta, LinkedIn, Google, Microsoft, X and GitHub

> **Updated:** 2026-10-20 · **Phase 14 item:** WS5 5.9 (status doc §5.5, M5-1)
> **Who does this:** the owner (accounts, legal details, consoles), with engineering for the last step of each provider.
> **Why now:** a business connects its Facebook Page, Instagram, WhatsApp number, LinkedIn Page, Gmail, Outlook, X account or GitHub **through HireBuddha's own app** with each provider. The code is ready (connectors, OAuth, token broker, webhooks), but no connector can be switched on until HireBuddha's apps exist and the providers have approved them. Meta, Google and LinkedIn reviews take weeks, so start them before the screens are finished.

---

## 1. Overview

| Provider | What you register | Review | Typical lead time | Cost | Unlocks |
|----------|-------------------|--------|-------------------|------|---------|
| **Meta** | One Business app: WhatsApp (Tech Provider, partner solution with **Tata**), Facebook Pages, Instagram | Business verification + App Review (Advanced access) | 2–6 weeks (verification 2–10 days, review 1–3 weeks per submission) | Free; WhatsApp messages billed on Tata's credit line | WhatsApp Business, Facebook Pages, Instagram connectors |
| **Google** | A Google Cloud project with an OAuth client | Brand verification; sensitive-scope review; **restricted-scope review + CASA security assessment** for Gmail | Drive: 1–2 weeks. Gmail: 3–8 weeks | Drive free. Gmail: a CASA Tier 2 assessment by an authorised lab, about US$540–6,000 a year | Google Drive; Gmail |
| **Microsoft** | A multi-tenant app registration in Entra ID | Publisher verification (through the free Microsoft AI Cloud Partner Program) | 1–2 weeks | Free | Outlook / Microsoft 365 mail |
| **LinkedIn** | A developer app on HireBuddha's LinkedIn Page, product **Community Management API** | Development tier form (and survey within 21 days), then Standard tier review with a screen recording | 2–6 weeks | Free | LinkedIn Page |
| **X** | A project and app in the X developer console | None | 1 day | **Pay per use** (credits; posting roughly US$0.015 a post, more with a link — check the console) | X account |
| **GitHub** | Two GitHub Apps (dev, prod) in HireBuddha's GitHub organisation | None for a public app | 1 hour | Free | GitHub (code lanes, app repositories) |

**Suggested order:** Meta business verification and Google brand/domain verification **today** (they gate everything else) → book the CASA lab → LinkedIn form → Microsoft Partner Program → GitHub → X when posting to X is wanted.

---

## 2. Before you start: what every provider asks for

Gather these once; most forms ask for the same things.

| Item | Value / where | Status |
|------|---------------|--------|
| Legal entity name, registration number, registered address, phone | Certificate of incorporation, GST, PAN | Owner to gather |
| A business e-mail on the company domain | e.g. `admin@hirebuddha.com` (not Gmail/Outlook) | — |
| Website | `https://hirebuddha.com` | Live |
| Privacy policy URL | `https://hirebuddha.com/privacy` | Live — **update it** to name each provider's data HireBuddha reads (Gmail, Outlook mail, Pages, Instagram, WhatsApp messages, LinkedIn Page posts, GitHub repositories), why, how long it is kept, and how a business disconnects |
| Terms of service URL | `https://hirebuddha.com/terms` | Live |
| **Data deletion instructions URL** (Meta requires it) | e.g. `https://hirebuddha.com/data-deletion` | **Missing** — a page explaining how a business disconnects (Connections → Disconnect) and asks for deletion (support e-mail) |
| App icon | 1024 × 1024 PNG, plus a 512 × 512 | — |
| Support e-mail | e.g. `support@hirebuddha.com` | — |
| A test business and test accounts | A test Facebook Page, Instagram professional account, WhatsApp test number, LinkedIn test Page, Gmail and Outlook test mailboxes | For the review videos |
| Screen recordings | Made on **Azure dev** (`https://app.azdev.hirebuddha.com`) once each connector is switched on there in preview | Engineering helps |

### Addresses HireBuddha uses with every provider

The API answers OAuth returns and webhooks on its public name (dev decision of 20 Oct: `gateway.` only).

| Environment | OAuth redirect / callback URL | Webhook URL |
|-------------|-------------------------------|-------------|
| Dev (Azure) | `https://gateway.azdev.hirebuddha.com/oauth/callback/<provider>` | `https://gateway.azdev.hirebuddha.com/webhook/provider/<provider>` |
| Production | `https://gateway.hirebuddha.com/oauth/callback/<provider>` | `https://gateway.hirebuddha.com/webhook/provider/<provider>` |

`<provider>` is exactly `meta`, `google`, `microsoft`, `linkedin`, `x` or `github`. The browser-side domains (for Meta's JavaScript SDK) are `app.azdev.hirebuddha.com` and `app.hirebuddha.com`.

### One app or two?

| Provider | Recommendation | Why |
|----------|----------------|-----|
| Meta | **One** app (production), both domains and both callback URLs on it; a Meta *test app* of it for dev if needed | Business verification, Tech Provider status and App Review belong to one app; doing them twice doubles the wait |
| Google | **Two** projects: `hirebuddha-connect` (production, verified) and `hirebuddha-connect-dev` (left in *Testing*, up to 100 test users, no verification) | Keeps the restricted-scope review on one project; dev needs no review. Keep both apart from the Vertex AI project |
| Microsoft | **Two** registrations (dev, prod) | Free and instant; the secret of each stays in its own vault |
| LinkedIn | **One** app with both redirect URLs | The review is per app |
| X | **One** app with both callback URLs | No review; one bill |
| GitHub | **Two** Apps (`HireBuddha Dev`, `HireBuddha`) | Webhooks go to one URL per App |

### Where secrets go (never e-mail or chat them)

Client secrets, private keys and tokens go **straight into Key Vault** — dev: `kv-hb-dev-ac48`; production: its own vault once production exists. In the Azure portal: **Key vaults → kv-hb-dev-ac48 → Objects → Secrets → + Generate/Import**, enter the name below and paste the value, **Create**. Then tell engineering the *name* only.

| Secret name | Value |
|-------------|-------|
| `oauth-meta-app-secret` | Meta app secret |
| `oauth-meta-verify-token` | A random string you make up (32+ characters); also typed into Meta's webhook form |
| `oauth-google-client-secret` | Google OAuth client secret |
| `oauth-microsoft-client-secret` | Entra client secret |
| `oauth-linkedin-client-secret` | LinkedIn primary client secret |
| `oauth-x-client-secret` | X OAuth 2.0 client secret |
| `oauth-github-client-secret` | GitHub App client secret |
| `oauth-github-private-key` | The GitHub App's `.pem` file contents |
| `oauth-github-webhook-secret` | A random string you make up; also typed into the GitHub App form |

---

## 3. Meta — WhatsApp as a Tech Provider with Tata, plus Facebook Pages and Instagram

### 3.1 How the Tata partnership works

HireBuddha becomes a **Tech Provider** that works with **Tata as its Solution Partner** through a Meta **Multi-Partner Solution**:

* HireBuddha's Meta app creates a *partner solution* by entering **Tata's Meta app ID**; Tata accepts it in its own App Dashboard.
* HireBuddha hosts WhatsApp **Embedded Signup** with that solution's ID. A business that completes it grants its WhatsApp assets to **both** HireBuddha and Tata.
* Messages of businesses onboarded this way are billed on **Tata's credit line** (a Tech Provider alone has none; each business would otherwise add its own card).
* Limit: a Tech Provider in a solution onboards up to **200 new businesses per rolling week**.
* Later, with volume and quality, Meta can upgrade a Tech Provider to **Tech Partner**; that is a separate step, not part of this guide.

**Ask Tata (your account manager) for, before you start:**

1. Tata's **Meta app ID** (the Solution Partner app that will be in the solution).
2. Agreement on a **solution name** (both dashboards show it), e.g. `HireBuddha x Tata`.
3. Who **creates** the solution (this guide assumes HireBuddha) and who **hosts Embedded Signup** (HireBuddha).
4. Which app **sends messages** for onboarded businesses: *Only me* (HireBuddha's app sends; recommended, since HireBuddha's code sends and receives through its own app) or *Only my partner*.
5. The commercial terms: credit line, per-message mark-up, invoicing, support and SLA, offboarding.
6. Whether Tata will help with the App Review videos through its existing integration (Meta accepts that).

### 3.2 Business portfolio and verification (start today)

1. Go to [business.facebook.com](https://business.facebook.com) → create (or choose) the **HireBuddha business portfolio** under the legal entity's name. Add a second admin so the account is never single-person.
2. **Business settings → Security Centre → Start verification**: business name, address, phone, website, the business e-mail; confirm by e-mail/phone/domain; upload documents if asked (certificate of incorporation, GST). Usually 2–10 working days.
3. Also verify the domain: **Business settings → Brand safety → Domains → Add** `hirebuddha.com` → TXT record at GoDaddy (DNS → Add New Record → TXT, Name `@`, value as shown) → **Verify**.

### 3.3 Create the app

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create app** → name `HireBuddha`, contact e-mail → use cases:
   * **Connect with customers through WhatsApp**
   * **Manage everything on your Page** (Facebook Pages)
   * **Manage messaging & content on Instagram**
   → connect the **HireBuddha business portfolio** → create.
2. **App settings → Basic**: app icon, category (Business and pages / Messaging), **Privacy policy URL**, **Terms of service URL**, **User data deletion → Data deletion instructions URL**, **App domains**: `hirebuddha.com`, `azdev.hirebuddha.com`. Copy the **App ID** and **App secret** (secret → Key Vault `oauth-meta-app-secret`).

### 3.4 Tech Provider onboarding, with Tata

1. App Dashboard → **Use cases → WhatsApp → Customize → Tech Provider onboarding**.
2. Step 1 (business verification) shows complete once §3.2 is done.
3. At the bottom choose **Onboard with a Solution Partner**, enter **Tata's app ID** and the agreed solution name, choose who sends messages → **Create a partner solution**. It shows **Pending** in **WhatsApp → Partner solutions** until Tata accepts; then **Active**. Copy the **solution ID**.
4. **App Review** for WhatsApp (Advanced access to `whatsapp_business_messaging` and `whatsapp_business_management`). Two videos:
   * a message created and sent, and received on a phone's WhatsApp;
   * a message template being created.
   Meta accepts, instead of HireBuddha's own screens, the **API Setup** page's cURL sending to your test number and **WhatsApp Manager** creating a template — or Tata's existing integration. That is the fastest route: submit this first.

### 3.5 Facebook Login for Business, Embedded Signup and webhooks

1. **Facebook Login for Business → Settings → Client OAuth settings**: turn on Client OAuth login, Web OAuth login, Enforce HTTPS, Embedded browser OAuth login, Use Strict Mode for redirect URIs, **Login with the JavaScript SDK**.
   * **Allowed domains for the JavaScript SDK:** `https://app.azdev.hirebuddha.com`, `https://app.hirebuddha.com`
   * **Valid OAuth redirect URIs:** `https://gateway.azdev.hirebuddha.com/oauth/callback/meta`, `https://gateway.hirebuddha.com/oauth/callback/meta`
2. **Facebook Login for Business → Configurations → Create from template → "WhatsApp Embedded Signup Configuration With 60 Expiration Token"** (Embedded Signup **v4**: Meta retired v2/v3 on 15 Oct 2026). Select only the assets HireBuddha uses (WhatsApp accounts; not catalogs or ad accounts). Copy the **configuration ID**.
3. **Webhooks** (Use cases → WhatsApp → Configuration, and the Page / Instagram use cases): **Callback URL** `https://gateway.azdev.hirebuddha.com/webhook/provider/meta` (production later: `gateway.hirebuddha.com`), **Verify token** = the value you put in Key Vault as `oauth-meta-verify-token` → **Verify and save** (HireBuddha must be running: it answers Meta's check). Subscribe to:
   * WhatsApp Business Account: `messages`, `account_update`, `partner_solutions`
   * Page: `feed`, `messages`
   * Instagram: `comments`, `messages`

### 3.6 App Review for Pages and Instagram (after the screens run on dev)

Request **Advanced access** for: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `pages_manage_metadata`, `pages_messaging`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages` (and `business_management` if Meta asks for it with Embedded Signup).

For each permission Meta wants a screen recording **in HireBuddha** that shows: signing in with Facebook, the permission being granted, and the feature that uses it (posting to a Page, replying to a comment, answering an Instagram DM). Record on Azure dev with the test Page and Instagram account once engineering has switched those connectors to *Preview* there. Describe each use in one or two plain sentences; request nothing the product does not use. Rejections are common on the first try — read the reviewer's notes and resubmit.

### 3.7 What to hand to engineering

| Setting | Value |
|---------|-------|
| App ID | from App settings → Basic |
| Embedded Signup configuration ID | §3.5 step 2 |
| Partner solution ID (Tata) | §3.4 step 3 |
| Graph API version | `v26.0` (the current one when this was written) |
| Secrets in Key Vault | `oauth-meta-app-secret`, `oauth-meta-verify-token` |

---

## 4. Google — Gmail and Google Drive

1. **Project:** [console.cloud.google.com](https://console.cloud.google.com) → new project `hirebuddha-connect` (and `hirebuddha-connect-dev`). Enable the **Gmail API** and **Google Drive API**.
2. **Domain:** verify `hirebuddha.com` in [Google Search Console](https://search.google.com/search-console) (TXT record at GoDaddy) with an account that is an owner of the project.
3. **Google Auth Platform → Branding:** app name `HireBuddha`, logo, support e-mail, home page `https://hirebuddha.com`, privacy policy, terms, **authorised domain** `hirebuddha.com`.
4. **Audience:** *External*. Dev project: leave **Testing** and add test users (up to 100; their refresh tokens last 7 days in Testing). Production project: **Publish app** when ready for review.
5. **Data access → Add scopes:** `openid`, `email`, `.../auth/drive.file` (Drive), `.../auth/gmail.modify` and `.../auth/gmail.send` (Gmail — **restricted**).
6. **Clients → Create client → Web application:** authorised redirect URIs `https://gateway.hirebuddha.com/oauth/callback/google` (production project) / `https://gateway.azdev.hirebuddha.com/oauth/callback/google` (dev project). Copy the **client ID**; the secret → Key Vault `oauth-google-client-secret`.
7. **Verification Centre → Prepare for verification:** a scope justification per scope and a **demo video** (unlisted YouTube) showing the consent screen with the app name and the scopes, then HireBuddha using each scope.
8. **Gmail (restricted scopes):** after Google's review, a **CASA Tier 2** security assessment by an authorised lab (Google's list in the Verification Centre; self-scan options exist). Repeat every 12 months. Budget US$540–6,000 a year and 2–6 weeks. **Tip:** submit Drive alone first (`drive.file` needs no assessment) and add Gmail when CASA is booked; until then businesses can connect mail with the **mailbox (IMAP)** connector, which needs no Google review.

**Hand to engineering:** client ID (each project), secret name `oauth-google-client-secret`.

---

## 5. Microsoft — Outlook / Microsoft 365 mail

1. **Tenant and domain:** in [entra.microsoft.com](https://entra.microsoft.com) (HireBuddha's Microsoft tenant — the Azure one is fine) → **Domain names → Add custom domain** `hirebuddha.com` → TXT record at GoDaddy → **Verify**. (Publisher verification needs a verified domain, not `*.onmicrosoft.com`.)
2. **App registrations → New registration:** name `HireBuddha` (and `HireBuddha Dev`); supported accounts **"Accounts in any organizational directory and personal Microsoft accounts"**; redirect URI **Web** `https://gateway.hirebuddha.com/oauth/callback/microsoft` (dev: `gateway.azdev…`).
3. **Certificates & secrets → New client secret** (24 months; diary the expiry) → Key Vault `oauth-microsoft-client-secret`. Copy the **Application (client) ID**.
4. **API permissions → Microsoft Graph → Delegated:** `openid`, `email`, `offline_access`, `Mail.ReadWrite`, `Mail.Send`. These need no admin consent by Microsoft's defaults, but many organisations let users consent only to apps from **verified publishers** — hence the next step.
5. **Branding & properties:** home page, terms, privacy URLs, logo, **publisher domain** `hirebuddha.com`.
6. **Publisher verification:** enrol in the **Microsoft AI Cloud Partner Program** (free; [partner.microsoft.com](https://partner.microsoft.com)) with the legal entity and business e-mail; wait for the account verification (days to two weeks); associate the tenant with the partner account; then in the app **Branding & properties → Add verified publisher** → enter the **Partner ID** → Verify. The consent screen then shows the blue "verified" badge.

**Hand to engineering:** client ID (each registration), tenant `common`, secret name `oauth-microsoft-client-secret`.

---

## 6. LinkedIn — LinkedIn Page posting

1. **HireBuddha's LinkedIn Page** must exist, with you as a **super admin**.
2. [linkedin.com/developers](https://www.linkedin.com/developers/apps) → **Create app**: name `HireBuddha`, **LinkedIn Page** = HireBuddha's, privacy policy URL, logo → create. On **Settings**, **Verify** the app (the Page admin approves the request).
3. **Products → Community Management API → Request access.** LinkedIn wants it to be the **only product on that app** — do not add *Sign In with LinkedIn* or others to it. The form asks for the legal name, registered address, website, privacy policy and business e-mail, and the use case: *"HireBuddha lets businesses publish and schedule posts to their own LinkedIn Pages and read their Page analytics from their HireBuddha workspace; an AI agent drafts, a person or the business's rules approve."* A vetting **survey** follows: complete it within **21 days**.
4. **Development tier** granted → **Auth** tab: redirect URLs `https://gateway.hirebuddha.com/oauth/callback/linkedin` and `https://gateway.azdev.hirebuddha.com/oauth/callback/linkedin`; scopes `r_organization_social`, `w_organization_social`, `rw_organization_admin`. Copy the **Client ID**; **Primary client secret** → Key Vault `oauth-linkedin-client-secret`.
5. **Standard tier** (needed beyond your own test Pages): once the connector works on Azure dev, apply with a screen recording of the whole OAuth flow and every feature that uses member data (posting to a Page, reading its analytics). Approved apps also get **programmatic refresh tokens** (otherwise businesses reconnect every 60 days).

**Hand to engineering:** client ID, secret name `oauth-linkedin-client-secret`, and which tier is granted.

---

## 7. X (Twitter)

1. [console.x.com](https://console.x.com) (the developer console) → sign in with HireBuddha's X account → accept the developer agreement → create a **project** and an **app** `HireBuddha`.
2. **Billing:** X moved to **pay-per-use** on 6 Feb 2026: buy credits; posting costs about US$0.015 a post and more with a link (check the console's price list). **Set a monthly spending limit** and turn auto-recharge to a level you are comfortable with. Each business's posts are paid from HireBuddha's credits — engineering prices them to the business (a registry price for the tool).
3. **User authentication settings → Set up:** OAuth 2.0 **on**; type **Web App, Automated App or Bot** (confidential client); app permissions **Read and write**; **Callback URI** `https://gateway.hirebuddha.com/oauth/callback/x` and `https://gateway.azdev.hirebuddha.com/oauth/callback/x`; website `https://hirebuddha.com`; terms and privacy URLs → Save.
4. Copy the OAuth 2.0 **Client ID**; **Client secret** → Key Vault `oauth-x-client-secret`. (The API key/secret pair for OAuth 1.0a is not used.)

No review. **Hand to engineering:** client ID, secret name, the spending limit you set.

---

## 8. GitHub

Create two Apps in HireBuddha's GitHub **organisation**: **Settings → Developer settings → GitHub Apps → New GitHub App**.

| Field | Production App | Dev App |
|-------|----------------|---------|
| Name | `HireBuddha` | `HireBuddha Dev` |
| Homepage URL | `https://hirebuddha.com` | same |
| Callback URL | `https://gateway.hirebuddha.com/oauth/callback/github` | `https://gateway.azdev.hirebuddha.com/oauth/callback/github` |
| **Setup URL** (after installation) | same as the callback URL, and tick **Redirect on update** | same |
| Webhook | Active; URL `https://gateway.hirebuddha.com/webhook/provider/github`; secret = `oauth-github-webhook-secret` | `…azdev…` |

**Repository permissions:** Contents **Read and write**, Pull requests **Read and write**, Issues **Read and write**, Checks **Read and write**, Metadata **Read** (automatic). **Organisation permissions:** Administration **Read and write** only if businesses should let HireBuddha create repositories in their organisation (the "create repository" action).
**Subscribe to events:** Push, Pull request, Issues, Check run, Check suite (installation events arrive anyway).
**Where can this GitHub App be installed?** **Any account.**

After creating: copy the **App ID**, **Client ID** and the **public link's slug** (`github.com/apps/<slug>`); **Generate a client secret** → Key Vault `oauth-github-client-secret`; **Generate a private key** (downloads a `.pem`) → paste its whole contents into Key Vault `oauth-github-private-key`, then delete the downloaded file. Public Apps need no review (a Marketplace listing is optional).

**Hand to engineering:** App ID, client ID, slug (each App), secret names.

---

## 9. The last step for every provider: switching the connector on

Engineering (not you) turns your hand-over into HireBuddha settings:

1. A **system integration** row on the platform company for each app: category `OAUTH_APP`, SKU `oauth-app-meta` / `oauth-app-google` / `oauth-app-microsoft` / `oauth-app-linkedin` / `oauth-app-x` / `oauth-app-github`; the non-secret settings (`client_id`, Meta's `config_id`, `solution_id` and `graph_version`, GitHub's `app_id` and `app_slug`, Microsoft's `tenant`) in its metadata; the secrets **by name** (`secret_ref`, `verify_token_ref`, `private_key_ref`, `webhook_secret_ref`).
2. On **Platform admin → Connectors** (`/admin/connectors`) the connector goes from *Coming soon* to **Preview** (staff and test businesses) while the review runs, then to **Available** with the review recorded as approved.
3. A test business connects on Azure dev; engineering checks a token refresh and a webhook delivery.

Production repeats step 1 in production's vault and database when production exists.

---

## 10. Tracker

| Provider | Step | Owner | Started | Done | Notes |
|----------|------|-------|---------|------|-------|
| All | Legal details, business e-mail, icon gathered | Owner | | | |
| All | Privacy policy updated; **data deletion page** published | Owner + Eng | | | |
| Meta | Business portfolio + business verification | Owner | | | |
| Meta | Domain verified | Owner | | | |
| Meta | Tata: app ID, solution name, terms agreed | Owner | | | |
| Meta | App created, basic settings | Owner | | | |
| Meta | Partner solution created → accepted by Tata | Owner / Tata | | | solution ID: |
| Meta | WhatsApp App Review (2 videos) | Owner | | | |
| Meta | Login for Business settings, Embedded Signup config, webhooks | Owner + Eng | | | config ID: |
| Meta | Pages / Instagram App Review | Owner + Eng | | | after dev screens |
| Google | Projects, APIs, domain, branding | Owner | | | |
| Google | Drive verification | Owner | | | |
| Google | Gmail review + CASA Tier 2 | Owner + lab | | | renew yearly |
| Microsoft | Domain, registrations, secret | Owner | | | secret expires: |
| Microsoft | Partner Program + publisher verification | Owner | | | Partner ID: |
| LinkedIn | App, Page verification, Development tier, survey | Owner | | | survey due: |
| LinkedIn | Standard tier | Owner + Eng | | | |
| X | Console, billing limit, OAuth 2.0 app | Owner | | | limit: |
| GitHub | Dev and prod Apps, key, secrets | Owner | | | |
| All | Registry rows, connectors to Preview / Available | Eng | | | |

---

## Sources (checked 20 Oct 2026)

* Meta: [Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers), [Multi-Partner Solutions](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/multi-partner-solutions/), [Embedded Signup implementation (v4)](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/), [Become a partner](https://whatsappbusiness.com/partners/become-a-partner/)
* Google: [Google security review notes (Nango)](https://nango.dev/docs/api-integrations/google-shared/google-security-review), [CASA lab pricing example (Leviathan)](https://leviathansecurity.com/programs/google-casa-cloud-application-security-assessment)
* Microsoft: publisher verification in the Entra admin centre (Branding & properties); [Microsoft AI Cloud Partner Program](https://partner.microsoft.com)
* LinkedIn: [Community Management API](https://developer.linkedin.com/product-catalog/marketing/community-management-api), [Community Management app review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review)
* X: [pay-per-use change, Feb 2026](https://roboin.io/article/en/2026/02/08/x-transitions-api-to-pay-per-use-model-ending-free-plan/), [pay-per-use explained](https://opentweet.io/how-to/x-api-pay-per-use-explained) — confirm prices in the console
* This repository: `backend/src/connections/catalog/*.yaml` (scopes and webhook fields per connector), `backend/src/connections/apps.py` (the settings each app row carries)
