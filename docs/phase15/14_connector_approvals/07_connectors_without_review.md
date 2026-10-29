# 07 — Connectors that need no provider review

> **Researched:** 2026-10-28.
> These connect with the business's own credentials (a token, an app password, a server URL), so no provider reviews HireBuddha. The notes say what still limits them. §1 answers whether the app-password mailbox works for HireBuddha.

| Connector (catalog id) | Status | How it connects | What still applies |
|---|---|---|---|
| HubSpot (`hubspot`) | available | The business's **private app access token** | No review. If HireBuddha later offers *Connect with HubSpot* (OAuth), the app on HubSpot's developer platform 2025.2 is capped at **25 installations** until HubSpot's Ecosystem Quality team reviews and lists it on the HubSpot Marketplace (since 22 Sep 2025; private OAuth distribution for 10 customers, or 100 for Solution Partners, is the alternative) |
| Mailbox, IMAP and SMTP (`imap_mailbox`) | available | E-mail address and **app password** | Works for Gmail and most mail services, **not for any Microsoft mailbox** (§1). The fallback for Gmail until the Gmail review ends ([02](02_google.md)) |
| MCP server (`mcp_server`) | preview | The business's server URL and optional header | No review. The business supplies the server, so its tools are untrusted input: tools are discovered but can't run until granted (E09-S02), and SH-E3's screening applies to their outputs too |
| Other service, API key (`api_key`) | available | The business's key for any service | The business's own agreement with that service |
| Your own key for a service HireBuddha uses (`provider_api_key`) | available | The business's key in place of the platform's | The same; usage under that key is the business's with the provider |

## 1. The mailbox with an app password: does it work for HireBuddha?

Two code paths sign in to a mailbox with a password over IMAP and SMTP:

* the **Mailbox connector** `imap_mailbox` (Phase 14). Its form asks for an *App password* and defaults to Gmail's servers;
* the older **e-mail connections wizard** (`ai/email_router.py`, `EmailConnectionWizard.tsx`, table `email_connections`). It offers *Gmail* and *Outlook / Office 365* with app passwords, and goes away with the old tables (WS9).

Both read with IMAP `LOGIN` and send with SMTP `AUTH` on port 587 (`ai/tools/email/email_tool.py`, `automation/pollers/mailbox.py`).

**Answer: yes for Gmail and most other mail services, no for any Microsoft mailbox.** No provider reviews HireBuddha on this path, because it uses the business's own credential rather than HireBuddha's OAuth app. That makes it the quickest way to give businesses e-mail while the Gmail review ([02](02_google.md)) runs.

| Mailbox | Works? | Why | What the business needs |
|---|---|---|---|
| Gmail, personal | **Yes** | Google stopped accepting plain passwords for IMAP and SMTP on 14 March 2025 and kept app passwords as the exception | 2-Step Verification, then an app password (`myaccount.google.com/apppasswords`). Not offered with Advanced Protection, or when 2-Step Verification uses security keys only |
| Google Workspace | **Usually** | The same, but organisation accounts may not be offered the option | The admin leaves IMAP on (Gmail's *POP and IMAP access* setting) and doesn't require security keys only; the user turns on 2-Step Verification |
| Microsoft 365 work or school (Exchange Online), including Microsoft 365 bought through GoDaddy | **No** | Exchange Online switched off Basic authentication for IMAP and POP in every tenant from October 2022, and an app password is Basic authentication. SMTP AUTH with Basic authentication is switched off by default at the end of December 2026; an admin can turn it back on until Microsoft announces its final removal, expected in the second half of 2027 | The Outlook connector ([04](04_microsoft.md)) |
| Outlook.com, Hotmail, Live, MSN (personal) | **No** | Basic authentication ended for every Outlook.com account on 16 September 2024, app passwords included. IMAP and POP now need OAuth | The Outlook connector |
| Zoho Mail | Yes | IMAP with the account password, or an application-specific password when two-factor authentication is on | IMAP access turned on in Zoho Mail's settings (it is off by default) |
| Yahoo, iCloud | Yes | Both require an app-specific password for other mail apps | One created in the account's security settings |
| Mail from hosting providers (cPanel, Hostinger, Titan, GoDaddy Professional Email and similar) | Yes | Ordinary IMAP and SMTP with the mailbox password | The provider's IMAP and SMTP server names |

**What this path costs:**

* **A key to the whole mailbox.** An app password opens the whole mailbox over IMAP and SMTP and can't be limited to reading or to one folder. HireBuddha seals it under the business's key (`connections/crypto.py`) and never logs it. The rules no provider demands here still apply, because the risks are the same: prompt-injection screening (SH-E3), a person's approval before sending (SH-E4), and no staff reading mail without consent (SH-E6).
* **It fails silently today.** Google revokes every app password when the account's password changes. The poller then fails each cycle with the old password: `automation/pollers/__init__.py` records the error and tries again on the next poll, indefinitely. Nobody is told, and repeated failed logins can trip the provider's lockout (MAIL-E1).
* **Disconnecting can't revoke it.** HireBuddha deletes the stored password (SH-E1), but only the person can revoke the app password, at their provider (MAIL-E4).
* **Sending limits are the mailbox's own.** In Gmail, about 500 messages a day on a personal account and 2,000 on Workspace (over a rolling 24 hours), and at most 100 recipients per message over SMTP. That is enough for an AI employee answering mail, not for campaigns.
* **Google discourages it.** Google's help says app passwords aren't recommended and suggests *Sign in with Google*. It gives no end date (checked 28 Oct 2026), but this is the last password route into Gmail, so build the Gmail connector ([02](02_google.md)) for the long run.
* **Trust.** Some businesses' IT teams won't hand over a mailbox password. The Gmail and Outlook connectors answer that.

**Recommendation:**

1. Keep `imap_mailbox`, but present it as *Other mailbox (IMAP/SMTP)*, with presets and help for Gmail, Zoho, Yahoo, iCloud and custom servers (MAIL-E3).
2. Remove Microsoft from every password path now: the old wizard's *Outlook / Office 365* option can't work. Send Microsoft addresses to the Outlook connector (MAIL-E2).
3. Use it as Gmail's route until the Gmail connector is approved (GOOG-11 and CASA), with Gmail-specific help: 2-Step Verification, and the Workspace admin's IMAP setting.

### HireBuddha's own mail (`smtp-system`)

The platform's own e-mail (sign-up, password resets, invitations, notifications) goes through `common/email.py`, using the APP company's `smtp-system` row in the integration registry. Its default sender is `noreply@hirebuddha.com`, and the credentials guide suggests a Gmail app password for it (`docs/how-to/AI_MODEL_CREDENTIALS_GUIDE.md` §14). That works technically, with three problems:

* **hirebuddha.com has no mail service and no SPF, DKIM or DMARC records** ([08](08_website_readiness.md), WEB-02). Gmail's SMTP replaces a sender address that isn't the signed-in account's or verified for it, and mail from hirebuddha.com sent by any other server fails the SPF and DMARC checks that Gmail and Yahoo have required of senders since 2024.
* All platform mail depends on one person's app password, which is revoked when that person changes their Google password. Password resets would stop.
* Gmail's limit of 2,000 messages a day per user caps every customer's notifications together.

**Recommended:** send platform mail through a transactional e-mail service on hirebuddha.com, with its SPF, DKIM and DMARC records. Azure Communication Services Email fits production on Azure, and its connection string goes into Key Vault like the other secrets. Keep the Gmail app password for local development only (MAIL-E5).

### Engineering

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| MAIL-E1 | **Stop and tell when a password is refused**: when IMAP or SMTP reports an authentication failure, mark the connection `needs_reconnect`, pause its triggers and notify the business (the path `connections/service.py` already has for failed OAuth refreshes), instead of trying again on every poll | `automation/pollers/__init__.py`, `ai/tools/email/email_tool.py`, `connections/service.py` | A test: a wrong password gives one notification and no further logins | Done (code) |
| MAIL-E2 | **No Microsoft on the password path**: remove *Outlook / Office 365* and its help link from the old wizard (`PROVIDER_DEFAULTS`); in the Mailbox form, recognise Microsoft hosts and addresses (`outlook.office365.com`, `outlook.com`, `hotmail.com`, `live.com`) and point to the Outlook connector | `ai/email_router.py`, `frontend/src/components/EmailConnectionWizard.tsx`, the Mailbox connect form | A Microsoft address can't be saved on this connector | Done (code) |
| MAIL-E3 | **Presets and help per provider** (Gmail, Zoho, Yahoo, iCloud, custom), each with its steps for an app password or for turning IMAP on; the form stops defaulting to Gmail's servers | `connections/catalog/imap_mailbox.yaml`, connect UI | — | Done (code) |
| MAIL-E4 | **Disconnect text**: after deleting the password, tell the person to revoke the app password at their provider, with a link per preset | Connect UI | — | Done (code) |
| MAIL-E5 | **Platform mail through a transactional service** on hirebuddha.com (after WEB-02), not a person's app password; update §14 of the credentials guide | `common/email.py`, the `smtp-system` row, `docs/how-to/AI_MODEL_CREDENTIALS_GUIDE.md` | A password reset sent from production reaches a Gmail inbox with SPF, DKIM and DMARC passing | Open |

## 2. Social tools that aren't connectors yet

`backend/src/ai/tools/social/` also has tools for **YouTube**, **Google Ads**, **TikTok** and **Reddit**, which read tokens from the older `social_connections` table. None is in the connector catalog, and that table is dropped after the WS7 cutover.

* **YouTube** and **Google Ads:** researched in [09](09_youtube_and_google_ads.md).
* **TikTok:** TikTok's app review of each product (Login Kit, Content Posting API); posts from an unaudited client are limited (private only) until TikTok audits it. Not researched in depth.
* **Reddit:** Reddit's Data API terms; commercial use needs Reddit's agreement. Not researched in depth.

## 3. Sources

* Google (official): [Sign in with app passwords](https://support.google.com/accounts/answer/185833); [Transition from less secure apps to OAuth](https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth); [Gmail sending limits in Google Workspace](https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace); [Limits for sending and getting mail](https://support.google.com/mail/answer/22839)
* Microsoft (official): [Modern authentication needed for Outlook.com in other mail apps](https://support.microsoft.com/help/c5d65390-9676-4763-b41f-d7986499a90d); [Basic authentication deprecation in Exchange Online](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online); [MC786329: SMTP AUTH Basic authentication timeline](https://mc.merill.net/message/MC786329?from=1&to=4)
* Secondary: [Are app passwords being discontinued? (Microsoft Q&A, June 2024)](https://learn.microsoft.com/en-us/answers/questions/4682437/are-app-passwords-being-discontinued); [Zoho Mail IMAP settings (Instantly)](https://instantly.ai/blog/zoho-email-imap/)
* This repository: `backend/src/connections/catalog/imap_mailbox.yaml`, `backend/src/connections/client.py`, `backend/src/ai/email_router.py`, `backend/src/ai/tools/email/email_tool.py`, `backend/src/automation/pollers/`, `backend/src/common/email.py`, `frontend/src/components/EmailConnectionWizard.tsx`
