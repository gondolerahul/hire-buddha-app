# 04 — Microsoft: Outlook / Microsoft 365 mail

> **Researched:** 2026-10-28 · **Status:** Not submitted (catalog: `outlook_mail` is `planned`, approval `not_submitted`).
> **App:** multi-tenant Entra app registrations `HireBuddha` and `HireBuddha Dev` (`oauth-app-microsoft`, tenant `common`). How to create them: [provider guide §5](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md).
> **Lead time:** Partner Program enrolment and verification, usually 3–5 business days but it can stall for weeks; publisher verification minutes after that. **Cost:** free.
> **The real gate is each customer's tenant.** Microsoft doesn't review the app. Whether a business can connect depends on its Microsoft 365 consent settings, and the default now blocks users from granting mail access themselves (§2).

---

## 1. What Microsoft checks

1. **Publisher verification** (the blue *verified* badge): a verified Microsoft AI Cloud Partner Program (CPP) account linked to the app. Since November 2020, in tenants with risk-based step-up consent, users can't consent to newer multi-tenant apps from **unverified** publishers that ask for more than sign-in.
2. **Each customer tenant's consent policy** (§2) decides whether a user can consent or an **admin** must.
3. Optional, for enterprise buyers: **Microsoft 365 App Compliance** (Publisher Attestation, then Microsoft 365 Certification). Not needed to launch.

## 2. Consent: users can't approve mail access in most tenants

The *Let Microsoft manage your consent settings* policy is the **default for new tenants**. Under it, users may consent to delegated permissions **except** a list that includes `Mail.Read`, `Mail.ReadWrite`, `Mail.ReadBasic`, `MailboxSettings.*`, `Calendars.*`, `Files.Read.All`, `Contacts.ReadWrite`, and on Exchange Online `IMAP.AccessAsUser.All` and `POP.AccessAsUser.All`. A short list of well-known mail clients (Apple Mail, Thunderbird, Spark, eM Client, Android mail) is allowed separately; HireBuddha is not on it.

So in most business tenants **an admin must consent once for the organisation**, verified publisher or not. `Mail.Send` and `User.Read` are not on the excluded list. Personal Microsoft accounts (outlook.com) aren't affected.

## 3. Found in the code: the connector asks for Graph but uses IMAP

The connector requests `openid`, `email`, `offline_access`, `Mail.ReadWrite` and `Mail.Send` (Microsoft Graph). But the product reads and sends Outlook mail over **IMAP and SMTP with XOAUTH2** (`connections/client.py` `email_credentials` → `outlook.office365.com` / `smtp.office365.com`; `automation/pollers/mailbox.py`).

* IMAP and SMTP need `https://outlook.office.com/IMAP.AccessAsUser.All` and `https://outlook.office.com/SMTP.Send`: a token for **Exchange Online**, not Graph. One token can't serve both, so today's Graph token is refused at the IMAP login.
* `MicrosoftProvider.accounts` reads `https://graph.microsoft.com/v1.0/me`, which needs `User.Read`; the connector doesn't ask for it.
* SMTP AUTH is switched off in many tenants. Exchange Online disables SMTP AUTH Basic authentication by default for existing tenants at the end of December 2026 (MC786329), so expect even more admins to keep SMTP AUTH off.
* **App passwords are no way round this.** Exchange Online has refused Basic authentication for IMAP and POP since October 2022, and personal Outlook.com accounts since 16 September 2024; an app password is Basic authentication. So the old wizard's *Outlook / Office 365* app-password option and the Mailbox connector can't connect a Microsoft mailbox ([07](07_connectors_without_review.md) §1, MAIL-E2).

**Recommended:** read and send Outlook mail through **Microsoft Graph** (`/me/messages` or delta queries for new mail, `createReply` and drafts, `sendMail`). That matches the scopes already declared, avoids SMTP AUTH, and gives one token. Add `User.Read`.

## 4. Requirements

### A. Partner Program (publisher identity)

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| MS-01 | Enrol in the **Microsoft AI Cloud Partner Program** ([partner.microsoft.com](https://partner.microsoft.com)) with the legal name and address of SH-01. The primary contact must be a person whose name matches their ID, with an e-mail on `hirebuddha.com` (SH-02), not a personal address | Owner | Enrolment submitted | Open |
| MS-02 | Account **verification** completes (status *Authorised* / *Success*, no pending actions). If it stalls in *Pending* or is rejected without a working *Fix now*, open a Partner Center support request and ask for manual vetting; an appeal is offered in Partner Center | Owner | Verified | Open |
| MS-03 | Note the **Partner One ID of the partner global account (PGA)**, not a *location* ID: location IDs fail publisher verification | Owner | ID recorded in the tracker | Open |
| MS-04 | Associate HireBuddha's Entra tenant (the one holding the app registrations) with the PGA (*Account settings → Tenants*) | Owner | Tenant listed | Open |
| MS-05 | The person who verifies holds **Application Administrator** (or Cloud Application Administrator) in Entra **and** CPP Partner Admin (or Account Admin) in Partner Center, and signs in with MFA | Owner | Roles assigned | Open |

### B. The app registrations

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| MS-06 | Registered with a **work or school account** in that tenant (apps registered with a personal Microsoft account can't be verified) | Owner | — | Open |
| MS-07 | **Publisher domain** `hirebuddha.com` as a DNS-verified custom domain (SH-03), not `*.onmicrosoft.com`. The domain of the e-mail used in the CPP verification must match it | Owner | *Branding & properties* shows it | Open |
| MS-08 | *Branding & properties*: name, logo (SH-11), home page (SH-06), terms (SH-08), privacy (SH-07) | Owner | — | Open |
| MS-09 | Redirect URIs (Web) for the SH-12 hostnames; supported accounts "any organisational directory and personal Microsoft accounts" | Owner | — | Open |
| MS-10 | **API permissions declared on the registration** (Graph, delegated): `openid`, `email`, `offline_access`, `User.Read`, `Mail.ReadWrite`, `Mail.Send`. Declared permissions are what an admin consents to for the whole organisation | Owner | — | Open |
| MS-11 | Client secret (24 months; put its expiry in the calendar) or a certificate, in Key Vault | Owner | Expiry diarised | Open |
| MS-12 | *Branding & properties → Add verified publisher* → Partner One ID (MS-03) → **Verify** | Owner | The consent prompt shows the blue badge | Open |

### C. Engineering

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| MS-E1 | **Mail through Microsoft Graph**, not IMAP/SMTP, for `outlook_mail` (§3); IMAP/SMTP stay for the `imap_mailbox` connector | `automation/pollers/mailbox.py`, `ai/tools/email/email_tool.py`, `connections/client.py` | Read, draft and send work on dev with the Graph token | Done (code) |
| MS-E2 | Add `User.Read` to `outlook_mail.yaml` (the account lookup calls Graph `/me`) | `connections/catalog/outlook_mail.yaml` | Connect works for a work and a personal account | Done (code) |
| MS-E3 | **Admin consent path**: when Microsoft answers that admin approval is needed, say so plainly and offer (a) a link for an admin to grant consent for the organisation (`https://login.microsoftonline.com/{tenant}/adminconsent?client_id=…&redirect_uri=…`, or `/v2.0/adminconsent` with `scope=https://graph.microsoft.com/.default`), handling its callback (`admin_consent`, `tenant`), and (b) the text to send the admin. Users in tenants with the admin-consent workflow can also *request approval* from Microsoft's own screen | `connections/providers/oauth.py`, `connections/api.py`, connect UI | A test tenant with the default policy connects after admin consent | Done (code) |
| MS-E4 | **Disconnect**: Microsoft offers no token revocation for this flow. Delete the tokens (SH-E1) and tell the business how an admin removes the app (*Entra → Enterprise applications*) or a user does (*My Apps*) | `connections/service.py`, help text | — | Done (code) |
| MS-E5 | The shared items that reviewers and enterprise admins ask about: SH-E3, SH-E4, SH-E6 | — | — | Partly done (code) |

### D. After verification

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| MS-20 | Connector to *Preview*, then *Available*; publisher verification recorded on *Platform Console → Connectors* | Eng | Catalog row `approved` | Open |
| MS-21 | A help article for business admins: what HireBuddha reads and sends, the admin consent link, how to restrict it to a group (*Enterprise applications → Properties → Assignment required*) and how to remove it | Owner + Eng | Linked from the connect screen | Open |
| MS-22 | Optional later: Microsoft 365 **Publisher Attestation** (a questionnaire on security and data handling) when enterprise customers ask | Owner | — | Open |

## 5. Common problems and how they were resolved

Sources: Microsoft Learn troubleshooting and Q&A threads (§6). Reddit could not be opened from this environment.

| Problem | Usual cause | What fixed it |
|---|---|---|
| "MPN ID / Partner One ID does not exist" or is invalid when verifying | A *location* ID was entered, or the ID is from an unverified account | Use the PGA's Partner One ID (MS-03) once verified (MS-02) |
| Verification refused: user not authorised | Missing role in Partner Center or Entra | MS-05 |
| Verification refused: tenant not associated | The app's tenant isn't linked to the PGA | MS-04 |
| Verification refused: domain mismatch | The CPP verification e-mail's domain isn't the publisher domain or a verified custom domain | MS-07; use an `@hirebuddha.com` contact in MS-01 |
| Partner Center identity verification rejected, *Fix now* does nothing | A personal e-mail as primary contact, or a name not matching the ID; sometimes automated risk checks (including after a D-U-N-S match) | Correct the contact to a company-domain address and a matching name; open a support request asking for manual vetting; use the appeal |
| Program stuck in *Pending qualification* | Verification queue | Support request routed to enrolment and verification |
| "Unverified" warning on the consent screen; users can't consent | Publisher not verified | MS-12 |
| "Need admin approval" even after verification | The tenant's policy excludes Mail permissions (§2) | MS-E3, MS-21 |
| IMAP login fails with a valid token | The token is for Graph, not Exchange Online | MS-E1 |
| Sending fails with "SMTP AUTH disabled" | SMTP AUTH turned off for the tenant or mailbox | MS-E1 (Graph `sendMail`) |
| *AUTHENTICATE failed* when connecting Outlook with an app password (the Mailbox connector or the old wizard) | Basic authentication is off for Exchange Online and Outlook.com | The Outlook connector (MS-E1); MAIL-E2 removes the option |

## 6. Sources

* Microsoft (official): [Publisher verification overview](https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview); [Troubleshoot publisher verification](https://learn.microsoft.com/en-us/entra/identity-platform/troubleshoot-publisher-verification); [Manage app consent policies (the Microsoft-managed policy's exclusions)](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/manage-app-consent-policies); [Authenticate IMAP, POP or SMTP with OAuth](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth); [Partner Center verification responses](https://learn.microsoft.com/en-us/partner-center/enroll/verification-responses); [MC786329: SMTP AUTH Basic auth retirement timeline](https://mc.merill.net/message/MC786329?from=1&to=4); [Basic authentication deprecation in Exchange Online](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online); [Outlook.com: modern authentication needed in other mail apps](https://support.microsoft.com/help/c5d65390-9676-4763-b41f-d7986499a90d)
* Q&A (secondary): [MPN ID does not exist](https://learn.microsoft.com/en-us/answers/questions/2120636/azure-app-publisher-verification-mpn-id-does-not-e); [Identity verification rejected, Fix now unresponsive](https://learn.microsoft.com/en-in/answers/questions/5916765/partner-center-identity-verification-rejected-fix); [Pending qualification since 23 Sep](https://learn.microsoft.com/en-us/answers/questions/6047007/publisher-verification-fails-partner-center-tenant); [Enrolment blocked after D-U-N-S](https://learn.microsoft.com/en-us/answers/questions/5911891/microsoft-ai-cloud-partner-program-enrollment-bloc); [Verified publisher: wrong assumptions (Tech Community)](https://techcommunity.microsoft.com/discussions/partnershelpingpartnerstechtopics/psa-verified-publisher-wrong-assumptions/4298586)
* This repository: `backend/src/connections/catalog/outlook_mail.yaml`, `backend/src/connections/providers/oauth.py` (`MicrosoftProvider`), `backend/src/connections/client.py`, `backend/src/automation/pollers/mailbox.py`
