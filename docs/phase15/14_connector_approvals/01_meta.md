# 01 — Meta: WhatsApp Business, Facebook Pages, Instagram

> **Researched:** 2026-10-28 · **Status:** Not submitted (catalog: `whatsapp_business`, `facebook_pages`, `instagram_business` are `planned`, approval `not_submitted`).
> **App:** one Meta app, `HireBuddha`, in Buddha Cognitive Lab's business portfolio (`oauth-app-meta`). How to create it: [provider guide §3](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md).
> **Lead time:** business verification 2–10 working days; WhatsApp App Review about a day on average; Pages and Instagram App Review about a week per submission, and first submissions are often rejected once. **Cost:** free; WhatsApp messages are billed on Tata's credit line.

---

## 1. What Meta checks

1. **Business verification** of the portfolio that owns the app. It is required before any Advanced access, and is the step that most often stalls for Indian companies (name mismatches, §7).
2. **App Review** for each permission that needs **Advanced access** (a business other than ours uses it). For each permission: a usage description, one screen recording, at least one successful API call in the last 30 days, and conformance with that permission's *Allowed usage*.
3. **Data handling questions** (part of the submission) and, once live, the yearly **Data Use Checkup**. Meta may also ask for a **Data Protection Assessment** through the dashboard.
4. **WhatsApp only: Tech Provider onboarding.** Business verification plus App Review for the two WhatsApp permissions, then the partner solution with Tata ([guide §3.1, §3.4](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)).
5. **Policies** that reviewers check in the recordings: Platform Terms and Developer Policies, the Messenger Platform and Instagram Messaging policy (§5), the WhatsApp Business Solution Terms and Business Messaging Policy (§6).

Meta **removed the separate "access verification"** for Tech Provider apps on 9 Oct 2026. Business verification and App Review now carry those checks (Social Media Today, 11 Oct 2026).

## 2. Permissions to request

| Permission | Connector | What HireBuddha uses it for | In the catalog? |
|---|---|---|---|
| `pages_show_list` | Pages, Instagram | List the Pages a person manages, to choose one | Yes |
| `pages_read_engagement` | Pages, Instagram | Read the Page's posts, reactions and comment counts | Yes |
| `pages_read_user_content` | Pages, Instagram | Read visitors' comments and posts on the Page. **Meta lists it as a dependency of `pages_manage_engagement` and `instagram_basic`** | **No: add (META-E2)** |
| `pages_manage_posts` | Pages | Publish a post the team approved | Yes |
| `pages_manage_engagement` | Pages | Post a reply to a comment, hide a comment | Yes |
| `pages_manage_metadata` | Pages | Subscribe the Page to the app's webhooks (`feed`, `messages`) | Yes |
| `pages_messaging` | Pages | Answer Messenger conversations of the Page | Yes |
| `read_insights` | Pages | Page insights for the `read_insights` action. Confirm in Meta's permissions reference which permission the Page Insights endpoint needs today | **No: add if the action stays (META-E2)** |
| `instagram_basic` | Instagram | The professional account's ID, username, media | Yes |
| `instagram_content_publish` | Instagram | Publish a feed post the team approved | Yes |
| `instagram_manage_comments` | Instagram | Read and reply to comments, hide abusive ones | Yes |
| `instagram_manage_messages` | Instagram | Answer Instagram Direct messages | Yes |
| `whatsapp_business_management` | WhatsApp | Read the onboarded business's WhatsApp account and numbers; manage its templates | Yes |
| `whatsapp_business_messaging` | WhatsApp | Send and receive messages for onboarded businesses | Yes |
| `business_management` | WhatsApp (if Meta asks) | Only if Embedded Signup or asset claiming needs it. Do not request it otherwise | No |
| *Human Agent* (feature) | Pages, Instagram | A **person** answering up to 7 days after the customer's last message. Request it only when the product has a human reply path (META-E4) | No |

The Instagram connector uses the **Instagram API with Facebook Login** (the account reached through its Page). Meta also offers the *Instagram API with Instagram Login* (`instagram_business_*` permissions, no Page needed), but the Instagram product of an app uses one login or the other. Stay with Facebook Login: the same login already serves Pages.

## 3. Requirements

### A. Business and accounts

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| META-01 | Business portfolio named **exactly** as SH-01's legal name, with two full admins and 2FA (SH-04) | Owner | Portfolio settings match the certificate character for character | Open |
| META-02 | **Business verification** (*Security Centre → Start verification*): name, address and phone as on the documents; confirm by domain, e-mail or phone; documents if asked. The certificate of incorporation or GST certificate proves the **name**. A utility bill proves only the **address**. Upload every page, uncropped and unaltered. | Owner | Portfolio shows *Verified* | Open |
| META-03 | Website identifies the business (SH-06) and the e-mail used is on the same domain: `hirebuddha.com` once it has mail (SH-02, WEB-02), or `buddhalab.in` with that site as the business website ([08](08_website_readiness.md) §2) | Owner | — | Open |
| META-04 | Domain `hirebuddha.com` verified in the portfolio (SH-03) | Owner | *Verified* | Open |
| META-05 | Tata: app ID, solution name, who sends messages, commercial terms ([guide §3.1](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)) | Owner | Agreed in writing | Open |

### B. App settings

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| META-06 | *App settings → Basic*: icon 1024 × 1024 with no Meta marks (SH-11), privacy policy URL (SH-07), terms URL (SH-08), category, contact e-mail you read, app domains for the hostnames of SH-12 | Owner | All fields filled | Open |
| META-07 | **User data deletion**: *Data deletion request URL* = `https://<gateway>/webhook/provider/meta/data-deletion` (the callback of META-E1, built), and *Deauthorize callback URL* = `https://<gateway>/webhook/provider/meta/deauthorize`; the instructions page SH-09 as well ([11](11_website_content/README.md)) | Owner + Eng | The URL answers | Open |
| META-08 | App purpose: **Clients** (other businesses use it). App verification: "users sign in with Meta" = Yes, with reviewer instructions (SH-14) | Owner | — | Open |
| META-09 | Login settings ([guide §3.5](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)): strict redirect URIs for the SH-12 hostnames, JavaScript SDK domains, Embedded Signup configuration (v4), webhooks verified for WhatsApp, Page and Instagram | Owner + Eng | *Verify and save* succeeds on each webhook | Open |
| META-10 | **Freeze the settings** once submitted: changing basic or advanced settings during a review can send it back to the queue | Owner | — | Open |

### C. Engineering before recording

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| META-E1 | **Data deletion request callback**, with a status page. Meta POSTs a `signed_request`; verify it with the app secret; find the connections of that app-scoped user ID; delete their tokens and Meta-derived data (SH-E1, SH-E2); answer `{"url": "<status page>", "confirmation_code": "<code>"}`; the status page explains, in plain words, what was deleted or why not. Also handle the **deauthorise callback** (the person removed the app on Facebook) by marking those connections disconnected. Neither exists in the code today. | `connections/webhooks.py` (new route under `/webhook/provider/meta/…`), a public status page | A test posts a signed request and gets a code; the connection is gone | Done (code) |
| META-E2 | **Scopes**: add `pages_read_user_content` to `facebook_pages.yaml` and `instagram_business.yaml`; add the Page Insights permission if `read_insights` stays (else remove that action); request nothing the product doesn't use | `connections/catalog/*.yaml` | The App Review dashboard shows no missing dependency | Done (code) |
| META-E3 | **Which login product.** `MetaProvider.authorize_url` sends a `scope` list to the classic OAuth dialog. If the app's Pages and Instagram use cases run on **Facebook Login for Business**, Meta expects a **configuration ID** (`config_id`) instead of `scope`, and the person grants all of the configuration's permissions or none. Check the dashboard. If it is Login for Business, create a "Pages and Instagram" configuration (user access token) and send `config_id` like the Embedded Signup path does. | `connections/providers/meta.py` | A connect on dev shows Meta's dialog with exactly the permissions of §2 | Done (code) |
| META-E4 | **Messaging rules in the product** (§5): reply to Page and Instagram DMs only inside the 24-hour window (a person may answer up to 7 days with *Human Agent*); an automated reply to every kind of input within 30 s; a line saying the reply comes from an AI assistant at the start of a conversation, after a long gap and when a person hands back to the assistant; a hand-off to a person; the Page's response type set to *hybrid* | Voice/messaging channel code, channel settings | A test refuses a send outside the window; the disclosure appears | Partly done (code) |
| META-E5 | **WhatsApp rules in the product** (§6): business-specific agents only (no general-purpose assistant on WhatsApp); business-initiated messages only as approved templates to customers who opted in, with the opt-in recorded; nothing from WhatsApp used to train models | Agent builder and WhatsApp channel; terms SH-08 | A check in the WhatsApp channel; the terms say it | Open |
| META-E6 | **Every requested permission called successfully within 30 days** before submitting, from HireBuddha on the environment reviewers use. The *Request advanced access* button stays grey until a call is logged, which takes up to 2 days. | Dev/production with the test assets of SH-16 | Each permission shows a recent call in App Review | Open |
| META-E7 | Graph API version (`DEFAULT_GRAPH_VERSION = "v26.0"`, or the app row's `graph_version`) is current at submission | `connections/providers/meta.py` | — | Done (code) |

### D. The submissions

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| META-11 | **WhatsApp first** (fastest, and Tech Provider status needs it): Advanced access to `whatsapp_business_messaging` and `whatsapp_business_management`, one video each (§4). Meta accepts the API Setup page's cURL send and WhatsApp Manager creating a template, or Tata's integration, in place of HireBuddha's screens | Owner | Approved | Open |
| META-12 | Tech Provider onboarding with Tata: partner solution created and accepted, solution ID recorded ([guide §3.4](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)) | Owner / Tata | Solution *Active* | Open |
| META-13 | **Pages and Instagram**: after META-E1…E6, one usage description (§4, unique per permission) and one recording per permission, reviewer instructions and credentials (SH-14), submitted together | Owner + Eng | Approved | Open |
| META-14 | Read every rejection note under the permission (*Add to submission* shows the reviewer's feedback), fix exactly that, resubmit | Owner | — | Open |

### E. After approval

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| META-15 | Switch the app to **Live** only after the review; in Live mode only approved permissions work, even for the app's own roles | Owner | — | Open |
| META-16 | Connectors to *Preview*, then *Available*, approval recorded on *Platform Console → Connectors* | Eng | Catalog row `approval.state = approved` | Open |
| META-17 | Data Use Checkup every year; answer developer alerts | Owner | Calendar entry | Open |
| META-18 | Per business, after Embedded Signup: Meta reviews the WhatsApp display name; templates are approved per business; messaging limits start low and grow with quality and verification. Tell businesses this in the WhatsApp connect screen | Eng | Help text shown | Open |

## 4. What to submit, per permission

Each description must be different; Meta rejects copied text. Drafts to adapt:

| Permission | Draft usage description | The recording shows |
|---|---|---|
| `pages_show_list` | When a business connects Facebook in HireBuddha, we list the Pages the person manages so they can choose the Page their AI employee works on. We keep only the chosen Page's ID and name. | Connect → Facebook dialog → the Page picker in HireBuddha |
| `pages_read_engagement` | HireBuddha shows the business its Page's recent posts with their reactions and comment counts, and gives its AI employee a post's text when it drafts a reply. Only that business's team sees it. | The Page's posts listed in HireBuddha, matching the Page on Facebook |
| `pages_read_user_content` | HireBuddha reads comments and visitor posts on the business's own Page so its AI employee can draft an answer for a person on the team to approve. | A new comment on Facebook appearing in HireBuddha |
| `pages_manage_posts` | The team writes or approves a post in HireBuddha (the AI employee may draft it) and HireBuddha publishes it to the business's Page now or at the time they choose. | Draft → approve → publish → **the post on the Facebook Page** |
| `pages_manage_engagement` | After a person approves the AI employee's draft, HireBuddha posts it as the Page's reply to a comment; the team can hide a comment they flag as spam. | Approve a reply in HireBuddha → the reply under the comment on Facebook |
| `pages_manage_metadata` | HireBuddha subscribes the chosen Page to our webhooks so new comments and messages reach the business's workspace as they happen. | Connect → a comment posted on Facebook arrives in HireBuddha within seconds |
| `pages_messaging` | People who message the business's Page get answers from the business's AI employee within the 24-hour window; it says it is an AI assistant, and hands the conversation to a person when asked or when it can't help. | A Messenger message from a test user → the AI reply in Messenger → a person taking over in HireBuddha |
| `instagram_basic` | HireBuddha reads the business's Instagram professional account's ID, username and posts so the team can choose the account and see its posts in HireBuddha. | Connect → account chosen → its posts listed |
| `instagram_content_publish` | The team approves an image or video post with its caption in HireBuddha, and HireBuddha publishes it to the business's own Instagram account. | Approve → publish → **the post on Instagram** |
| `instagram_manage_comments` | HireBuddha shows comments on the business's Instagram posts and posts the reply a person approves; the team can hide abusive comments. | Comment on Instagram → reply approved in HireBuddha → reply on Instagram |
| `instagram_manage_messages` | Customers who send the business an Instagram Direct message get answers from its AI employee within the 24-hour window, with a hand-off to a person. | A DM from a test account → the AI reply in Instagram |
| `whatsapp_business_management` | Businesses connect their WhatsApp Business Account to HireBuddha with Embedded Signup; HireBuddha reads their phone numbers and creates and manages their message templates for them. | A template created (in HireBuddha or WhatsApp Manager) |
| `whatsapp_business_messaging` | HireBuddha sends and receives WhatsApp messages for each onboarded business: its AI employee answers customer messages in the customer service window and sends approved templates (appointment reminders, order updates) to customers who opted in. | A message sent → **received on a phone's WhatsApp** |

**Reviewer instructions** (one block for the submission): the HireBuddha URL, the reviewer's e-mail and password (SH-14), "Connections → Facebook Pages → Connect", which Page and Instagram account to use, how to trigger each feature (post a comment, send a DM), and that a person approves each outbound reply.

## 5. Messenger and Instagram messaging rules (Meta's policy page)

* **Standard messaging window:** 24 hours after the person's last message (up to 7 days after a click-to-Messenger ad). Outside it, only message tags for their approved uses.
* **Human Agent tag:** a person (not the AI) may reply up to 7 days later.
* **Automated bots** must answer every input (free text, quick replies, buttons, menu) within 30 seconds.
* **Disclosure:** where the law requires it (Meta names California and Germany), a bot says it is automated at the start of a conversation, after a significant lapse and when a human hands back to automation. Meta recommends this everywhere, which is why META-E4 makes it the default.
* Restriction notices arrive in the Page's Support Inbox; fix within 7 days.

## 6. WhatsApp rules that affect the product

* **AI providers clause** (WhatsApp Business Solution Terms, for all businesses from 15 Jan 2026): providers of AI or ML technology may not use the Business API to offer that technology as the core service (general-purpose assistants such as ChatGPT, Copilot, Perplexity). AI that serves a business's own customers (support, bookings, order tracking, sales) stays allowed. Describe HireBuddha as the second kind everywhere: an AI employee *of that business* for *its* customers. Meta decides what the primary use is, so the agent builder must not offer a general assistant on WhatsApp (META-E5).
* **WhatsApp data may not train AI models.**
* **Business-initiated messages** need the customer's opt-in and an approved template. Free-form replies are possible only in the customer service window.
* **Onboarding limit**: a Tech Provider in a partner solution onboards up to 200 new businesses per rolling week (guide §3.1).

## 7. Common rejections and how they were resolved

Sources: Meta's App Review guides and WhatsApp/Instagram review pages (official), Meta business verification write-ups, practitioner write-ups (§8). Reddit could not be opened from this environment, so the community patterns come from those write-ups and forums.

| Rejection or symptom | Usual cause | What fixed it |
|---|---|---|
| "The screencast does not show the permission being used" (the most common) | The video starts already signed in, skips Facebook's dialog, or shows only HireBuddha's side | Start disconnected; show the Facebook dialog listing the permission; do the action; **show the result on Facebook/Instagram/WhatsApp** (the post on the Page, the reply under the comment, the message on the phone). For `pages_manage_posts`, a video of reading only is rejected |
| "We could not access your app" / test credentials failed | Login behind MFA, an IP allow-list, an expired password, or dev switched off at night | SH-14, SH-15; test the instructions from a fresh browser the day you submit |
| "Your app does not need this permission" | A permission requested for later, or never called | Request only what the recording shows; one successful call per permission in the last 30 days (META-E6) |
| "Use not allowed for this permission" | The use isn't in the permission's *Allowed usage* | Read *Allowed usage* for each permission; describe the user-facing feature, not marketing |
| Copied or vague descriptions | The same text across permissions | One specific description each (§4): what the user does, what is read or written, what they see |
| WhatsApp: rejected for screenshots, or one video for both permissions | Meta wants one video per permission | Two separate recordings; cURL from API Setup is accepted |
| Submission never reviewed | Left in draft | Press *Submit for review* and accept the onboarding terms |
| Messaging permissions "could not be verified" | Bot replies only work on a developer's machine | Public webhooks (gateway URL), app subscribed to the Page, reviewer can trigger a reply |
| Instagram DMs fail for the reviewer | The test account isn't a professional account linked to the Page, or *Allow access to messages* is off | SH-16; say so in the reviewer instructions |
| Login button rejected (Instagram) | A custom button | Meta's branded "Continue with Facebook" button |
| Data deletion URL invalid | 404 (today's `/data-deletion`) | SH-09 and META-E1 |
| **Business verification:** "not approved" | Name differs from the document (even a suffix like "Pvt Ltd"); a utility bill offered as proof of name; blurry, cropped or old documents; website without the legal name or contact; personal e-mail; not a full admin; fewer than two admins or no 2FA | Match SH-01 exactly, re-upload proper documents, fix the website (SH-06), then *Re-verify* once. Wait a day between attempts, since resubmitting too often counts against you (attempts are limited) |
| Approved, but nothing works for customers | App still in Development mode, or the connector still *planned* | META-15, META-16 |

## 8. Sources

* Meta (official): [App Review submission guide](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review/submission-guide); [WhatsApp solution providers: App Review](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/app-review.md); [Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers); [Instagram API App Review](https://developers.facebook.com/docs/instagram-platform/app-review); [Permissions reference](https://developers.facebook.com/docs/permissions); [Data deletion request callback](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback); [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/); [Messenger Platform and IG Messaging API policy](https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy.md); [Data Use Checkup](https://developers.facebook.com/docs/resp-plat-initiatives/individual-processes/data-use-checkup)
* News: [WhatsApp bars general-purpose chatbots (TechCrunch, 18 Oct 2025)](https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform/); [respond.io on the ban](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban); [Meta removes access verification (Social Media Today, 11 Oct 2026)](https://socialmediatoday.com/news/meta-removes-access-verification-for-developers/832678)
* Practitioners (secondary): [20 business verification rejection reasons (Chakra)](https://chakrahq.com/article/meta-business-verification-rejected-reasons); [Meta App Review rejected: 7 reasons (Dojo Labs)](https://dojolabs.co/blog/meta-app-review-rejected-what-to-fix/); [Meta app approval guide (Saurabh Dhar)](https://www.saurabhdhar.com/blog/meta-app-approval-guide); [Screencast guide (singhamandeep)](https://singhamandeep.com/meta-app-review-screencast-why-your-demo-video-gets-rejected-2026/); [Messenger bot reviews (singhamandeep)](https://singhamandeep.com/facebook-messenger-bot-app-review-chatbot-saas/)
* This repository: `backend/src/connections/catalog/{facebook_pages,instagram_business,whatsapp_business}.yaml`, `backend/src/connections/providers/meta.py`, `backend/src/connections/webhooks.py`
