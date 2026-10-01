# 04. Authentication, RBAC & Multi-Tenancy — Defect Register

> **What this document is:** defects in who a request is, what it is allowed to do, and
> whose data it can reach — plus the improvements that would make those three questions
> answerable in one place instead of forty.
> **Source document:** [`04-auth-rbac-tenancy.md`](../04-auth-rbac-tenancy.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this is the highest-severity register in the set. Two of the entries are
> straightforward privilege escalation and one is an unauthenticated credential store.

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `04-auth-rbac-tenancy.md`, not independently re-checked.
- The tiers here are about **blast radius**, not effort. Several T0 items are one-line
  fixes.
- Tenant isolation on this platform is a convention, not a mechanism. There is no
  row-level security and no query filter. Every one of the ~40 tables is protected by a
  `WHERE company_id = ...` that a developer remembered to type. Read
  [§6 Improvements](#6-improvements) with that in mind — most of them are about making
  the boundary structural.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Privilege escalation and open doors](#2-t0--privilege-escalation-and-open-doors)
3. [T1 — Controls that are not enforced](#3-t1--controls-that-are-not-enforced)
4. [T2 — Missing pieces](#4-t2--missing-pieces)
5. [T3 — Inconsistency and dead weight](#5-t3--inconsistency-and-dead-weight)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--privilege-escalation-and-open-doors) | Privilege escalation and open doors | 6 | **Now** — before any real customer data exists |
| [T1](#3-t1--controls-that-are-not-enforced) | Controls that are not enforced | 8 | Before relying on the control |
| [T2](#4-t2--missing-pieces) | Missing pieces | 5 | Before launch |
| [T3](#5-t3--inconsistency-and-dead-weight) | Inconsistency and dead weight | 6 | When the area is next touched |

**Total: 25 defects, 10 improvements.** (AU-23 to AU-25 were found on 2026-10-01, while fixing the rest.)

The three to read before anything else:

- **[AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin)** — a `tenant_admin`
  can make themselves `app_admin` with one PATCH. That is full platform access.
- **[AU-02](#au-02--the-email-connection-api-has-no-authentication-at-all)** — five
  routes that create, read, delete and test **SMTP/IMAP credentials**, with no auth.
- **[AU-03](#au-03--any-user-can-suspend-their-own-company)** — a `tenant_user` can lock
  their whole company out of the platform, admins included.

---

## 2. T0 — Privilege escalation and open doors

### AU-01 — Any admin can promote themselves to `app_admin`

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — worse than recorded: the
self-edit branch let **any** user, `tenant_user` included, PATCH their own role.

`PATCH /api/v1/users/{user_id}` checks two things — same company, and caller is one of
`app_admin` / `partner_admin` / `tenant_admin` — and then does this:

```python
update_data = user_update.model_dump(exclude_unset=True)
for field, value in update_data.items():
    setattr(user, field, value)
```

`UserUpdate` declares `role: Optional[str] = None`. Nothing validates the value.

So a `tenant_admin` can PATCH **their own user row** with `{"role": "app_admin"}` and
become a platform superuser. From there, `app_admin` short-circuits the tenant filter
everywhere, which turns this into a full-database read across every tenant.

The stricter `create_user_as_admin` **does** validate which roles a caller may assign.
The update path simply never got the same treatment.

- [`auth/user_router.py:48`](../../../backend/src/auth/user_router.py:48) — `update_user`
- [`auth/schemas.py`](../../../backend/src/auth/schemas.py) — `UserUpdate.role`
- [`auth/service.py:52`](../../../backend/src/auth/service.py:52) — the correct pattern, for contrast

**Fix:** run the same assignable-role check the create path uses, and refuse a role
change on the caller's own row entirely.

**Done (2026-09-30).** The route also let a non-admin through when `current_user.id ==
user_id`, and then applied every field — so a `tenant_user` could set its own `role` (or
`is_active`) too.

- `auth/roles.py` — a `Role` enum (`StrEnum`, so it compares and hashes as the stored
  string), `USER_ADMIN_ROLES`, and `assignable_roles(role)`: `app_admin` any role,
  `partner_admin` the four partner/tenant roles, `tenant_admin` the two tenant roles.
- `UserUpdate.role` and `UserCreateAdmin.role` are typed `Role`: an unknown string is a 422.
- `PATCH /users/{id}` calls `service.update_user_as_admin`. Anyone may change their own
  `full_name`. Anything else needs a user admin of the target's company (a partner admin:
  its own company and its tenants — before, partner admins could not edit their tenants'
  users at all); the target's current role and the new role must both be assignable by the
  caller; nobody changes their **own** role or active status. Resending the current role
  or `is_active` is not a change, so the edit form still saves.
- `create_user_as_admin` uses the same table and company check.

**Evidence:** `tests/unit/test_user_role_escalation.py` — 17 cases through the router: all
five non-`app_admin` roles are refused a self-promotion and nothing is committed;
`app_admin` cannot change its own role; nobody reactivates themselves; a self-rename that
resends the current role saves; a tenant admin cannot grant any partner/app role, can
promote and deactivate a colleague, and a plain user cannot edit a colleague; a partner
admin manages its tenant's users but not another partner's, and cannot grant `app_admin`;
`"tenant-admin"` is a 422. 13 of the 17 fail on the old code. Live on the local API: a
freshly registered `tenant_admin` PATCHing `{"role": "app_admin"}` onto itself got 403,
`"superuser"` 422, a rename 200, and `/auth/me` still said `tenant_admin`.

---

### AU-02 — The email connection API has no authentication at all

**✅ Verified · Critical** · **Status: fixed (2026-09-30)**

All five routes on `/api/v1/email/*` depend on `get_db` and nothing else. No
`get_current_user`, no `RoleChecker`.

```
POST   /email/connections            create
GET    /email/connections            list
DELETE /email/connections/{id}       delete
POST   /email/connections/{id}/validate
GET    /email/provider-defaults
```

The router creates, lists, deletes and validates **SMTP/IMAP credentials**. That makes
it the highest-value unauthenticated surface in the tree.

Two of the routes are worse than "unauthenticated": `DELETE` and `validate` look up by
`connection_id` alone with no ownership check. `validate` **decrypts another tenant's
app password and attempts an IMAP login with it**.

The code's own comment admits the design:

```python
# current_user will be injected by auth middleware in production
company_id: Optional[str] = None
```

There is no such middleware. `CompanySuspensionMiddleware` injects nothing and lets a
request with no `Authorization` header straight through.

- [`ai/email_router.py:88`](../../../backend/src/ai/email_router.py:88), [`:94`](../../../backend/src/ai/email_router.py:94), [`:159`](../../../backend/src/ai/email_router.py:159), [`:179`](../../../backend/src/ai/email_router.py:179), [`:204`](../../../backend/src/ai/email_router.py:204)
- [`ai/social_router.py`](../../../backend/src/ai/social_router.py) — the same feature, done correctly
- Also recorded as **D-04** in the platform register

**Fix:** add `get_current_user_and_company` and scope every query. Copy
`social_router.py`, never this file.

**Done (2026-09-30).** Every route depends on `get_current_user_and_company` (so an
anonymous call is a 401 before any query). List and create use the caller's company; the
`company_id` query parameter is gone, and one sent anyway is ignored. Delete and validate
go through `_get_own_connection`, which matches on id **and** company and answers 404
otherwise — so another tenant's app password is never decrypted. The frontend
(`email.service.ts`, `EmailConnectionWizard`, `IntegrationsPage`) no longer sends a company
id.

**Evidence:** `tests/unit/test_email_router_auth.py` — all five routes return 401 without a
token and never reach the database. `tests/integration/test_email_connection_scope.py` —
against the real Postgres: list shows only the caller's company even with another
company's id in the query string; create lands in the caller's company; another company's
connection cannot be deleted (404, row still there) and is never decrypted or logged into
(404, no IMAP call); the caller's own connection validates and deletes. 9 of the 10 fail
on the old code. Live on the local API: anonymous calls to all five routes got 401; tenant
B listing with tenant A's company id got `[]`, and validating or deleting A's connection got
404 while A still saw it and could delete it.

---

### AU-03 — Any user can suspend their own company

**✅ Verified · Critical** · **Status: fixed (2026-09-30)** — with AU-15.

`PATCH /api/v1/companies/{company_id}` guards on company match only:

```python
if current_user.role != "app_admin" and current_user.company_id != company_id:
    raise HTTPException(status_code=403, detail="Not authorized to update this company")
```

There is **no role check**. Any authenticated user — including a `tenant_user` — can
PATCH their own company with `{"status": "suspended"}` and lock the entire company out
of the platform, its admins included. Nothing else in the product sets that status, so
recovery needs an `app_admin`.

The inline comment on the next line (`Also allow partner admins to update their own
tenants?`) shows this was known to be unfinished.

- [`auth/company_router.py:110`](../../../backend/src/auth/company_router.py:110) — `update_company`

**Fix:** add a role check. `status` in particular should be `app_admin` only.

**Done (2026-09-30), with [AU-15](#au-15--partner-admins-cannot-manage-the-tenants-they-create).**
`update_company` now separates the two changes it allows:

| Change | `app_admin` | `partner_admin` | `tenant_admin` | everyone else |
|---|---|---|---|---|
| `name` | any company | its own company and its tenants | its own company | — |
| `status` | any company **but its own** | its own tenants | — | — |

Nobody changes the status of their own company — an `app_admin` suspending the APP company
would lock out every platform admin. Resending the current status is not a change, so an
edit form that sends it back still saves. `CompanyUpdate.status` is
`Literal["active", "suspended"]`; anything else is a 422.

**Evidence:** `tests/unit/test_company_update_access.py` — 16 cases through the router: all
six roles are refused suspending their own company and nothing is committed; the three
plain roles cannot rename it; both admin roles rename it while resending its status; a
partner admin renames and suspends its own tenant but not another partner's; a tenant
admin cannot touch another company; an `app_admin` suspends a partner; `"deleted"` is a
422. 11 fail on the old code. Live on the local API: a partner admin (created by the
`app_admin`) created a tenant, renamed and suspended it (200), and got 403 suspending its
own partner company; a registered tenant admin got 403 suspending its own company, 200
renaming it, 403 renaming the partner's tenant, and could still use the API afterwards.

---

### AU-04 — `is_active` is never checked, so deactivating a user does nothing

**✅ Verified · High** · **Status: fixed (2026-09-30)**

`users.is_active` exists, defaults to `True`, is editable through `UserUpdate`, and is
shown in the partner dashboard. Neither `authenticate_user` nor `_authenticate_user`
ever reads it.

An admin who deactivates a user in the UI sees the flag flip and reasonably believes
that person is locked out. They can still log in and still use every API.

- [`auth/service.py`](../../../backend/src/auth/service.py) — `authenticate_user`
- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py) — `_authenticate_user`

**Fix:** reject inactive users in `_authenticate_user`, next to the existing suspension
check. One line.

**Done (2026-09-30).** Four places, not one — each is a way back in:

| Path | Deactivated user gets |
|---|---|
| Any authenticated request (`_authenticate_user`) | 401 *This account has been deactivated* |
| `POST /auth/login`, `/auth/token` with the right password (`authenticate_user` → `require_active`) | 403, same message. A wrong password is still a plain 401, so the 403 does not confirm the account to someone without the password |
| `POST /auth/refresh` (`verify_refresh_token`) | 401 |
| `POST /auth/oauth/{provider}` (`require_active` on the upserted user) | 403 |

The 401 on requests makes the frontend try a refresh, which fails, and send the user to the
login page, which shows the 403's message.

**Evidence:** `tests/unit/test_auth_token_checks.py` — a deactivated user's token is
refused; the right password is a 403 and a wrong one still returns nothing; refresh and
OAuth refuse. Live on the local API: an `app_admin` deactivated a registered user; the
user's existing token got 401 *This account has been deactivated*, login with the right
password 403, a wrong password 401, refresh 401; after reactivation login worked again.

---

### AU-05 — Access tokens cannot be revoked

**✅ Verified · High** · **Status: fixed (2026-09-30)** — through [AU-I3](#au-i3--add-token_version-to-users), with AU-09 and AU-12.

The JWT carries `sub`, `company_id` and `exp`. There is no `jti`, no denylist, and no
logout endpoint. Logging out clears `localStorage` on the client and nothing else.

A stolen access token is valid for up to 30 minutes and nothing can stop it. A stolen
refresh token is valid for up to 7 days — see
[AU-09](#au-09--refresh-token-reuse-is-detected-and-ignored).

- [`common/security.py`](../../../backend/src/common/security.py) — `create_access_token`
- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py) — the validator

**Fix:** the cheapest version is a `token_version` integer on `users`, put in the token
and compared on every request. Bumping it invalidates every token for that user
instantly, which also gives [AU-09](#au-09--refresh-token-reuse-is-detected-and-ignored)
somewhere to act.

**Done (2026-09-30)** — that version. `users.token_version` (revision `au05_token_version`,
default 0) is minted into every access token as `tv` by `issue_access_token`, and
`_authenticate_user` refuses a token whose `tv` differs. `service.revoke_all_sessions(user)`
bumps it and revokes every refresh token; it is what logout-everywhere (AU-12), reuse
detection (AU-09) and password reset (AU-06) call. Revocation is per user, not per token —
there is still no `jti`. Access tokens minted before the change carry no `tv`, so each
browser refreshes once.

**Evidence:** `tests/integration/test_session_revocation.py` (real Postgres, rolled back), 7
cases — ending all sessions refuses an existing access token while a new login works; an
access token without `tv` is refused; presenting a rotated refresh token again kills the
current refresh token and the access token; logout ends only its own session; logout with
`all_sessions` ends every refresh and access token; logging out twice does not trip reuse
detection; the route answers 204 even for an unknown token. Live on the local API, one
registered user with several sessions: after `POST /auth/logout` session A's refresh got
401 while session B's still refreshed; presenting B's rotated token again got 401 and then
B's current refresh token and access token both got 401; `all_sessions` from session C
made session D's access token and refresh token 401, and a new login worked.

### AU-23 — An OAuth login can sign in as any existing account

**✅ Verified · Critical** · **Status: backend fixed (2026-10-01); the frontend half is open**
— found 2026-10-01 while recording new defects. The design doc listed the ingredients
(§12.1, items 2 and 3), but no register entry did.

`POST /auth/oauth/{provider}` exchanges the code, reads the provider's profile, and signs
into **the existing account with that email**. It created one only if none existed. Two
inputs made that email attacker-controlled:

- **Microsoft:** the email was `mail or userPrincipalName` from Graph `/me`, through the
  `common` authority, which accepts any Entra tenant. `mail` is an attribute the user's own
  tenant admin sets to any string. An attacker with a free tenant sets it to the victim's
  address and signs in as the victim. It was not a fallback problem: `mail` came first.
- **Google:** `email` was used without checking `email_verified`.

The endpoint is live whenever the provider's client id and secret are set, even though no
UI reaches it (below).

**Fixed (backend):** `_verified_email` in `auth/router.py` takes Google's `email` only
when `email_verified` is true (otherwise 400). For Microsoft it takes `userPrincipalName`,
whose domain must be one the user's tenant has verified, or the user's own Microsoft
account. It never takes `mail`. The address is lower-cased, and `get_or_create_oauth_user`
matches it case-insensitively. An existing account that never verified its email is marked
verified, because the provider has just proved it. Before, the account got a token that
every route then refused.

**Open (frontend; register 16):**
- The SPA sends **no `state`**. `oauth.service.ts` builds both authorize URLs without one,
  so the callback cannot reject a forged redirect (login CSRF). `OAuthCallback.tsx` also
  reads `state` as the provider name, so the callback fails ("Invalid OAuth state") even on
  a genuine login.
- The Login page's Google and Microsoft buttons have no `onClick`.

The fix there is a random `state` (with the provider inside it) kept in `sessionStorage`
and compared on return, plus PKCE.

**Evidence:** `tests/unit/test_oauth_identity.py` drives the real router against a fake
provider. A Microsoft profile with `mail=victim@…` and a different UPN signs in as the
UPN. A Google profile with `email_verified=false` is a 400 and links nothing.
`tests/integration/test_oauth_account_link.py` checks that an existing unverified
`…@Example.com` account is found from `…@example.com` and verified. All three fail on the
old code.

---

## 3. T1 — Controls that are not enforced

### AU-06 — Password reset works in the browser and does not exist in the backend

**✅ Verified · High** · **Status: fixed (2026-09-30)** — with AU-07 and AU-08.

The frontend has a complete two-page reset flow, routed at `/forgot-password` and
`/reset-password`. It calls `POST /auth/forgot-password` and `POST /auth/reset-password`.

**Neither endpoint exists.** Grepping the whole backend for `forgot`, `reset-password`
or `new_password` returns nothing. Both pages show "Failed to send reset email" against
a 404.

A user who forgets their password today has no recovery path at all short of an admin
editing the database.

- [`frontend/src/pages/auth/PasswordReset.tsx:23`](../../../frontend/src/pages/auth/PasswordReset.tsx:23), [`:121`](../../../frontend/src/pages/auth/PasswordReset.tsx:121)
- [`frontend/src/router/index.tsx:121`](../../../frontend/src/router/index.tsx:121)–122 — the routes
- [`auth/router.py`](../../../backend/src/auth/router.py) — no matching routes

**Fix:** implement both endpoints. The verification-email machinery in
[`common/email.py`](../../../backend/src/common/email.py) already has the token minting
and send path to copy.

**Done (2026-09-30).** That machinery had never run — see AU-08 — so both flows were built in
`auth/account_emails.py` and the auth router:

- `POST /auth/forgot-password {email}` → 202, the same answer for any address (no account
  enumeration); an active account is emailed a link to `/reset-password?token=…`. At most
  five account emails an hour per address.
- The reset token is a JWT with `type: "password_reset"`, 30 minutes, and `pwh` — a
  fingerprint of the password hash it was issued against — so it works **once**: the new
  password changes the hash.
- `POST /auth/reset-password {token, new_password}` checks the policy (AU-07), sets the
  password, marks the address verified (the user proved they read its mail), ends every
  session through `revoke_all_sessions` (AU-05), and clears the sign-in throttle.
- Emails are sent after the response (FastAPI background tasks) through the `smtp-system`
  integration, with links built from the new `FRONTEND_URL` setting (the old code read an
  env var defaulting to port 5173; the SPA runs on 3000). The endpoints themselves are the
  retry. `EMAIL_LINKS_IN_LOG` (local development only) writes a link that could not be
  emailed to the log.

**Evidence:** `tests/integration/test_account_email_flows.py` (auth router against the real
Postgres, SMTP captured, Redis faked), 7 cases, among them the reset end to end — same 202
for known and unknown addresses, the old password refused and the new one accepted, the
earlier session's refresh token refused, the link refused the second time — and a
verification token refused as a reset token. Live, in the browser against the local stack (2026-10-01): registering on `/register`
landed on `/verify-email` ("we've sent a verification link"); signing in before verifying
showed *Please verify your email address before signing in* with a "Send the verification
link again" link; the link (read from the API log with `EMAIL_LINKS_IN_LOG`) verified the
address; sign-in then worked and landed on onboarding; the sidebar's Logout called
`POST /auth/logout` (204) and cleared storage; `/forgot-password` → the logged reset link →
a new password on `/reset-password` succeeded, after which the old password got 401, the new
one 200, and the same link again 400.

---

### AU-07 — There is no password policy on the server

**✅ Verified · High** · **Status: fixed (2026-09-30)** — with [AU-I6](#au-i6--rate-limit-login-by-email-not-only-by-ip).

`UserCreate.password` is a bare `str`. No minimum length, no complexity rule, no breach
check. A one-character password is accepted by the API.

The only policy in the codebase is client-side, in the reset page that cannot work:

```tsx
if (password.length < 12) { setError('Password must be at least 12 characters long'); return; }
```

That runs in the browser and is bypassed by any direct API call.

There is also **no rate limit on `/auth/login`**. The gateway's blanket
`200/minute` per IP is the only thing between an attacker and unlimited password
guessing.

- [`auth/schemas.py`](../../../backend/src/auth/schemas.py) — `UserCreate`
- [`frontend/src/pages/auth/PasswordReset.tsx:108`](../../../frontend/src/pages/auth/PasswordReset.tsx:108)

**Fix:** a Pydantic validator with a length minimum, plus a per-email login rate limit.

**Done (2026-09-30).**

- `service.check_password_policy`: 12–128 characters and not the account's email, where a
  password is chosen — register, admin create, reset. Not a Pydantic validator: its 422
  `detail` would be a list, and every page renders `detail` as text; this one is a string.
  Existing passwords are not re-checked at login. The create-user modal says "min 12".
- `auth/throttle.py`: ten wrong passwords for one account in 15 minutes and sign-in for that
  account answers 429 with `Retry-After` until the window ends, the right password included;
  unknown emails count the same, so the limit reveals nothing; a correct password clears the
  count. Keyed by a SHA-256 of the email in Redis; if Redis is down the check is skipped and
  logged rather than locking everyone out.

**Evidence:** `tests/unit/test_login_throttle_and_policy.py` (10 cases: lengths, email as
password, lock at the tenth failure in any letter case, clear, no email in the key, Redis
down fails open) and, through the real router, a weak password's readable 422 and a 429
after ten wrong passwords in `tests/integration/test_account_email_flows.py`.

---

### AU-08 — `is_verified` gates nothing

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — product decision: an unverified
account cannot sign in.

Self-registered users get `is_verified = False` **and a working access token in the same
response**. Nothing anywhere checks the flag. The verification email exists and the
verify endpoint works, but completing it changes no behaviour.

Worse, the email links to `/verify-email`, and that route **does not exist in the
frontend router** — it falls through the catch-all to `/dashboard`. So the user clicks
the link, lands on the dashboard, and the token is never presented to the endpoint.

- [`auth/service.py`](../../../backend/src/auth/service.py) — `create_user`
- [`common/email.py:183`](../../../backend/src/common/email.py:183) — the link builder
- [`frontend/src/router/index.tsx`](../../../frontend/src/router/index.tsx) — no `/verify-email` route

**Worse than recorded:** no verification email was ever sent. `send_verification_email` had
no caller; a comment in `create_user` said the background worker sent it, and no job did.

**Done (2026-09-30).**

- `POST /auth/register` returns `201 {email, message}` and **no tokens**, and emails a
  verification link (24 hours). `POST /auth/resend-verification {email}` sends it again —
  202 for any address, at most five an hour.
- An unverified account is refused everywhere: the right password is a 403 *Please verify
  your email address before signing in*; its refresh and access tokens are 401.
- Admin-created and OAuth users are verified at creation, as before. A password reset
  verifies the address too.
- Revision `au08_verify_existing_users` marks every existing account verified: none had
  been sent a link, and blocking them would have locked out every self-registered user.
- Frontend: registration goes to a new `/verify-email` page ("we've sent a link", with a
  resend form); the email's link opens the same page, which verifies and offers sign-in; the
  login page shows "Send the verification link again" on the 403.

**Evidence:** `tests/integration/test_account_email_flows.py` — registration sends one
`/verify-email` link and returns no token; sign-in is 403 until the link is opened, then 200;
resend answers alike for unknown and unverified addresses and emails only the latter;
`tests/unit/test_auth_token_checks.py` — an unverified user's access token is 401. Live: see
[AU-06](#au-06--password-reset-works-in-the-browser-and-does-not-exist-in-the-backend).

**Found while verifying:** the single-flight refresh added for AU-09 (`6127c33`) sent the
browser to `/login` on any 401 when no refresh token was stored. The login page itself makes
a call that 401s when signed out (`GET /ai/admin/feature_flags/me`), so the login page
reloaded forever. `api.client.ts` now passes the 401 on when there is no refresh token to try,
as before.

---

### AU-09 — Refresh token reuse is detected and ignored

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — a rotated refresh token presented
again ends every session of its user (`revoke_all_sessions`: all refresh tokens revoked,
`token_version` bumped, so the attacker's rotated token and every access token die). Logout
deletes its token's row instead of flagging it, so a token the user logged out with never
trips this. Two concurrent refreshes from one browser would present the same token, so the
frontend refreshes through one shared request. Evidence under
[AU-05](#au-05--access-tokens-cannot-be-revoked).

Presenting a revoked refresh token is the classic signal that a token family has been
stolen. The code spots it and comments on the correct response without doing it:

```python
if refresh_token.revoked:
    # Security alert: Attempt to use revoked token
    # In a real system, we might revoke all tokens for this user
    raise HTTPException(status_code=401, detail="Token revoked")
```

Only that one request is rejected. The attacker's freshly rotated token stays live for
the rest of its 7 days.

- [`auth/service.py:186`](../../../backend/src/auth/service.py:186)

**Fix:** revoke every token for that user. Pairs directly with the `token_version` idea
in [AU-05](#au-05--access-tokens-cannot-be-revoked).

---

### AU-10 — Refresh tokens are stored in plaintext

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-30)**

`refresh_tokens.token` holds the 32-byte secret as-is, `unique=True, index=True`. Any
read access to that table — a backup, a log, a SQL injection elsewhere — is a set of
working 7-day credentials for every active user.

- [`auth/models.py`](../../../backend/src/auth/models.py) — `RefreshToken`

**Fix:** store a SHA-256 hash and look up by hash. The token is already high-entropy, so
no salt or slow hash is needed.

**Done (2026-09-30).** The column is now `refresh_tokens.token_hash` (hex SHA-256, unique);
`service.hash_refresh_token` is the one hashing function, and create, verify and rotate all
go through it. Revision `au10_refresh_token_hash` hashes existing rows in place with
Postgres's `sha256()`, so nobody is signed out, then drops the plaintext column.

**Evidence:** `tests/integration/test_refresh_token_hashing.py` (real Postgres, rolled
back) — the row holds the token's SHA-256 and the table has no `token` column; the token
verifies and its **stored hash presented as a token is refused**; rotation finds tokens by
hash. On the local database: a live refresh token read before the migration still verified
after it, and all 33 rows carry a 64-character hash.

---

### AU-11 — The gateway's JWT secret does not match the API's

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — `JWT_SECRET` and the middleware that
decoded with it are deleted with the gateway; only `SECRET_KEY` exists.

The backend signs with `SECRET_KEY`. The gateway decodes with `JWT_SECRET`. They are
different settings, and in the checked-in `.env` they hold different values.

`GatewayAuthMiddleware._decode_jwt` therefore fails silently on every request,
`request.state.tenant.company_id` is always `None`, and gateway-level tenant metrics are
permanently empty. Nothing errors; the data is just blank.

- `gateway/gateway_config.py:35`
- `gateway/auth_middleware.py`

**Fix:** have the gateway read `SECRET_KEY` from the shared settings object. See also
[SA-20](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-20--both-shared-secrets-ship-as-change-me-in-production).

### AU-24 — The credential-encryption key has a public default

**✅ Verified · High** · **Status: open** — found 2026-10-01.

`ENCRYPTION_MASTER_KEY` defaults to `"your-default-dev-key-must-be-32-bytes"`
([config.py](../../../backend/src/common/config.py)). It encrypts every stored third-party
credential: integration API keys, SMTP/IMAP passwords, social access and refresh tokens. A
deployment whose environment omits it starts normally and encrypts everything with a key
that is in this repository. Nothing warns. And `security.py` does not derive the AES key:
it truncates the string to 32 bytes or pads it with NULs, so a short passphrase becomes a
weak key.

**Fix:** refuse to start when the key is unset or equals the default (`SECRET_KEY` already
has no default), and derive the AES key with HKDF. Both change which key existing
ciphertexts were made with. Any environment that ran on the default needs its stored
credentials re-encrypted, which is why this is not fixed in passing. Decide the rotation
first.

### AU-25 — Social-connection client secrets are stored in plaintext

**✅ Verified · Medium** · **Status: open** — found 2026-10-01.

`POST /api/social-connections` encrypts the access and refresh tokens, but its
`oauth_metadata` field is documented as "client_id, client_secret, etc." and stored
as-is in `social_connections.oauth_metadata`. Token refresh reads `client_secret` from
there ([social_connection_service.py](../../../backend/src/ai/social_connection_service.py)).
The app's OAuth client secret therefore sits next to tokens that are encrypted, in a column
that is not. The API does not return it, but anyone who can read the table has it.

**Fix:** store `client_secret` with `encrypt_api_key`, or better, keep platform client
credentials in the integration registry (already encrypted), not per connection.

---

## 4. T2 — Missing pieces

### AU-12 — There is no logout endpoint

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — `POST /auth/logout
{refresh_token, all_sessions?}` answers 204: it deletes the presented refresh token's row
and clears the refresh cookie; `all_sessions: true` also ends every other session (refresh
and access tokens). An unknown or already-ended token is a no-op. The frontend's sign-out
calls it before clearing its storage. Evidence under
[AU-05](#au-05--access-tokens-cannot-be-revoked).

Logout is `localStorage.removeItem(...)` in the browser. The refresh-token row stays
`revoked = false` and valid for up to 7 days. Signing out on a shared computer does not
end the session.

**Fix:** `POST /auth/logout` that revokes the presented refresh token. Two lines with
the service that already exists.

---

### AU-13 — The internal token is compared with `!=`

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-30)** — `require_internal` compares with
`hmac.compare_digest`.

`X-Internal-Token` is checked with a plain `token != settings.INTERNAL_TOKEN`, not
`hmac.compare_digest`. That is a timing side channel on a shared secret that guards an
endpoint capable of creating executions.

Combined with the default value still being `change-me-in-production` in the checked-in
`.env`, the timing channel is currently the smaller problem.

- `gateway/auth_middleware.py`

---

### AU-14 — The `type` claim is not checked on login tokens

**✅ Verified · Medium** · **Status: fixed (2026-09-30)**

`create_access_token` mints both login tokens and email-verification tokens. The only
difference is a `type` claim, and `_authenticate_user` **never inspects it**.

The verification path checks `type == "email_verification"` correctly, so a login token
cannot be replayed there. The reverse is open: any code that mints a token with
`type: email_verification` is minting something `get_current_user` will accept as a
full login token.

- [`common/security.py`](../../../backend/src/common/security.py) — `create_access_token`
- [`auth/service.py:277`](../../../backend/src/auth/service.py:277) — `verify_email_token`

**Fix:** require `type == "access"` in `_authenticate_user` and stamp it at mint time.

**Done (2026-09-30).** `service.issue_access_token(user)` is the one minting helper for
login tokens (register, login, `/token`, refresh, OAuth — five hand-written dicts before) and
stamps `type: "access"`; `_authenticate_user` refuses any other `type`, and a token with
none. The two type strings are constants in `common/security.py`. Access tokens issued
before the change have no `type`, so each signed-in browser refreshes once (its refresh
token is unaffected). The `print("Auth Debug: …")` lines in `_authenticate_user`, which
wrote user emails to stdout, are `logger.debug` calls without the email.

**Evidence:** `tests/unit/test_auth_token_checks.py` — a login token authenticates; an
`email_verification`, a `password_reset` and an untyped token are all 401. 8 of its 9
cases fail on the old code. Live: a verification-type token for a real user got 401 from
`/auth/me`.

---

### AU-15 — Partner admins cannot manage the tenants they create

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — with
[AU-03](#au-03--any-user-can-suspend-their-own-company). Product decision: a partner admin
may rename, suspend and reactivate its own tenants. The Tenants tab's status toggle in
Platform Management, which returned 403 for a partner admin, now works. The `/partner/*`
router stays read-only; `PATCH /companies/{id}` is the write path.

The same missing role logic as [AU-03](#au-03--any-user-can-suspend-their-own-company),
seen from the other side. `update_company` allows `app_admin` or "your own company"
only. A `partner_admin` can create a tenant and then cannot rename it, suspend it, or
change anything about it.

The whole `/partner/*` router is read-only as a result. Partner self-service is a stated
product goal that the guard blocks.

- [`auth/company_router.py:110`](../../../backend/src/auth/company_router.py:110)

---

### AU-16 — The refresh cookie nobody reads

**✅ Verified · Low** · **Status: won't fix (2026-09-30)** — the entry asks for the cookie to be
kept, and it is: it is the base for [AU-I7](#au-i7--move-refresh-tokens-into-the-cookie-that-already-exists).
`/auth/register` no longer sets it (registration returns no tokens since AU-08), and
`/auth/logout` clears it.

`/auth/register`, `/auth/login`, `/auth/refresh` and `/auth/oauth/{provider}` all set an
`HttpOnly; Secure; SameSite=lax` cookie named `refresh_token`. Nothing reads it. The
refresh endpoint takes the token from the JSON body and the frontend reads it from
`localStorage`.

Harmless today, and it is exactly the right foundation for moving refresh tokens out of
`localStorage` — which is the fix for a real problem. Listed so the cookie is not
deleted by mistake.

---

## 5. T3 — Inconsistency and dead weight

### AU-17 — Two functions named `_require_admin` mean different things

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — with AU-18, AU-21 and
[AU-I2](#au-i2--one-role-enum-one-guard).

| Helper | File | Who counts as admin |
|---|---|---|
| `_require_admin` | [`ai/api/admin.py:91`](../../../backend/src/ai/api/admin.py:91) | `app_admin`, `partner_admin`, **`tenant_admin`** |
| `_require_admin` | [`billing/cron_router.py:16`](../../../backend/src/billing/cron_router.py:16) | `app_admin` only |
| `_require_app_admin` | [`config/router.py:156`](../../../backend/src/config/router.py:156) | `app_admin` only |
| `_require_roles(user, *roles)` | [`ai/reports_router.py:24`](../../../backend/src/ai/reports_router.py:24) | varies per endpoint |

Four guard styles, two of them sharing a name and disagreeing. Reading a route's
decorator does not tell you who can call it — you have to follow the import.

**Fix:** one guard mechanism, `RoleChecker`, everywhere. Delete the hand-rolled ones.

**Done (2026-09-30).** All thirty call sites of the four helpers are `RoleChecker`
dependencies in their route signatures, with the same roles: `ai/api/admin.py` (20 routes,
`RoleChecker(ADMIN_ROLES)` — `ADMIN_ROLES` now named once in `auth/roles.py`), the two cron
routes and the three task-default routes (`app_admin`), and five analytics reports (their
listed roles). The helpers, and `admin.py`'s `_is_admin`, are deleted; every guarded 403 now
says *Operation not permitted*.

**Evidence:** `tests/unit/test_role_guards.py`, 17 cases — `app_admin` passes a guard that does
not list it; other roles are refused; a misspelt role fails at construction; no
`_require_admin` / `_require_app_admin` / `_require_roles` definition remains under `src/`;
walking the real app's routes, every one of the 40+ guards admits `app_admin` and holds only
`Role` members; nine routes (among them the converted ones) keep exactly their roles. Fails on
the old code. Live: `GET /ai/admin/admin/kpi/runs` 200 for `app_admin` and `tenant_admin`, 403
for `tenant_user`; the cron, task-default and data-growth routes 403 for both tenant roles and
200 for `app_admin`.

---

### AU-18 — There is no hierarchy, so `app_admin` can be locked out by omission

**✅ Verified · Medium** · **Status: fixed (2026-09-30)** — `RoleChecker` always admits
`app_admin`. Every existing list already named it, so no route's behaviour changed; the trap
is gone for the next one. The route-table test fails if any guard would refuse it. Evidence
under [AU-17](#au-17--two-functions-named-_require_admin-mean-different-things).

`RoleChecker` is a flat set-membership test. `app_admin` is **not** implicitly allowed
anywhere — it only gets through a guard whose list literally contains `"app_admin"`.

Every guard in the codebase spells it out by hand today, so it works. One forgotten
entry silently locks the platform administrator out of an endpoint, and the failure looks
like a bug in the feature rather than in the guard.

- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py) — `RoleChecker`

---

### AU-19 — `app_user` is a role with almost no meaning

**✅ Verified · Low** · **Status: won't fix (2026-09-30)** — product decision: keep `app_user`
as it behaves — an APP-company user with the platform ops reports and no cross-tenant access
— and document it. `04-auth-rbac-tenancy.md` §7.1 and §7.6 now describe it that way instead of
"platform ops / support, read-mostly". Cross-tenant read access for support staff would be a
new feature.

`app_user` appears in exactly three backend lines, all in `reports_router.py`. It is in
no `RoleChecker` list, so it is rejected from `/companies/partners`,
`/companies/tenants`, `POST /companies`, `POST /users` and the whole `/partner/*` tree.

`GET /companies` falls into the `else` branch and returns "own company only" — the same
as a tenant user. In practice `app_user` is a tenant user with two extra report pages,
despite being documented as a platform operations role.

---

### AU-20 — Five independent copies of "own company plus children"

**📄 Doc-reported · Medium** · **Status: fixed (2026-09-30)** — with [AU-I5](#au-i5--one-visible_company_idsuser-helper)
and [PO-I6](01-PRODUCT-OVERVIEW-DEFECTS.md#po-i6--cache-the-partner-entity-fan-out).

The cascade logic appears separately in `user_router`, `company_router`, `ai/router`,
`ai/service` and `phone_number_router`. They already disagree about what `partner_user`
can see.

Five copies means five places to fix when the rule changes, and five places for a
tenant-boundary bug to hide.

**Fix:** one `visible_company_ids(user)` helper. Every scoped query takes its result.

**Done (2026-09-30).** `auth/visibility.py`: `company_scope(db, company_id, role)` and
`visible_company_ids(db, user)` return the companies a user can see — `None` for `app_admin`
(every company), own + tenants for `partner_admin` / `partner_user`, own for everyone else —
and `in_scope(scope, company_id)`. The five copies use it: `list_users`, `list_companies`,
`create_entity` (a `target_company_id` must be in scope), `list_entities` and
`AIService.get_entity`, and phone-number agent assignment for partners. `get_entities` now
takes a set of company ids, so a partner's entity list is **one** query with `company_id IN
(...)` instead of one per tenant (PO-I6).

The "disagreement about `partner_user`" was not one: every copy let partners see their
tenants; `list_users` refuses `partner_user` because listing users is an admin action. That
stays a role check in the route. Small change: a tenant passing its **own** id as
`target_company_id` to `POST /ai/entities` used to be refused; it is in scope now.

**Evidence:** `tests/integration/test_company_visibility.py` (real Postgres, rolled back; a
partner, its tenant and an unrelated tenant), 9 cases — the rule for four roles; a partner's
entity list returns its own and its tenant's entities, not the other tenant's, **in one entity
query**; a partner reads its tenant's entity and gets 404 for the other's; a partner admin lists
its and its tenant's users only; a partner user sees both companies but gets 403 listing users;
entity creation is allowed for the tenant and refused for the other company. 5 fail on the old
code.

---

### AU-21 — The role strings exist as a comment, not an enum

**✅ Verified · Low** · **Status: fixed (2026-09-30)** — `auth/roles.py` has the `Role` enum
(since AU-01, which typed the request schemas with it, so an unknown role in a request is a
422); since AU-17 `RoleChecker` converts its list to `Role` members, so a typo like
`"tenant-admin"` raises when the route module is imported. Evidence under
[AU-17](#au-17--two-functions-named-_require_admin-mean-different-things). `users.role` still
has no database constraint.

The six roles are declared as a comment on `users.role` in the backend and as a real
TypeScript enum on the frontend. There is no Python enum. Every guard list is a list of
string literals, so a typo — `"tenant-admin"` for `"tenant_admin"` — produces a guard
that silently allows nobody.

This is also what makes [AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin)
possible: with no enum there is nothing to validate an incoming role string against.

- [`auth/models.py:35`](../../../backend/src/auth/models.py:35)

---

### AU-22 — Suspension is checked twice, in two different ways

**✅ Verified · Low** · **Status: fixed (2026-09-30)** — the middleware is deleted (SA-18); the
dependency's check is the only one.

`CompanySuspensionMiddleware` reads `company_id` from the **JWT claim** and runs its own
`SELECT` on its own session. `_authenticate_user` reads it from the **eager-loaded
`user.company`**.

If a user is moved between companies, the middleware checks the old company until the
token expires while the dependency checks the new one. The middleware also swallows
every exception and continues, so a database blip silently disables it.

The dependency-level check is correct and free. The middleware's own docstring says it
exists only because "the requirement specifically asked for Middleware".

- `common/middleware.py`
- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py)

**Fix:** delete the middleware. It costs a DB round trip per request and adds nothing
the dependency does not already do better.

---

## 6. Improvements

### AU-I1 — Make tenant scoping structural instead of remembered

**Effect: the largest single change available in this register.** Today isolation is
`WHERE company_id = ...` typed by hand in every service method across ~40 tables. There
is no row-level security, no query filter, and no test that would catch a missing one.

Two options, in increasing order of strength:

1. A `TenantSession` wrapper that requires a `company_id` and applies the filter for
   you. Cheap, and it makes the forgotten filter impossible **in code that uses it**.
2. Postgres row-level security with `SET LOCAL app.company_id`. Correct even for raw SQL
   — which matters, because the pgvector search paths are all raw SQL today.

Whichever is chosen, `app_admin` still needs an explicit escape hatch. That escape hatch
is exactly why [AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin) is
critical rather than merely bad.

### AU-I2 — One role enum, one guard

**Status: done (2026-09-30)** — AU-17, AU-18, AU-21.

**Effect: medium.** A Python `Role` enum, and `RoleChecker` as the only guard. This
closes [AU-17](#au-17--two-functions-named-_require_admin-mean-different-things),
[AU-21](#au-21--the-role-strings-exist-as-a-comment-not-an-enum) and half of
[AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin) in one change, and it
makes an audit of "who can call what" a grep instead of a reading exercise.

### AU-I3 — Add `token_version` to `users`

**Status: done (2026-09-30)** — AU-05, AU-09 and AU-12. (AU-04's lockout did not need it:
`is_active` is read on every request.)

**Effect: large for security, small in code.** One integer column, one claim, one
comparison in `_authenticate_user`. It gives the platform:

- working logout ([AU-12](#au-12--there-is-no-logout-endpoint)),
- token revocation ([AU-05](#au-05--access-tokens-cannot-be-revoked)),
- a real response to refresh-token reuse ([AU-09](#au-09--refresh-token-reuse-is-detected-and-ignored)),
- and instant lockout when a user is deactivated ([AU-04](#au-04--is_active-is-never-checked-so-deactivating-a-user-does-nothing)).

Four defects, one column.

### AU-I4 — Delete `CompanySuspensionMiddleware`

**Status: done (2026-09-30)** — SA-18.

**Effect: medium, and it is a deletion.** See
[AU-22](#au-22--suspension-is-checked-twice-in-two-different-ways). It costs one extra
database round trip on every authenticated request and is strictly weaker than the check
that already runs in the dependency.

### AU-I5 — One `visible_company_ids(user)` helper

**Status: done (2026-09-30)** — AU-20.

**Effect: medium.** Replaces the five copies in
[AU-20](#au-20--five-independent-copies-of-own-company-plus-children). Every scoped
query then takes a list, and the partner fan-out becomes one `IN (...)` instead of a
query per child tenant — which is also
[PO-I6](01-PRODUCT-OVERVIEW-DEFECTS.md#po-i6--cache-the-partner-entity-fan-out).

### AU-I6 — Rate-limit login by email, not only by IP

**Status: done (2026-09-30)** — with AU-07: a fixed 15-minute window of ten failures per
account, not exponential backoff; `governance/rate_limiter.py` was not used (it is a
sliding-window request counter, and this counts failures).

**Effect: medium.** The gateway's `200/minute` per remote address does nothing against a
distributed attempt and hurts legitimate users behind one NAT. A per-email counter with
exponential backoff is the right shape, and Redis is already there. The platform even
has a working sliding-window rate limiter in
[`ai/governance/rate_limiter.py`](../../../backend/src/ai/governance/rate_limiter.py)
with zero call sites.

### AU-I7 — Move refresh tokens into the cookie that already exists

**Effect: medium.** The `HttpOnly; Secure; SameSite=lax` cookie is already being set on
four endpoints ([AU-16](#au-16--the-refresh-cookie-nobody-reads)). Reading it instead of
`localStorage` takes the long-lived credential out of reach of any XSS on the page. The
hard half is already done.

### AU-I8 — Add an audit log for permission changes

**Effect: medium.** There is no record of who changed a role, who suspended a company, or
who deleted an email connection. With [AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin)
open, there is also no way to tell after the fact whether it was used.

Role change, company status change and credential deletion are three events. Append-only,
never deleted.

### AU-I9 — Add a permission test suite generated from the route table

**Effect: large for confidence.** `04-auth-rbac-tenancy.md` already contains a complete
permission matrix derived from the guard code. Turning that table into a parameterised
test — for each route, for each of the six roles, assert allowed or 403 — would have
caught [AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin),
[AU-03](#au-03--any-user-can-suspend-their-own-company) and
[AU-19](#au-19--app_user-is-a-role-with-almost-no-meaning) automatically.

### AU-I10 — Reduce the per-request database work

**Effect: medium.** Every authenticated request currently does: one middleware `SELECT`
on its own session, plus one `SELECT ... selectinload(User.company)` in the dependency.
Deleting the middleware ([AU-I4](#au-i4--delete-companysuspensionmiddleware)) removes
one. Caching the user-plus-company lookup in Redis for 30 seconds removes most of the
other. Role changes would then take up to 30 seconds to apply, which is a fair trade and
should be stated in the docs.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | AU-01, AU-03 | Two privilege-escalation holes, both a few lines. Nothing else on this list matters while they are open |
| **2** | AU-02 | Add auth to the email router. Copy `social_router.py` |
| **3** | AU-04, AU-14 | Two one-line checks in `_authenticate_user` |
| **4** | AU-I3 — `token_version` | One column that closes AU-05, AU-09, AU-12 and completes AU-04 |
| **5** | AU-06, AU-07 | Password reset and a server-side password policy. Needed before real users exist |
| **6** | AU-I2, AU-I5, AU-I4 | Consolidate the guards, the scoping helper, and delete the middleware |
| **7** | AU-I1 | The structural tenancy boundary. The largest piece of work here, and the one that stops this class of defect recurring |
| **8** | AU-I9 | The permission test suite, so step 7 stays correct |

---

## Where to go next

- [04 — Auth, RBAC & tenancy](../04-auth-rbac-tenancy.md) — the source document,
  including the full permission matrix.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — AU-02 is D-04.
- [03 — Data model](03-DATA-MODEL-DEFECTS.md) — DM-09 and DM-16 are the schema side of
  AU-I1.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-20 for the shared
  secrets behind AU-11 and AU-13.
- [17 — API reference](17-API-REFERENCE-DEFECTS.md) — for the full list of routes and
  their guards.
