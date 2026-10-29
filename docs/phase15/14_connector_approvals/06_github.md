# 06 — GitHub

> **Researched:** 2026-10-28 · **Status:** Not started (catalog: `github` is `planned`, approval `not_submitted`).
> **App:** two GitHub Apps in HireBuddha's GitHub organisation, `HireBuddha` and `HireBuddha Dev` (`oauth-app-github`). How to create them: [provider guide §8](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md).
> **Lead time:** an hour. **Cost:** free. **Review:** none for a public GitHub App. The GitHub Marketplace listing is optional (§3).

---

## 1. What GitHub checks

Nothing before launch: a GitHub App set to install on *any account* can be installed by any organisation or user. What decides adoption is each customer: the **organisation owner approves** the installation and the permissions, and organisations may restrict which apps members can install.

## 2. Requirements

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| GH-01 | The Apps belong to HireBuddha's **organisation** (not a person), which has a **verified domain** `hirebuddha.com` (SH-03) and requires 2FA of its members (SH-04) | Owner | Organisation shows the verified badge | Open |
| GH-02 | **Least permissions**: Contents, Pull requests, Issues and Checks read and write; Metadata read. Ask for **Administration: write** only if businesses must let HireBuddha create repositories in their organisation (the `create_repository` action). It is the permission organisation owners hesitate over most, so consider having the business create the repository and HireBuddha only push to it | Owner + Eng | The permissions list matches the actions the product uses | Open |
| GH-03 | Public page of the App: description of what HireBuddha does with repositories, homepage, privacy policy (SH-07) and support contact (SH-02) | Owner | — | Open |
| GH-04 | Webhook URL for the SH-12 hostname with its secret; private key and client secret in Key Vault ([guide §8](../../how-to/PROVIDER_APP_REGISTRATION_GUIDE.md)) | Owner | — | Open |
| GH-05 | *Expire user authorisation tokens* on (8-hour tokens with refresh tokens), if HireBuddha uses user-to-server tokens at all. Installation tokens already last an hour (`connections/providers/github.py`) | Owner | — | Open |

### Engineering (already in place, keep it so)

* Webhook payloads are checked against `X-Hub-Signature-256` with the App's webhook secret (`connections/webhooks.py`).
* An `installation` event with `deleted` ends the connection.
* Disconnect deletes the installation (`GitHubProvider.revoke`).

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| GH-E1 | Also handle `installation` `suspend` / `unsuspend` and `installation_repositories` `removed` (the business took a repository away) so agents stop, rather than fail, on those repositories | `connections/webhooks.py` | A test per event | Done (code) |

## 3. Optional: GitHub Marketplace

Only if HireBuddha wants a listing, or billing through GitHub later:

* Listing requirements: valid publisher contact, a description, a pricing plan, privacy policy and support links; the app must give value beyond sign-in, be public (not invite-only or a preview), and receive Marketplace webhooks for plan changes and cancellations. Organisation owners submit it.
* **Paid plans** need a **verified publisher** organisation (contact, 2FA, verified domain) and at least **100 installations**, and must handle Marketplace purchase events.

## 4. Sources

* GitHub (official): [Requirements for listing an app](https://docs.github.com/en/apps/github-marketplace/creating-apps-for-github-marketplace/requirements-for-listing-an-app); [Marketplace badges and verified publishers](https://docs.github.com/en/apps/github-marketplace/github-marketplace-overview/about-marketplace-badges); [Pricing plans for a listing](https://docs.github.com/en/apps/github-marketplace/listing-an-app-on-github-marketplace/setting-pricing-plans-for-your-listing)
* This repository: `backend/src/connections/catalog/github.yaml`, `backend/src/connections/providers/github.py`, `backend/src/connections/webhooks.py`
