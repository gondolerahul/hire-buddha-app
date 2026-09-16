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
| [T0](#2-t0--privilege-escalation-and-open-doors) | Privilege escalation and open doors | 5 | **Now** — before any real customer data exists |
| [T1](#3-t1--controls-that-are-not-enforced) | Controls that are not enforced | 6 | Before relying on the control |
| [T2](#4-t2--missing-pieces) | Missing pieces | 5 | Before launch |
| [T3](#5-t3--inconsistency-and-dead-weight) | Inconsistency and dead weight | 6 | When the area is next touched |

**Total: 22 defects, 10 improvements.**

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

**✅ Verified · Critical**

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

---

### AU-02 — The email connection API has no authentication at all

**✅ Verified · Critical**

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

---

### AU-03 — Any user can suspend their own company

**✅ Verified · Critical**

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

---

### AU-04 — `is_active` is never checked, so deactivating a user does nothing

**✅ Verified · High**

`users.is_active` exists, defaults to `True`, is editable through `UserUpdate`, and is
shown in the partner dashboard. Neither `authenticate_user` nor `_authenticate_user`
ever reads it.

An admin who deactivates a user in the UI sees the flag flip and reasonably believes
that person is locked out. They can still log in and still use every API.

- [`auth/service.py`](../../../backend/src/auth/service.py) — `authenticate_user`
- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py) — `_authenticate_user`

**Fix:** reject inactive users in `_authenticate_user`, next to the existing suspension
check. One line.

---

### AU-05 — Access tokens cannot be revoked

**✅ Verified · High**

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

---

## 3. T1 — Controls that are not enforced

### AU-06 — Password reset works in the browser and does not exist in the backend

**✅ Verified · High**

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

---

### AU-07 — There is no password policy on the server

**✅ Verified · High**

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

---

### AU-08 — `is_verified` gates nothing

**✅ Verified · Medium**

Self-registered users get `is_verified = False` **and a working access token in the same
response**. Nothing anywhere checks the flag. The verification email exists and the
verify endpoint works, but completing it changes no behaviour.

Worse, the email links to `/verify-email`, and that route **does not exist in the
frontend router** — it falls through the catch-all to `/dashboard`. So the user clicks
the link, lands on the dashboard, and the token is never presented to the endpoint.

- [`auth/service.py`](../../../backend/src/auth/service.py) — `create_user`
- [`common/email.py:183`](../../../backend/src/common/email.py:183) — the link builder
- [`frontend/src/router/index.tsx`](../../../frontend/src/router/index.tsx) — no `/verify-email` route

---

### AU-09 — Refresh token reuse is detected and ignored

**✅ Verified · Medium**

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

**📄 Doc-reported · Medium**

`refresh_tokens.token` holds the 32-byte secret as-is, `unique=True, index=True`. Any
read access to that table — a backup, a log, a SQL injection elsewhere — is a set of
working 7-day credentials for every active user.

- [`auth/models.py`](../../../backend/src/auth/models.py) — `RefreshToken`

**Fix:** store a SHA-256 hash and look up by hash. The token is already high-entropy, so
no salt or slow hash is needed.

---

### AU-11 — The gateway's JWT secret does not match the API's

**✅ Verified · Medium**

The backend signs with `SECRET_KEY`. The gateway decodes with `JWT_SECRET`. They are
different settings, and in the checked-in `.env` they hold different values.

`GatewayAuthMiddleware._decode_jwt` therefore fails silently on every request,
`request.state.tenant.company_id` is always `None`, and gateway-level tenant metrics are
permanently empty. Nothing errors; the data is just blank.

- [`gateway/gateway_config.py:35`](../../../backend/src/gateway/gateway_config.py:35)
- [`gateway/auth_middleware.py`](../../../backend/src/gateway/auth_middleware.py)

**Fix:** have the gateway read `SECRET_KEY` from the shared settings object. See also
[SA-20](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-20--both-shared-secrets-ship-as-change-me-in-production).

---

## 4. T2 — Missing pieces

### AU-12 — There is no logout endpoint

**✅ Verified · Medium**

Logout is `localStorage.removeItem(...)` in the browser. The refresh-token row stays
`revoked = false` and valid for up to 7 days. Signing out on a shared computer does not
end the session.

**Fix:** `POST /auth/logout` that revokes the presented refresh token. Two lines with
the service that already exists.

---

### AU-13 — The internal token is compared with `!=`

**📄 Doc-reported · Medium**

`X-Internal-Token` is checked with a plain `token != settings.INTERNAL_TOKEN`, not
`hmac.compare_digest`. That is a timing side channel on a shared secret that guards an
endpoint capable of creating executions.

Combined with the default value still being `change-me-in-production` in the checked-in
`.env`, the timing channel is currently the smaller problem.

- [`gateway/auth_middleware.py`](../../../backend/src/gateway/auth_middleware.py)

---

### AU-14 — The `type` claim is not checked on login tokens

**✅ Verified · Medium**

`create_access_token` mints both login tokens and email-verification tokens. The only
difference is a `type` claim, and `_authenticate_user` **never inspects it**.

The verification path checks `type == "email_verification"` correctly, so a login token
cannot be replayed there. The reverse is open: any code that mints a token with
`type: email_verification` is minting something `get_current_user` will accept as a
full login token.

- [`common/security.py`](../../../backend/src/common/security.py) — `create_access_token`
- [`auth/service.py:277`](../../../backend/src/auth/service.py:277) — `verify_email_token`

**Fix:** require `type == "access"` in `_authenticate_user` and stamp it at mint time.

---

### AU-15 — Partner admins cannot manage the tenants they create

**✅ Verified · Medium**

The same missing role logic as [AU-03](#au-03--any-user-can-suspend-their-own-company),
seen from the other side. `update_company` allows `app_admin` or "your own company"
only. A `partner_admin` can create a tenant and then cannot rename it, suspend it, or
change anything about it.

The whole `/partner/*` router is read-only as a result. Partner self-service is a stated
product goal that the guard blocks.

- [`auth/company_router.py:110`](../../../backend/src/auth/company_router.py:110)

---

### AU-16 — The refresh cookie nobody reads

**✅ Verified · Low**

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

**✅ Verified · Medium**

| Helper | File | Who counts as admin |
|---|---|---|
| `_require_admin` | [`ai/api/admin.py:91`](../../../backend/src/ai/api/admin.py:91) | `app_admin`, `partner_admin`, **`tenant_admin`** |
| `_require_admin` | [`billing/cron_router.py:16`](../../../backend/src/billing/cron_router.py:16) | `app_admin` only |
| `_require_app_admin` | [`config/router.py:156`](../../../backend/src/config/router.py:156) | `app_admin` only |
| `_require_roles(user, *roles)` | [`ai/reports_router.py:24`](../../../backend/src/ai/reports_router.py:24) | varies per endpoint |

Four guard styles, two of them sharing a name and disagreeing. Reading a route's
decorator does not tell you who can call it — you have to follow the import.

**Fix:** one guard mechanism, `RoleChecker`, everywhere. Delete the hand-rolled ones.

---

### AU-18 — There is no hierarchy, so `app_admin` can be locked out by omission

**✅ Verified · Medium**

`RoleChecker` is a flat set-membership test. `app_admin` is **not** implicitly allowed
anywhere — it only gets through a guard whose list literally contains `"app_admin"`.

Every guard in the codebase spells it out by hand today, so it works. One forgotten
entry silently locks the platform administrator out of an endpoint, and the failure looks
like a bug in the feature rather than in the guard.

- [`auth/dependencies.py`](../../../backend/src/auth/dependencies.py) — `RoleChecker`

---

### AU-19 — `app_user` is a role with almost no meaning

**✅ Verified · Low**

`app_user` appears in exactly three backend lines, all in `reports_router.py`. It is in
no `RoleChecker` list, so it is rejected from `/companies/partners`,
`/companies/tenants`, `POST /companies`, `POST /users` and the whole `/partner/*` tree.

`GET /companies` falls into the `else` branch and returns "own company only" — the same
as a tenant user. In practice `app_user` is a tenant user with two extra report pages,
despite being documented as a platform operations role.

---

### AU-20 — Five independent copies of "own company plus children"

**📄 Doc-reported · Medium**

The cascade logic appears separately in `user_router`, `company_router`, `ai/router`,
`ai/service` and `phone_number_router`. They already disagree about what `partner_user`
can see.

Five copies means five places to fix when the rule changes, and five places for a
tenant-boundary bug to hide.

**Fix:** one `visible_company_ids(user)` helper. Every scoped query takes its result.

---

### AU-21 — The role strings exist as a comment, not an enum

**✅ Verified · Low**

The six roles are declared as a comment on `users.role` in the backend and as a real
TypeScript enum on the frontend. There is no Python enum. Every guard list is a list of
string literals, so a typo — `"tenant-admin"` for `"tenant_admin"` — produces a guard
that silently allows nobody.

This is also what makes [AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin)
possible: with no enum there is nothing to validate an incoming role string against.

- [`auth/models.py:35`](../../../backend/src/auth/models.py:35)

---

### AU-22 — Suspension is checked twice, in two different ways

**✅ Verified · Low**

`CompanySuspensionMiddleware` reads `company_id` from the **JWT claim** and runs its own
`SELECT` on its own session. `_authenticate_user` reads it from the **eager-loaded
`user.company`**.

If a user is moved between companies, the middleware checks the old company until the
token expires while the dependency checks the new one. The middleware also swallows
every exception and continues, so a database blip silently disables it.

The dependency-level check is correct and free. The middleware's own docstring says it
exists only because "the requirement specifically asked for Middleware".

- [`common/middleware.py`](../../../backend/src/common/middleware.py)
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

**Effect: medium.** A Python `Role` enum, and `RoleChecker` as the only guard. This
closes [AU-17](#au-17--two-functions-named-_require_admin-mean-different-things),
[AU-21](#au-21--the-role-strings-exist-as-a-comment-not-an-enum) and half of
[AU-01](#au-01--any-admin-can-promote-themselves-to-app_admin) in one change, and it
makes an audit of "who can call what" a grep instead of a reading exercise.

### AU-I3 — Add `token_version` to `users`

**Effect: large for security, small in code.** One integer column, one claim, one
comparison in `_authenticate_user`. It gives the platform:

- working logout ([AU-12](#au-12--there-is-no-logout-endpoint)),
- token revocation ([AU-05](#au-05--access-tokens-cannot-be-revoked)),
- a real response to refresh-token reuse ([AU-09](#au-09--refresh-token-reuse-is-detected-and-ignored)),
- and instant lockout when a user is deactivated ([AU-04](#au-04--is_active-is-never-checked-so-deactivating-a-user-does-nothing)).

Four defects, one column.

### AU-I4 — Delete `CompanySuspensionMiddleware`

**Effect: medium, and it is a deletion.** See
[AU-22](#au-22--suspension-is-checked-twice-in-two-different-ways). It costs one extra
database round trip on every authenticated request and is strictly weaker than the check
that already runs in the dependency.

### AU-I5 — One `visible_company_ids(user)` helper

**Effect: medium.** Replaces the five copies in
[AU-20](#au-20--five-independent-copies-of-own-company-plus-children). Every scoped
query then takes a list, and the partner fan-out becomes one `IN (...)` instead of a
query per child tenant — which is also
[PO-I6](01-PRODUCT-OVERVIEW-DEFECTS.md#po-i6--cache-the-partner-entity-fan-out).

### AU-I6 — Rate-limit login by email, not only by IP

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
