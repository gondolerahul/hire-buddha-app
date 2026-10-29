# 10 — Code fixes: the consolidated plan

> **Planned:** 2026-10-28 from the engineering items (`…-E…`) of [00](00_shared_prerequisites.md)–[09](09_youtube_and_google_ads.md) and SH-13, codebase at `80537e1` · **Status (28 Oct 2026):** waves 1 and 2 built and tested; wave 3's provider-required pieces built (SH-E3, the YouTube upload contract, Messenger's 24-hour window); the rest of wave 3 open, with design notes below. Not committed or deployed: see "To deploy".
> **What this covers:** the changes in this repository that the provider reviews need. Website changes ([08](08_website_readiness.md)), the owner's console work, and infrastructure outside the repository (WEB-01, SH-15) are not here.

## Rules for every change

* **One platform rule, not an agent option.** What a provider requires (a person's approval, a retention limit, a disclosure) is enforced by the platform for every agent, not left to each agent's builder.
* **No connector becomes connectable here.** Every reviewed connector stays `planned` until its provider approves (the catalog's `approval`); these changes make the product reviewable.
* **Tested without the provider.** Provider calls are played (`connections.providers.base.set_transport`, `httpx.MockTransport`); nothing calls Google, Meta, Microsoft, LinkedIn or X from the tests.
* **The docs follow the code.** When an item is done, its Status here and in the provider document says so.

## Wave 1 — small fixes, no dependencies

| # | IDs | Change | Where | Test | Status |
|---|-----|--------|-------|------|--------|
| 1.1 | LI-E1 | One LinkedIn version setting (`LINKEDIN_API_VERSION`, now `202610`) for the connector and the tools; a start-up warning when it is more than ten months old | `common/config.py`, `connections/providers/oauth.py`, `connections/api_versions.py`, `main.py` | Unit | Done |
| 1.2 | GADS-E2, META-E7 | One Google Ads version setting (`GOOGLE_ADS_API_VERSION`, `v26`) with its announced sunset month, warned 60 days before; one Meta Graph version setting behind the app row's own | `common/config.py`, `ai/tools/social/google_ads.py`, `connections/providers/meta.py`, `connections/api_versions.py` | Unit | Done |
| 1.3 | MS-E2, META-E2 | Catalog scopes: `User.Read` for Outlook; `pages_read_user_content` for Pages and Instagram; `read_insights` for Pages | `connections/catalog/*.yaml` | Unit (catalog) | Done |
| 1.4 | META-E3 | Facebook Login for Business: a `login_config_id` on the Meta app sends `config_id` in place of `scope` | `connections/providers/meta.py` | Unit | Done |
| 1.5 | GOOG-E3 | Google's granted scopes checked at connect: a missing one refuses the connection and names the feature that needs it | `connections/providers/oauth.py` | Unit | Done |
| 1.6 | MAIL-E1 | A mail server that refuses the stored password marks the connection `needs_reconnect`, pauses its triggers and tells the owners; no more logins with it | `connections/service.py`, `automation/pollers/`, `ai/tools/email/email_tool.py` | Unit, integration | Done |
| 1.7 | MAIL-E2 | No Microsoft mailbox on the password path: the Mailbox form refuses Microsoft servers and addresses; the old wizard loses *Outlook / Office 365* | `connections/providers/forms.py`, `ai/email_router.py`, `frontend/…/EmailConnectionWizard.tsx` | Unit | Done |
| 1.8 | MAIL-E3 | Mailbox presets: a `select` field kind; presets fill in the servers; help text on the form | `connections/catalog.py`, `catalog/imap_mailbox.yaml`, `providers/forms.py`, `frontend/…/ConnectionsPage.tsx` | Unit | Done |
| 1.9 | MAIL-E4, MS-E4, LI-E7 | After disconnecting, the advice the provider needs (revoke the app password; remove the app in Entra; LinkedIn and Google's own pages) | catalog `after_disconnect`, `connections/service.py`, `frontend/…/ConnectionDetail.tsx` | Integration | Done |
| 1.10 | SH-13, X-E2 | A disclosure before every reviewed connector's sign-in: what HireBuddha reads, what AI employees do with it, the privacy policy; the person continues or cancels | catalog `disclosure`, `connections/catalog.py`, `frontend/…/ConnectionsPage.tsx` | Unit | Done |
| 1.11 | GH-E1 | GitHub: an installation suspended or unsuspended changes the connection's status; repositories removed from it are recorded | `connections/webhooks.py` | Unit, integration | Done |
| 1.12 | YT-E3, YT-E6, GADS-E3 (bugs) | YouTube analytics defaults to the last 28 days; comment moderation is a `POST`; Google Ads stops offering Video campaign creation and Enhanced CPC | `ai/tools/social/youtube.py`, `google_ads.py` | Unit | Done |

## Wave 2 — connector behaviour

| # | IDs | Change | Where | Test | Status |
|---|-----|--------|-------|------|--------|
| 2.1 | SH-E4, X-E1, YT-E3, GADS-E4, GOOG-E5 | **A person approves each write to a connected account.** A registry of outbound actions (tool, and the arguments that make it a write); before such a step the governance check opens an approval showing exactly what goes out, unless the agent already has a checkpoint for that tool or staff have exempted it | `ai/governance/connector_actions.py`, `ai/governance/governance_service.py`, platform setting `connections.action_approval` | Unit, integration | Done |
| 2.2 | GOOG-E1, GOOG-E2 | Gmail through the Gmail API (new mail, read, draft, send, label) with `gmail.modify` alone | `connections/mail/gmail_api.py`, `automation/pollers/mailbox.py`, `ai/tools/email/email_tool.py`, `catalog/gmail.yaml` | Unit (played Gmail) | Done |
| 2.3 | MS-E1 | Outlook through Microsoft Graph (new mail, read, draft, send) | `connections/mail/graph_mail.py`, poller, e-mail tools | Unit (played Graph) | Done |
| 2.4 | MS-E3 | The admin-consent path: Microsoft's "needs admin approval" answer explained, with a consent link for the business's admin and its callback | `connections/providers/oauth.py`, `connections/service.py`, `connections/api.py`, `ConnectionsPage.tsx` | Unit | Done |
| 2.5 | META-E1, META-07 | Meta's data deletion and deauthorise callbacks (verified `signed_request`), the app-scoped user recorded at connect, and a public status page per confirmation code | `providers/meta.py`, `connections/webhooks.py`, `connections/deletion.py`, a control migration | Unit, integration | Done |
| 2.6 | SH-E1, GOOG-E8 | Disconnecting deletes what came through the connection: its stored events, its poll cursor and its pending state (traces and memory follow SH-E2) | `connections/service.py` | Integration | Done |
| 2.7 | YT-E1, GADS-E1 | YouTube and Google Ads connectors on the marketing app (`planned`): the channel and the Ads customers are the accounts; the tools use the connector; no developer token | `catalog/youtube_channel.yaml`, `catalog/google_ads.yaml`, `providers/oauth.py`, `connections/client.py`, `google_ads.py` | Unit | Done |
| 2.8 | X-E3, X-E6 | The same text from another X account in the last 7 days is refused; X's rate-limit reset header is honoured | `ai/tools/social/twitter.py`, `ai/tools/social/base.py` | Unit | Done |
| 2.9 | X-E5 | Each X post is priced: a usage row at the registry's price (post, post with a link), so the business is billed | `ai/tools/social/twitter.py`, the integration registry | Unit | Done |

## Wave 3 — shared data rules

Larger changes that cut across runs, memory and records. Each needs its own design note before code.

| # | IDs | Change | Where | Status |
|---|-----|--------|-------|--------|
| 3.1 | SH-E2, LI-E2, X-E4, YT-E5, GOOG-E6 | **Retention by source**: connector data marked with its connector in tool outputs, traces, CORTEX memory and records; a nightly job applies each provider's limit (LinkedIn 48 h and 24 h, X 24 h after deletion, YouTube 30 days) and keeps Gmail and Drive data out of cross-business learning | Run persistence, trace store, `cortex_memory`, records engine, a retention job | Open |
| 3.2 | SH-E3 | **Prompt-injection screening** of connector content before the planner sees it, marked untrusted in prompts (Azure AI Content Safety *Prompt Shields* on Azure) | Tool output path, prompt builder | Done |
| 3.3 | SH-E6 | **Staff don't read connector content without consent**: redacted in traces for staff, unless the business grants time-boxed access | Trace views, the access grants of M15.4 | Open |
| 3.4 | LI-E3, LI-E4 | LinkedIn member data kept out of records, leads, memory and exports; the comment and analytics views the screencast shows | Records writes, exports, run view | Open |
| 3.5 | META-E4, META-E5 | Messaging rules: the 24-hour window, the AI disclosure, the hand-off to a person; WhatsApp opt-in and templates outside the window, no general-purpose assistant | Social and WhatsApp channel code, agent builder | Partly done: the 24-hour window |
| 3.6 | YT-E2, YT-E4, YT-E6 | YouTube's upload contract (audience, AI disclosure, scheduling), streamed uploads and a per-business share of the 100 a day, analytics with dimensions | `ai/tools/social/youtube.py` | Partly done: the upload contract |
| 3.7 | GADS-E3, GADS-E5, GADS-E6 | Demand Gen campaigns with video ads, reports, operation counting | `ai/tools/social/google_ads.py` | Open |
| 3.8 | GOOG-E4 | The Google Picker for Drive files | Frontend, `catalog/google_drive.yaml` | Open |
| 3.9 | LI-E5, X-E7 | One client per provider: the LinkedIn and X tools stop using the old `social_connections` path | `ai/tools/social/`, `connections/client.py` | Open (with WS9) |
| 3.10 | SH-E5, GOOG-E9 | Security headers on `app.` and `gateway.` (HSTS, CSP), dependency and container scans in CI, the CASA pre-assessment | Ingress and nginx configuration, CI | Open |

## What was built (28 Oct 2026)

| Item | What changed | Main files | Tests |
|---|---|---|---|
| 1.1, 1.2 | `LINKEDIN_API_VERSION` = `202610` for the connector and the tools; `GOOGLE_ADS_API_VERSION` = `v26` with `GOOGLE_ADS_API_SUNSET`; `META_GRAPH_VERSION`; a start-up warning for a version near its end | `connections/api_versions.py`, `common/config.py`, `main.py` | unit |
| 1.3–1.5 | Scopes (`User.Read`, `pages_read_user_content`, `read_insights`, Gmail `gmail.modify` only); `login_config_id` → `config_id`; Google's granted scopes checked, the missing feature named | catalog YAML, `providers/meta.py`, `providers/oauth.py` | unit, integration |
| 1.6–1.9 | A refused mailbox password → `needs_reconnect`, triggers paused, owners told (`service.mark_needs_reconnect`); Microsoft refused on the password path; Mailbox presets (`select` field, help text); `after_disconnect` advice in the revoke answer and on screen | `connections/mail/__init__.py`, `providers/forms.py`, `automation/pollers/`, `ai/tools/email/email_tool.py`, `ai/email_router.py`, `catalog.py`, frontend | unit, integration, browser |
| 1.10 | A disclosure before every reviewed connector's sign-in, with the privacy policy (`PRIVACY_POLICY_URL`) | catalog `disclosure`, `ConnectionsPage.tsx` | unit, browser |
| 1.11 | GitHub `suspend`/`unsuspend` and `installation_repositories`; code lanes name a removed repository | `connections/webhooks.py`, `code_lanes/github.py` | integration |
| 1.12 | YouTube analytics' last 28 days; moderation `POST`; Google Ads without `VIDEO` creation or Enhanced CPC, with the EU political ads declaration and `login-customer-id` | `ai/tools/social/youtube.py`, `google_ads.py` | unit |
| 2.1 | **Connector writes wait for a person**: a run's `email_send` or `social_api` write becomes a PENDING approval (`context_snapshot.kind = connector_action`) holding the exact call; the inbox shows "What will be sent (exactly)"; approving carries it out once and bills it; rejecting sends nothing | `ai/governance/connector_actions.py`, `ai/tool_executor.py`, `ai/router.py`, `HITLPanel.tsx` | unit, integration |
| 2.2, 2.3 | Gmail through the Gmail API (history-based new mail, read, draft, send, label) and Outlook through Microsoft Graph (new mail by time, MIME read, draft, send, folder) for the poller and the four mail tools | `connections/mail/apis.py`, `automation/pollers/mailbox.py`, `ai/tools/email/email_tool.py`, `connections/client.py` | unit |
| 2.4 | Microsoft's "admin approval needed" explained; `POST /api/v1/connections/admin-consent` gives the administrator's link; the callback says when it was granted | `providers/oauth.py`, `service.py`, `api.py`, `ConnectionsPage.tsx` | unit |
| 2.5 | Meta's data deletion and deauthorise callbacks (signed request verified), `meta_user_id` recorded at connect, `provider_deletion_requests` (control migration `control_0023_provider_deletions`), a public status page per confirmation code | `connections/deletion.py`, `webhooks.py`, `models.py` | unit, integration |
| 2.6 | Disconnecting deletes the events stored from the connection (lifecycle events stay) and its poll cursor | `service.revoke` | integration |
| 2.7 | `youtube_channel` and `google_ads` connectors (`planned`) on `oauth-app-google-marketing`; the channel and the reachable Ads customers are the accounts | catalog, `providers/oauth.py`, `client.py`, `register_app.py` | unit |
| 2.8, 2.9 | X: the same text from another account in 7 days refused; `x-rate-limit-reset` honoured and explained; each post billed as `x_post` or `x_post_link` | `ai/tools/social/twitter.py`, `base.py`, `social_api.py` | unit |
| 3.2 | **Prompt-injection screening**: mail, comments and messages in tool results and in provider-triggered runs screened (Azure Prompt Shields when configured, patterns otherwise) and quoted; an attack withheld | `ai/governance/untrusted.py`, `tool_executor.py`, `automation/router.py` | unit |
| 3.5 (part) | Messenger replies only within 24 hours of the person's last message | `ai/tools/social/facebook.py` | unit |
| 3.6 (part) | YouTube uploads need `made_for_kids` and `contains_synthetic_media`; `publish_at` schedules (private until then) | `ai/tools/social/youtube.py` | unit |

Checks run on 28 Oct 2026: the unit tier, 2,878 passed (2 skipped), including the strict type check and the route census (regenerated: `docs/reference/api-routes.md`); 102 integration tests in the suites for connections, approvals, mail, social, webhooks, idempotency, tenancy and the schema census, all passing; the frontend's `tsc` and `eslint`; and the Connections page in the browser (the disclosure, the provider select, an Outlook address refused).

## To deploy

1. Run the control migration (`control_0023_provider_deletions`) with the release.
2. **Meta app** (console): *Data deletion request URL* `https://<gateway>/webhook/provider/meta/data-deletion`; *Deauthorize callback URL* `https://<gateway>/webhook/provider/meta/deauthorize`; `login_config_id` on the app's registry row if the app uses Facebook Login for Business.
3. **Registry prices** for `x_post` and `x_post_link` (X's current per-post prices); until then X posts are recorded as unpriced usage.
4. **Prompt Shields**: an Azure AI Content Safety resource; `CONTENT_SAFETY_ENDPOINT` and the key's secret name `CONTENT_SAFETY_KEY_NAME` in Key Vault. Without them, nothing is withheld.
5. **The marketing app**: register `oauth-app-google-marketing` (provider `google-marketing`) when the Google project of [09](09_youtube_and_google_ads.md) exists.
6. Check `PRIVACY_POLICY_URL`, `DATA_DELETION_URL` and `PRIVACY_CONTACT_EMAIL` once the pages of [11](11_website_content/README.md) are live.
7. Agents that send e-mail or post without a person today now wait in *Approvals*. Tell businesses; staff can exempt a tool for the platform's own use with `CONNECTOR_ACTION_APPROVAL_EXEMPT`.

## Design notes for what remains

* **3.1 Retention by source (SH-E2).** Mark each tool result with its connector and account (the tool executor knows both); store the mark on `tool_interaction_log` rows, trace spans and CORTEX nodes written from them. A nightly job redacts marked content past its provider's limit (LinkedIn member activity 48 h, profile fields 24 h; X content 24 h after deletion on X; YouTube 30 days) and, on disconnect, the account's marked content. Records written by agents carry the source run, so LinkedIn and X writes can be refused at the records engine (LI-E3).
* **3.3 Staff access (SH-E6).** Trace and run views redact marked connector content for platform staff unless the business has granted time-boxed support access (the partner grants of M15.4 are the model); the grant and each view are audited.
* **3.5 (rest).** The AI disclosure as the first message of a Messenger, Instagram or WhatsApp conversation and after a hand-back; a "talk to a person" path that parks the conversation for the team; WhatsApp opt-in records per contact, templates outside the service window, and no general-purpose assistant in the agent builder for WhatsApp (META-E5).
* **3.6 (rest), 3.7.** Streamed resumable uploads from tenant storage with a per-business share of the 100 uploads a day; analytics dimensions and Reporting API jobs; Demand Gen campaigns with video responsive ads, a monthly spending ceiling per business, report templates and operation counting.
* **3.8 Google Picker.** A "Choose files" step on the Drive connector; the picked file ids stored on the connection; `read_file` limited to them.
* **3.9, 3.10.** The LinkedIn and X tools stop using `social_connections` with WS9; HSTS and CSP on the app's nginx and ingress, and dependency and container scans in CI, before the CASA pre-assessment.

## Already in place (checked, kept)

* **GOOG-E7:** a refresh that fails (`invalid_grant`) marks the connection `needs_reconnect`, pauses its triggers and tells the owners once a day; it never loops (`connections/service.py` `_refresh_failed`).
* **LI-E6:** a token without a refresh token is flagged `expiring`, and its owners are warned `CONNECTION_EXPIRY_WARNING_DAYS` (7) before it lapses (`refresh_due`).
* GitHub webhooks are signed and an uninstalled App ends its connection (GH-E1 adds suspension).

## Order

1. Wave 1 in any order; 1.6–1.9 together (the mailbox), 1.10 before any recording.
2. 2.1 before any provider review: Google, YouTube and X require it.
3. 2.2 and 2.3 replace the IMAP path for Gmail and Outlook; the `imap_mailbox` connector keeps IMAP.
4. 2.5 before Meta's App Review (the data deletion URL).
5. Wave 3 after its design notes. 3.1 and 3.2 come before the Gmail CASA assessment.
