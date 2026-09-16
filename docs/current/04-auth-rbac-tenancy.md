# 04. Authentication, RBAC & Multi-Tenancy

> **What this document covers:** how a request proves who it is, what role it carries, which company it belongs to, and where the platform stops one tenant from seeing another's data.
> **Who should read it:** every backend or frontend developer touching an endpoint, a query, or a route guard.
> **Prerequisites:** [02 — System architecture](02-system-architecture.md) for the service topology, [03 — Data model](03-data-model.md) for the wider table set.

---

## Table of contents

1. [The 60-second version](#1-the-60-second-version)
2. [The identity tables](#2-the-identity-tables)
3. [Passwords: Argon2, hashing, and the reset gap](#3-passwords-argon2-hashing-and-the-reset-gap)
4. [Access tokens: minting, claims, validation](#4-access-tokens-minting-claims-validation)
5. [Refresh tokens: storage, rotation, revocation](#5-refresh-tokens-storage-rotation-revocation)
6. [The FastAPI dependency chain](#6-the-fastapi-dependency-chain)
7. [The RBAC model](#7-the-rbac-model)
8. [The company hierarchy: APP, PARTNER, TENANT](#8-the-company-hierarchy-app-partner-tenant)
9. [Tenant isolation: how queries get scoped](#9-tenant-isolation-how-queries-get-scoped)
10. [CompanySuspensionMiddleware](#10-companysuspensionmiddleware)
11. [Internal service-to-service auth](#11-internal-service-to-service-auth)
12. [OAuth: login, social connections, email connections](#12-oauth-login-social-connections-email-connections)
13. [Onboarding and the company state machine](#13-onboarding-and-the-company-state-machine)
14. [Frontend route protection and token storage](#14-frontend-route-protection-and-token-storage)
15. [Security checklist and known gaps](#15-security-checklist-and-known-gaps)

---

## 1. The 60-second version

HireBuddha is a **three-level multi-tenant platform**. Everything hangs off one table, `companies`, whose `type` column is one of `APP`, `PARTNER`, or `TENANT`, and whose `parent_id` points at the company above it. Every user belongs to exactly one company. Every business row in the database carries a `company_id`.

Authentication is deliberately simple:

- Passwords are hashed with **Argon2** via `passlib`.
- Login returns a **stateless HS256 JWT access token** (default 30-minute life) plus an **opaque random refresh token** stored as a row in `refresh_tokens`.
- The access token carries only three claims: `sub` (the email), `company_id`, and `exp`. **The role is not in the token.** Every protected request re-reads the `users` row from the database, so role and company changes take effect immediately.
- Authorisation is a flat list check: `RoleChecker(["app_admin", "partner_admin"])`. There is no inheritance — each guard must name every role it allows.
- Tenant isolation is **not** enforced by the database or by any middleware. It is enforced by hand, one query at a time, by adding `WHERE company_id = current_user.company_id`. That makes it fast, but it also means a missing filter is a silent data leak. Section 15 lists the places where the filter is actually missing today.

```mermaid
flowchart TD
    Browser["Browser - React SPA"]
    LS["localStorage - access_token and refresh_token"]
    GW["Gateway :8001 - GatewayAuthMiddleware"]
    BE["Backend :8000 - FastAPI"]
    SUSP["CompanySuspensionMiddleware"]
    DEP["get_current_user dependency"]
    ROLE["RoleChecker guard - optional"]
    HANDLER["Route handler"]
    SVC["Service layer - adds WHERE company_id"]
    DB[("PostgreSQL")]

    Browser -->|"Authorization: Bearer JWT"| GW
    LS -.->|"axios request interceptor"| Browser
    GW -->|"transparent reverse proxy"| BE
    BE --> SUSP
    SUSP -->|"not suspended"| DEP
    SUSP -->|"suspended"| Blocked403["403 Company is suspended"]
    DEP -->|"decode JWT, load User row"| DB
    DEP --> ROLE
    ROLE --> HANDLER
    HANDLER --> SVC
    SVC --> DB

    INT["Internal microservice"]
    INT -->|"X-Internal-Token"| GW
```

Read the rest of this document if you are about to add an endpoint, change a role check, or debug "why can this user see that row".

---

## 2. The identity tables

Three tables in [models.py](../../backend/src/auth/models.py) carry all identity state. There is no separate `roles`, `permissions`, or `sessions` table — role is a plain string column on `users`.

```mermaid
erDiagram
    COMPANIES ||--o{ COMPANIES : "parent_id - self reference"
    COMPANIES ||--o{ USERS : "company_id"
    USERS ||--o{ REFRESH_TOKENS : "user_id"

    COMPANIES {
        uuid id PK
        string name
        string type "APP PARTNER TENANT"
        uuid parent_id FK "nullable"
        string logo_url
        string status "active or suspended"
        string onboarding_status "pending in_progress completed"
        jsonb onboarding_metadata
        string default_daily_credits
        datetime created_at
        datetime updated_at
    }
    USERS {
        uuid id PK
        string email UK "indexed unique"
        string full_name
        string hashed_password "argon2"
        uuid company_id FK "NOT NULL"
        string role "six role strings"
        bool is_active
        bool is_verified
        string profile_picture_url
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        string token UK "opaque, indexed, plaintext"
        datetime expires_at
        bool revoked
        datetime created_at
    }
```

Things worth noticing right away:

| Observation | Why it matters |
|---|---|
| `users.company_id` is `nullable=False` | Every user always has a company. There are no "floating" users. |
| `users.role` is a free-text `String`, not an enum | Nothing at the DB level stops `role = "wizard"`. Validation lives only in [service.py:52](../../backend/src/auth/service.py:52). |
| `companies.parent_id` is a self-FK | The whole hierarchy is one adjacency-list column. Only **one** level of nesting is ever queried (`parent_id == my_company_id`); nobody walks the tree recursively. |
| `refresh_tokens.token` stores the raw token | A database read gives an attacker working refresh tokens. See section 15. |
| `users.is_active` exists but is barely enforced | Grep shows it is set and returned, but `_authenticate_user` never checks it. A deactivated user can still log in. |

---

## 3. Passwords: Argon2, hashing, and the reset gap

### 3.1 Where hashing happens

All password work funnels through two functions in [common/security.py](../../backend/src/common/security.py):

```python
# backend/src/common/security.py
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)
```

`CryptContext(schemes=["argon2"])` means passlib uses **Argon2** (the `argon2-cffi` backend) with passlib's default parameters — no custom time/memory cost is configured anywhere in the repo. `deprecated="auto"` would let passlib migrate older hashes, but since `argon2` is the only scheme, there is nothing to migrate from.

Every call site:

| Call site | Purpose |
|---|---|
| [service.py:83](../../backend/src/auth/service.py:83) `create_user_as_admin` | Admin-created user |
| [service.py:133](../../backend/src/auth/service.py:133) `create_user` | Self-registration |
| [service.py:257](../../backend/src/auth/service.py:257) `get_or_create_oauth_user` | OAuth user — hashes a throwaway `secrets.token_urlsafe(16)` |
| [service.py:162](../../backend/src/auth/service.py:162) `authenticate_user` | The only `verify_password` call |

```mermaid
flowchart LR
    A["POST /auth/register"] --> B["service.create_user"]
    B --> C["get_password_hash - argon2"]
    C --> D["users.hashed_password"]

    E["POST /auth/login"] --> F["service.authenticate_user"]
    F --> G["SELECT user WHERE email"]
    G --> H{"verify_password"}
    H -->|"no"| I["return None -> 401"]
    H -->|"yes"| J["return User"]
```

### 3.2 What is NOT validated

`UserCreate` in [schemas.py:5](../../backend/src/auth/schemas.py:5) declares `password: str` with **no constraints**. There is no minimum length, no complexity rule, no breach check, and no rate limit on `/auth/login`. A one-character password is accepted by the API.

The only password policy in the whole codebase is client-side, in [PasswordReset.tsx:108](../../frontend/src/pages/auth/PasswordReset.tsx:108):

```tsx
// frontend/src/pages/auth/PasswordReset.tsx
if (password.length < 12) {
    setError('Password must be at least 12 characters long');
    return;
}
```

That check runs in the browser and is trivially bypassed.

### 3.3 Password reset — the frontend exists, the backend does not

This is the single most surprising gap in the auth module. The frontend has a complete two-page reset flow:

- `/forgot-password` → `POST /auth/forgot-password { email }` — [PasswordReset.tsx:23](../../frontend/src/pages/auth/PasswordReset.tsx:23)
- `/reset-password?token=...` → `POST /auth/reset-password { token, new_password }` — [PasswordReset.tsx:121](../../frontend/src/pages/auth/PasswordReset.tsx:121)

Both routes are wired up in [router/index.tsx:121-122](../../frontend/src/router/index.tsx:121). **Neither endpoint exists in the backend.** Grepping the whole `backend/` tree for `forgot`, `reset-password`, or `new_password` returns zero matches. Both pages will show "Failed to send reset email" against a 404.

```mermaid
sequenceDiagram
    participant U as User
    participant FE as ForgotPasswordPage
    participant API as Backend /api/v1

    U->>FE: enters email, submits
    FE->>API: POST /auth/forgot-password
    Note over API: NO ROUTE REGISTERED
    API-->>FE: 404 Not Found
    FE-->>U: "Failed to send reset email"
```

The closest working thing is **email verification**, which is a different flow:

| Piece | Location |
|---|---|
| Verification link builder | [common/email.py:183](../../backend/src/common/email.py:183) `send_verification_email` — builds `{FRONTEND_URL}/verify-email?token=...` |
| Verify endpoint | [router.py:176](../../backend/src/auth/router.py:176) `GET /auth/verify-email?token=` |
| Token check | [service.py:277](../../backend/src/auth/service.py:277) `verify_email_token` — decodes the JWT and requires `payload["type"] == "email_verification"` |

Note that `create_access_token` is reused to mint the verification token, and the `type` claim is the only thing distinguishing it from a login token. Nothing stops a normal login token from being replayed at `/auth/verify-email` — it simply fails the `type` check, which is the correct outcome, but the reverse is worth watching: any code that mints a token with `type: email_verification` is minting something that `get_current_user` will happily accept as a login token, because `_authenticate_user` never inspects `type`.

Also note the `/verify-email` frontend route does not exist in [router/index.tsx](../../frontend/src/router/index.tsx) — the verification email links to a page that falls through to the `*` catch-all and redirects to `/dashboard`.

---

## 4. Access tokens: minting, claims, validation

### 4.1 Minting

One function does all minting — [security.py:18](../../backend/src/common/security.py:18):

```python
# backend/src/common/security.py
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
```

Every login-style call site passes exactly the same dict:

```python
# backend/src/auth/router.py — identical at lines 18, 41, 66, 89, 162
create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
```

### 4.2 The complete claim set

| Claim | Type | Source | Notes |
|---|---|---|---|
| `sub` | string | `user.email` | The **only** claim the validator reads. Not the user UUID — the email. |
| `company_id` | string | `str(user.company_id)` | Read by `CompanySuspensionMiddleware` and by `GatewayAuthMiddleware`. **Ignored** by `get_current_user`. |
| `exp` | int | `utcnow() + ACCESS_TOKEN_EXPIRE_MINUTES` | Added by `create_access_token`. Verified by `jose`. |
| `type` | string | *only* on email-verification tokens | Set by the verification-email path; checked at [service.py:286](../../backend/src/auth/service.py:286). |

There is **no** `iat`, `nbf`, `iss`, `aud`, `jti`, `role`, or `user_id` claim. That has two consequences worth internalising:

1. **Role changes take effect instantly** — because the role is fetched from the DB on every request, not read from the token. Good.
2. **Access tokens cannot be revoked** — no `jti`, no denylist. A stolen access token is valid until `exp`. See section 15.

### 4.3 Signing configuration

| Setting | Default | Where | Real `.env` value |
|---|---|---|---|
| `SECRET_KEY` | *required, no default* | [config.py:6](../../backend/src/common/config.py:6) | `dev_secret_key_change_in_production` |
| `ALGORITHM` | `HS256` | [config.py:7](../../backend/src/common/config.py:7) | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | [config.py:8](../../backend/src/common/config.py:8) | `30` |
| `JWT_SECRET` (gateway only) | `change-me-in-production` | [gateway_config.py:35](../../backend/src/gateway/gateway_config.py:35) | `change-me-in-production` |

`SECRET_KEY` is a symmetric HMAC secret — anyone who has it can mint tokens for any user.

**Trap:** the backend signs with `SECRET_KEY` but the gateway decodes with a *different* variable, `JWT_SECRET`. In the checked-in `backend/.env` these two hold different values, so `GatewayAuthMiddleware._decode_jwt` always fails silently and `request.state.tenant.company_id` is always `None` on the REST path. That is harmless today (the gateway only uses it for logging) but it means gateway-level tenant metrics are empty.

### 4.4 Validation

```python
# backend/src/auth/dependencies.py
payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
email: str = payload.get("sub")
if email is None:
    raise credentials_exception
token_data = TokenData(email=email)
...
result = await db.execute(
    select(User).options(selectinload(User.company)).filter(User.email == token_data.email)
)
```

`jose.jwt.decode` verifies the signature and `exp` automatically. Everything else — the user still existing, the company not being suspended — is a fresh DB read on **every single request**, with the company eager-loaded via `selectinload` so the suspension check does not fire a second query.

---

## 5. Refresh tokens: storage, rotation, revocation

Refresh tokens are **not** JWTs. They are 32 bytes of `secrets.token_urlsafe` stored as rows.

```python
# backend/src/auth/service.py
async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)
    refresh_token = RefreshToken(user_id=user_id, token=token, expires_at=expires_at)
    db.add(refresh_token)
    await db.commit()
    return token
```

| Property | Value |
|---|---|
| Format | Opaque URL-safe random string, 32 bytes of entropy |
| Lifetime | 7 days, hard-coded at [service.py:168](../../backend/src/auth/service.py:168) |
| Storage | `refresh_tokens` table, **plaintext**, `unique=True, index=True` |
| Rotation | Yes — every `/auth/refresh` revokes the old row and inserts a new one |
| Reuse detection | Detected but not acted on — see below |
| Revocation on logout | **None** — there is no logout endpoint |

### 5.1 The rotation path

`POST /auth/refresh` at [router.py:80](../../backend/src/auth/router.py:80) does two DB round trips where one would do:

```python
# backend/src/auth/router.py
new_refresh_token = await service.rotate_refresh_token(db, request.refresh_token)
user = await service.verify_refresh_token(db, new_refresh_token)
access_token = create_access_token(data={"sub": user.email, "company_id": str(user.company_id)})
```

`rotate_refresh_token` ([service.py:202](../../backend/src/auth/service.py:202)) sets `revoked = True` on the old row, calls `create_refresh_token`, and commits. `verify_refresh_token` then re-reads the brand-new row purely to get the `User`.

### 5.2 Full lifecycle sequence

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend
    participant API as "POST /api/v1/auth/*"
    participant SVC as auth.service
    participant DB as refresh_tokens

    Note over FE,DB: LOGIN
    FE->>API: POST /auth/login {email, password}
    API->>SVC: authenticate_user
    SVC->>DB: SELECT users WHERE email
    SVC-->>API: User or None
    API->>API: create_access_token sub company_id exp
    API->>SVC: create_refresh_token user.id
    SVC->>DB: INSERT token expires_at plus 7d revoked false
    API-->>FE: access_token + refresh_token + Set-Cookie refresh_token

    Note over FE,DB: NORMAL CALL
    FE->>API: GET /ai/entities with Bearer access_token
    API-->>FE: 200

    Note over FE,DB: ACCESS TOKEN EXPIRES after 30 min
    FE->>API: GET /ai/entities with expired token
    API-->>FE: 401

    Note over FE,DB: ROTATION - axios interceptor
    FE->>API: POST /auth/refresh {refresh_token}
    API->>SVC: rotate_refresh_token old
    SVC->>DB: SELECT WHERE token = old
    SVC->>DB: UPDATE old SET revoked = true
    SVC->>DB: INSERT new token
    API->>SVC: verify_refresh_token new
    SVC->>DB: SELECT user
    API-->>FE: new access_token + new refresh_token

    Note over FE,DB: LOGOUT - client side only
    FE->>FE: localStorage.removeItem access_token
    FE->>FE: localStorage.removeItem refresh_token
    Note over DB: rows stay valid for up to 7 days
```

### 5.3 The refresh-token state machine

```mermaid
stateDiagram-v2
    [*] --> Active: create_refresh_token
    Active --> Revoked: rotate_refresh_token uses it
    Active --> Expired: expires_at passes, 7 days
    Revoked --> [*]: 401 Token revoked
    Expired --> [*]: 401 Token expired
    Active --> Orphaned: user clears localStorage
    Orphaned --> Expired: still valid until expires_at
    note right of Orphaned
        No logout endpoint exists.
        Rows are never deleted or
        revoked on sign-out.
    end note
```

### 5.4 Reuse detection is a comment, not code

[service.py:186](../../backend/src/auth/service.py:186) spots the classic replay signal and then does nothing about it:

```python
# backend/src/auth/service.py
if refresh_token.revoked:
    # Security alert: Attempt to use revoked token
    # In a real system, we might revoke all tokens for this user
    raise HTTPException(status_code=401, detail="Token revoked")
```

Presenting a revoked token is a strong sign the token family was stolen. The standard response is to revoke **every** token for that user. Here only the single request is rejected; the attacker's freshly rotated token stays live.

### 5.5 The refresh cookie nobody reads

`/auth/register`, `/auth/login`, `/auth/refresh`, and `/auth/oauth/{provider}` all set an `HttpOnly; Secure; SameSite=lax` cookie named `refresh_token`. Nothing ever reads it. `POST /auth/refresh` takes the token from the JSON body (`RefreshTokenRequest`), and the frontend reads it from `localStorage`. The cookie is dead weight — but harmless, and it is the right foundation if the team later moves refresh out of `localStorage`.

---

## 6. The FastAPI dependency chain

Everything lives in [dependencies.py](../../backend/src/auth/dependencies.py) — 85 lines, four public entry points.

```mermaid
flowchart TD
    SCHEME["oauth2_scheme - OAuth2PasswordBearer tokenUrl /api/v1/auth/token auto_error=False"]
    DB["get_db - AsyncSession"]

    SCHEME --> AUTH["_authenticate_user token db"]
    DB --> AUTH

    AUTH --> C1{"token is None"}
    C1 -->|"yes"| E401["401 Could not validate credentials"]
    C1 -->|"no"| C2["jwt.decode with SECRET_KEY HS256"]
    C2 -->|"JWTError"| E401
    C2 --> C3{"payload sub present"}
    C3 -->|"no"| E401
    C3 -->|"yes"| C4["SELECT User selectinload company WHERE email = sub"]
    C4 -->|"not found"| E401
    C4 --> C5{"user.company.status == suspended"}
    C5 -->|"yes"| E403["403 Company account is suspended"]
    C5 -->|"no"| USER["User ORM object"]

    USER --> GCU["get_current_user"]
    USER --> GCUC["get_current_user_and_company"]
    USER --> GCFQ["get_current_user_from_query"]
    GCU --> RC["RoleChecker allowed_roles"]

    GCUC --> C6{"user.company is None"}
    C6 -->|"yes"| E403b["403 User is not associated with any company"]
    C6 -->|"no"| TUP["user, company tuple"]

    RC --> C7{"user.role in allowed_roles"}
    C7 -->|"no"| E403c["403 Operation not permitted"]
    C7 -->|"yes"| OK["User passed to handler"]
```

### 6.1 The four entry points

| Dependency | Returns | Used by |
|---|---|---|
| `get_current_user` | `User` | The overwhelming default — nearly every protected route |
| `get_current_user_and_company` | `(User, Company)` tuple | [social_router.py](../../backend/src/ai/social_router.py) — the only consumer |
| `get_current_user_from_query` | `User` | [ai/router.py:328](../../backend/src/ai/router.py:328) — the SSE `/executions/{id}/stream` endpoint, because `EventSource` cannot send headers |
| `RoleChecker(["..."])` | `User` | 11 call sites, listed in section 7 |

Note `auto_error=False` on `oauth2_scheme`. FastAPI will not raise on a missing header; instead `token` arrives as `None` and `_authenticate_user` raises its own 401. This is why the file has `print("Auth Debug: ...")` statements — leftover debugging that still ships. Those prints go to stdout, not the logger, and they include the user's email.

### 6.2 How `company_id` is derived and injected

There is no `company_id` dependency. **The handler reads it off the user object.** The canonical pattern is:

```python
# backend/src/ai/router.py
@router.get("/executions")
async def get_executions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_executions(current_user.company_id, current_user.role)
```

Both `company_id` **and** `role` are passed down into the service layer, and the service builds the `WHERE` clause. The `company_id` claim inside the JWT is *not* the source of truth for handlers — the DB row is.

Two escape hatches exist for cross-tenant work, both opt-in query params:

```python
# backend/src/ai/router.py — list_entities
effective_company_id = current_user.company_id
if company_id and current_user.role == "app_admin":
    effective_company_id = company_id
```

```python
# backend/src/ai/router.py — create_entity
if target_company_id:
    if current_user.role == "app_admin":
        effective_company_id = target_company_id
    elif current_user.role in ("partner_admin", "partner_user"):
        result = await db.execute(select(Company).where(
            Company.id == target_company_id,
            Company.parent_id == current_user.company_id,
        ))
        if result.scalar_one_or_none():
            effective_company_id = target_company_id
        else:
            raise HTTPException(status_code=403, detail="Not authorized to create entities for this company")
    else:
        raise HTTPException(status_code=403, detail="Cannot create entities for another company")
```

That second block is the reference implementation for "let a partner act on one of its tenants" — it re-verifies `parent_id` against the DB rather than trusting anything from the client.

### 6.3 Protecting a new endpoint — worked example

```python
# backend/src/ai/my_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.common.database import get_db
from src.auth.models import User
from src.auth.dependencies import get_current_user, RoleChecker
from src.ai.models import Widget

router = APIRouter(prefix="/widgets", tags=["Widgets"])

# 1. Plain authentication — any logged-in user, scoped to their own company.
@router.get("/{widget_id}")
async def get_widget(
    widget_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Widget).where(
            Widget.id == widget_id,
            # ALWAYS include this. There is no automatic scoping.
            Widget.company_id == current_user.company_id,
        )
    )
    widget = result.scalar_one_or_none()
    if not widget:
        # 404 not 403 — do not confirm the row exists in another tenant.
        raise HTTPException(status_code=404, detail="Widget not found")
    return widget


# 2. Role-gated — RoleChecker returns the User, so you still get company_id.
@router.delete("/{widget_id}", status_code=204)
async def delete_widget(
    widget_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["app_admin", "tenant_admin"])),
):
    ...
```

Three rules for a new endpoint:

1. **Always** take `current_user: User = Depends(get_current_user)` — even on a "harmless" read.
2. **Always** add `WHERE company_id == current_user.company_id` unless you have explicitly written the `app_admin` / partner branch.
3. Return **404**, not 403, when a row exists but belongs to another tenant. The codebase mostly does this ([service.py:119](../../backend/src/ai/service.py:119) raises `404 Entity not found` when the company filter excludes a real row) and it avoids leaking existence.

---

## 7. The RBAC model

### 7.1 The six role strings

Defined nowhere as a Python enum — only as a comment on [models.py:35](../../backend/src/auth/models.py:35) and as a TypeScript enum on the frontend at [types/index.ts:24](../../frontend/src/types/index.ts:24).

| Role string | Company type it belongs to | Typical holder |
|---|---|---|
| `app_admin` | `APP` | HireBuddha platform staff, superuser |
| `app_user` | `APP` | Platform ops / support, read-mostly |
| `partner_admin` | `PARTNER` | Reseller or agency owner managing tenants |
| `partner_user` | `PARTNER` | Reseller staff |
| `tenant_admin` | `TENANT` | Customer's own admin — **the default for self-registration** |
| `tenant_user` | `TENANT` | Customer's ordinary user — the DB column default |

Two defaults that disagree:

- `users.role` column default is `"tenant_user"` ([models.py:35](../../backend/src/auth/models.py:35)).
- `service.create_user` explicitly sets `role="tenant_admin"` for self-registration ([service.py:139](../../backend/src/auth/service.py:139)), because a self-registering user is the first person in a brand-new workspace and must be able to invite others.

### 7.2 There is no hierarchy

This is the most important RBAC fact in the codebase, and it surprises everyone. `RoleChecker` is a set-membership test:

```python
# backend/src/auth/dependencies.py
class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Operation not permitted")
        return user
```

`app_admin` is **not** implicitly allowed everywhere. It only gets through a guard if the guard's list literally contains `"app_admin"`. Every guard in the codebase spells it out by hand, which works, but means one forgotten entry locks the platform admin out of an endpoint.

The *conceptual* hierarchy — which the guard lists approximate — looks like this:

```mermaid
flowchart TD
    AA["app_admin - sees everything"]
    AU["app_user - platform reports only"]
    PA["partner_admin - own company plus child tenants"]
    PU["partner_user - read of own plus child tenants"]
    TA["tenant_admin - own company, manage users"]
    TU["tenant_user - own company, use only"]

    AA -->|"conceptually above"| AU
    AA --> PA
    PA --> PU
    PA -->|"manages"| TA
    TA --> TU

    NOTE["NOT enforced by inheritance. Every guard lists roles explicitly."]
    AA -.-> NOTE
```

### 7.3 Every `RoleChecker` guard in the codebase

| File | Endpoint | Allowed roles |
|---|---|---|
| [router.py:76](../../backend/src/auth/router.py:76) | `GET /auth/admin-only` | `app_admin` |
| [company_router.py:41](../../backend/src/auth/company_router.py:41) | `GET /companies/partners` | `app_admin` |
| [company_router.py:49](../../backend/src/auth/company_router.py:49) | `GET /companies/tenants` | `app_admin`, `partner_admin` |
| [company_router.py:65](../../backend/src/auth/company_router.py:65) | `POST /companies` | `app_admin`, `partner_admin` |
| [user_router.py:44](../../backend/src/auth/user_router.py:44) | `POST /users` | `app_admin`, `partner_admin`, `tenant_admin` |
| [partner_router.py:27](../../backend/src/auth/partner_router.py:27) | all `/partner/*` | `partner_admin`, `app_admin` |
| [ai/router.py](../../backend/src/ai/router.py) | template admin routes | `app_admin` |
| [voice/phone_pool_router.py](../../backend/src/voice/phone_pool_router.py) | pool admin | `app_admin` |
| [voice/phone_number_router.py](../../backend/src/voice/phone_number_router.py) | number admin | `app_admin` |
| [ai/tool_management_router.py](../../backend/src/ai/tool_management_router.py) | tool registry | `app_admin` |

### 7.4 The four *other* guard styles

`RoleChecker` is not the only mechanism. Four hand-rolled variants coexist, and they disagree about what "admin" means:

| Helper | File | Definition of admin |
|---|---|---|
| `_require_admin` | [ai/api/admin.py:91](../../backend/src/ai/api/admin.py:91) | `app_admin`, `partner_admin`, **`tenant_admin`** |
| `_require_admin` | [billing/cron_router.py:16](../../backend/src/billing/cron_router.py:16) | `app_admin` only |
| `_require_app_admin` | [config/router.py:156](../../backend/src/config/router.py:156) | `app_admin` only |
| `_require_roles(user, *roles)` | [ai/reports_router.py:24](../../backend/src/ai/reports_router.py:24) | varies per endpoint |

Two functions with the same name, `_require_admin`, mean two different things. `ai/api/admin.py` treats `tenant_admin` as an admin — so the "kernel admin" endpoints (`/api/v1/ai/admin/*`, the Meta-Intelligence Board and KPI dashboards) are open to every tenant admin, scoped to their own `company_id`. That is intentional, and [router/index.tsx:545](../../frontend/src/router/index.tsx:545) mirrors it in the frontend, but the naming makes it easy to misread.

### 7.5 The permission matrix

Derived from the actual guard code, not from intent. Legend: **Y** = allowed, **own** = allowed but restricted to own company, **own+children** = own company plus tenants whose `parent_id` matches, **—** = 403.

| Capability | Source | `app_admin` | `app_user` | `partner_admin` | `partner_user` | `tenant_admin` | `tenant_user` |
|---|---|---|---|---|---|---|---|
| List companies | [company_router.py:13](../../backend/src/auth/company_router.py:13) | all | own | own+children | own+children | own | own |
| List partner companies | [company_router.py:38](../../backend/src/auth/company_router.py:38) | Y | — | — | — | — | — |
| List tenant companies | [company_router.py:46](../../backend/src/auth/company_router.py:46) | all | — | own children | — | — | — |
| Create company | [company_router.py:61](../../backend/src/auth/company_router.py:61) | any type | — | `TENANT` only, forced `parent_id` | — | — | — |
| Update company / suspend | [company_router.py:110](../../backend/src/auth/company_router.py:110) | any | own | own only | own only | own | **own** |
| List users | [user_router.py:14](../../backend/src/auth/user_router.py:14) | all | — | own+children | — | own | — |
| Create user | [service.py:52](../../backend/src/auth/service.py:52) | any role, any company | — | 4 non-app roles, own+children | — | `tenant_*` in own company | — |
| Update user | [user_router.py:48](../../backend/src/auth/user_router.py:48) | any | own company | own company | own company | own company | self only |
| Partner dashboard `/partner/*` | [partner_router.py:27](../../backend/src/auth/partner_router.py:27) | all tenants | — | own children | — | — | — |
| Upload own avatar | [profile_router.py:26](../../backend/src/auth/profile_router.py:26) | Y | Y | Y | Y | Y | Y |
| Upload company logo | [profile_router.py:66](../../backend/src/auth/profile_router.py:66) | Y | — | Y | — | Y | — |
| Onboarding step / complete / skip | [onboarding_router.py](../../backend/src/auth/onboarding_router.py) | Y | Y | Y | Y | Y | Y |
| Create AI entity | [ai/router.py:19](../../backend/src/ai/router.py:19) | any company | own | own+children | own+children | own | own |
| Read AI entity | [ai/service.py:78](../../backend/src/ai/service.py:78) | all | own | own+children+templates | own+children+templates | own+templates | own+templates |
| Kernel admin `/ai/admin/*` | [ai/api/admin.py:91](../../backend/src/ai/api/admin.py:91) | own scope | — | own scope | — | own scope | — |
| Manage AI task defaults | [config/router.py:156](../../backend/src/config/router.py:156) | Y | — | — | — | — | — |
| Create integration | [config/router.py:64](../../backend/src/config/router.py:64) | any category | — | any category, own | — | 4 categories only, own | — |
| Trigger daily-credit cron | [billing/cron_router.py:16](../../backend/src/billing/cron_router.py:16) | Y | — | — | — | — | — |
| Platform analytics reports | [ai/reports_router.py:205](../../backend/src/ai/reports_router.py:205) | Y | Y | — | — | — | — |
| Portfolio analytics reports | [ai/reports_router.py:116](../../backend/src/ai/reports_router.py:116) | Y | — | Y | Y | — | — |
| Tool registry management | `tool_management_router.py` | Y | — | — | — | — | — |
| Phone pool administration | `phone_pool_router.py` | Y | — | — | — | — | — |

### 7.6 Where enforcement is missing or inconsistent

Being blunt about the weak spots:

1. **`app_user` is a role with almost no meaning.** It appears in only three backend lines, all in `reports_router.py`. It is absent from every `RoleChecker` list, so an `app_user` is rejected from `/companies/partners`, `/companies/tenants`, `POST /companies`, `POST /users` and the whole `/partner/*` tree — but `GET /companies` falls into the `else` branch and returns "own company only", the same as a tenant user. In practice `app_user` behaves like a tenant user with two extra report pages.

2. **`tenant_user` can suspend its own company.** [company_router.py:118](../../backend/src/auth/company_router.py:118) guards only on `current_user.company_id != company_id`:
   ```python
   if current_user.role != "app_admin" and current_user.company_id != company_id:
       raise HTTPException(status_code=403, detail="Not authorized to update this company")
   ```
   There is no role check at all. Any authenticated user can `PATCH /companies/{their_own_id}` with `{"status": "suspended"}` and lock their entire company out of the platform, including its admins. The inline comment on line 119 (`Also allow partner admins to update their own tenants?`) shows this was known to be unfinished.

3. **Partner admins cannot update their own tenants.** The same check means a `partner_admin` can create a tenant but then cannot rename or suspend it — only `app_admin` can. The `/partner/*` router is read-only.

4. **`update_user` lets any admin change any role in their company.** [user_router.py:62-72](../../backend/src/auth/user_router.py:62) checks company match and admin-ness, then blindly applies `UserUpdate`, which includes `role: Optional[str]`. A `tenant_admin` can therefore set their own role to `"app_admin"`. Nothing validates the target role string. **This is a privilege-escalation path.** Note that the stricter `create_user_as_admin` *does* validate assignable roles — the update path simply never got the same treatment.

5. **`is_active` is never checked.** `authenticate_user` and `_authenticate_user` both ignore it. Deactivating a user in the UI does not lock them out.

6. **`is_verified` is never checked either.** Self-registered users get `is_verified = False` and a token in the same response. Nothing gates on verification.

---

## 8. The company hierarchy: APP, PARTNER, TENANT

### 8.1 How rows relate

```mermaid
flowchart TD
    subgraph APP_LEVEL["type = APP"]
        APP["HireBuddha - parent_id NULL"]
        AAU["app_admin, app_user"]
    end
    subgraph PARTNER_LEVEL["type = PARTNER"]
        P1["Partner A - parent_id NULL"]
        P2["Partner B - parent_id NULL"]
        PAU["partner_admin, partner_user"]
    end
    subgraph TENANT_LEVEL["type = TENANT"]
        T1["Tenant A1 - parent_id = Partner A"]
        T2["Tenant A2 - parent_id = Partner A"]
        T3["Tenant B1 - parent_id = Partner B"]
        T4["Direct Tenant - parent_id NULL, self-registered"]
        TAU["tenant_admin, tenant_user"]
    end

    APP -.->|"app_admin sees all, no FK"| P1
    APP -.-> P2
    APP -.-> T4
    P1 -->|"parent_id"| T1
    P1 -->|"parent_id"| T2
    P2 -->|"parent_id"| T3

    APP --- AAU
    P1 --- PAU
    T1 --- TAU
```

Key structural facts:

- **The APP company is not a parent of anything.** `app_admin` visibility comes from `if role == "app_admin": no filter`, not from a `parent_id` chain. There is no code that creates or looks up "the APP company".
- **Partners have `parent_id = NULL`.** Only tenants ever carry a non-null `parent_id`, and only when created by a partner or by an app admin who supplied one.
- **Self-registered tenants are orphans.** [service.py:105](../../backend/src/auth/service.py:105) creates a `TENANT` company with no `parent_id`. It belongs to no partner and shows up only for `app_admin`.
- **The tree is one level deep in practice.** Every partner query is `Company.parent_id == current_user.company_id` — a single hop. A tenant of a tenant would be invisible to the grandparent.

### 8.2 How a partner creates a tenant

```mermaid
sequenceDiagram
    autonumber
    participant PA as partner_admin
    participant CR as "POST /api/v1/companies"
    participant RC as "RoleChecker app_admin partner_admin"
    participant DB as PostgreSQL
    participant BILL as billing.CreditWallet

    PA->>CR: {name, type: TENANT, parent_id: ignored}
    CR->>RC: check role
    RC-->>CR: ok
    Note over CR: if role == partner_admin
    CR->>CR: reject unless type == TENANT
    CR->>CR: FORCE parent_id = current_user.company_id
    CR->>DB: INSERT companies status active onboarding_status pending
    CR->>DB: flush to get company.id
    alt type TENANT and apply_default_daily_credits
        CR->>BILL: _provision_new_tenant company
        BILL->>DB: queue INSERT credit_wallets
        opt custom_daily_credits supplied
            CR->>DB: UPDATE wallet.daily_credits
        end
    end
    CR->>DB: COMMIT
    CR-->>PA: CompanyResponse

    Note over PA,DB: Then, separately:
    PA->>DB: POST /api/v1/users with company_id + role tenant_admin
```

The `parent_id` a partner sends is discarded and overwritten — [company_router.py:68-71](../../backend/src/auth/company_router.py:68):

```python
# backend/src/auth/company_router.py
if current_user.role == "partner_admin":
    if company.type != "TENANT":
        raise HTTPException(status_code=403, detail="Partner admins can only create Tenants")
    company.parent_id = current_user.company_id
```

That is the correct pattern — never trust a client-supplied parent.

Creating the tenant's first user is a **separate** call to `POST /api/v1/users`, validated by `create_user_as_admin` ([service.py:60-72](../../backend/src/auth/service.py:60)), which re-loads the target company and confirms `target_company.parent_id == creator.company_id`.

### 8.3 How visibility cascades

```mermaid
flowchart LR
    subgraph Q["The three query shapes"]
        A["app_admin - no WHERE clause"]
        B["partner - WHERE id = mine OR parent_id = mine"]
        C["tenant - WHERE company_id = mine"]
    end
    A --> R1["all rows"]
    B --> R2["own rows plus direct children rows"]
    C --> R3["own rows only"]
```

The partner pattern appears verbatim in several places, e.g. [user_router.py:25](../../backend/src/auth/user_router.py:25):

```python
# backend/src/auth/user_router.py
comp_result = await db.execute(
    select(Company.id).where(
        (Company.id == current_user.company_id) | (Company.parent_id == current_user.company_id)
    )
)
company_ids = comp_result.scalars().all()
result = await db.execute(select(User).where(User.company_id.in_(company_ids)))
```

Note it is copy-pasted rather than factored into a shared helper. There is no `visible_company_ids(user)` utility, so each new endpoint re-implements the cascade — and some get it wrong (see `partner_user` in the table above, which is excluded from `list_users` entirely but included in `list_companies`).

---

## 9. Tenant isolation: how queries get scoped

### 9.1 The layers, and which one actually enforces

```mermaid
graph TB
    subgraph L1["Layer 1 - Gateway :8001"]
        G1["GatewayAuthMiddleware"]
        G2["Extracts company_id for logging only"]
        G3["ENFORCES NOTHING on REST"]
    end
    subgraph L2["Layer 2 - Backend middleware"]
        M1["CompanySuspensionMiddleware"]
        M2["Blocks suspended companies"]
        M3["Does NOT scope queries"]
    end
    subgraph L3["Layer 3 - FastAPI dependency"]
        D1["get_current_user"]
        D2["Supplies current_user.company_id"]
        D3["Does NOT scope queries"]
    end
    subgraph L4["Layer 4 - Route handler"]
        H1["Chooses effective_company_id"]
        H2["Handles app_admin and partner branches"]
    end
    subgraph L5["Layer 5 - Service and query"]
        S1["WHERE company_id = :cid"]
        S2["THIS IS THE ONLY REAL ENFORCEMENT"]
    end
    subgraph L6["Layer 6 - Database"]
        DB1["No Row Level Security"]
        DB2["No policies, no per-tenant schemas"]
    end

    L1 --> L2 --> L3 --> L4 --> L5 --> L6
```

**All isolation lives in layer 5, written by hand.** PostgreSQL Row Level Security is not enabled anywhere; there is no shared query mixin, no SQLAlchemy event listener injecting a tenant filter, and no per-tenant schema or database. A forgotten `WHERE` is a live cross-tenant read.

### 9.2 Concrete scoping code

The good examples — copy these:

```python
# backend/src/ai/service.py — get_entity, the fullest three-way branch
if user_role == "app_admin":
    pass  # No company filter
elif user_role in ("partner_admin", "partner_user"):
    child_result = await self.db.execute(
        select(Company.id).where(Company.parent_id == company_id)
    )
    child_ids = [row[0] for row in child_result.fetchall()]
    allowed_ids = [company_id] + child_ids
    query = query.where(or_(
        HierarchicalEntity.company_id.in_(allowed_ids),
        HierarchicalEntity.is_template == True,
    ))
else:
    query = query.where(or_(
        HierarchicalEntity.company_id == company_id,
        HierarchicalEntity.is_template == True,
    ))
```

```python
# backend/src/ai/api/admin.py — check-then-return-company_id pattern for a single row
async def _execution_company_check(db, run_id, user) -> UUID:
    row = (await db.execute(
        select(ExecutionRun.company_id, ExecutionRun.entity_id).where(ExecutionRun.id == run_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="execution not found")
    company_id, _entity_id = row
    if user.role != "app_admin" and company_id != user.company_id:
        raise HTTPException(status_code=403, detail="not authorised for this run")
    return company_id
```

```python
# backend/src/voice/sessions_router.py — the simple, most common shape
select(VoiceSession).where(VoiceSession.company_id == current_user.company_id)
```

```python
# backend/src/billing/credits_router.py — never accepts a company_id from the client
wallet = await credit_svc.get_or_create_wallet(current_user.company_id)
```

```python
# backend/src/ai/social_router.py — uses the (user, company) tuple dependency
user, company = auth
select(SocialConnection).where(
    SocialConnection.id == connection_id,
    SocialConnection.company_id == company.id,
)
```

### 9.3 Where the leakage risk sits

| Risk | Location | Detail |
|---|---|---|
| **Email connections have no auth at all** | [ai/email_router.py](../../backend/src/ai/email_router.py) | `GET /api/v1/email/connections?company_id=<any-uuid>` has **no `Depends(get_current_user)`**. Any unauthenticated caller can enumerate another company's mailboxes. |
| **Email connection delete/validate ignore company** | [email_router.py:179](../../backend/src/ai/email_router.py:179), [:204](../../backend/src/ai/email_router.py:204) | Look up by `connection_id` alone. `DELETE /email/connections/{id}` deletes any tenant's connection; `POST .../validate` decrypts another tenant's app password and attempts an IMAP login with it. |
| Templates are global | [ai/service.py:57](../../backend/src/ai/service.py:57) | `is_template == True` rows have `company_id = NULL` and are visible to everyone by design. Anything put in a template is public to all tenants. |
| `app_admin` short-circuits | throughout | `if user_role != "app_admin"` skips the filter entirely. Correct, but it means a role-escalation bug (7.6 item 4) becomes a full-database read. |
| Copy-pasted cascade logic | `user_router`, `company_router`, `ai/router`, `ai/service`, `phone_number_router` | Five independent implementations of "own + children". They already disagree about `partner_user`. |
| Webhooks derive tenancy from provider data | [voice/webhook_router.py](../../backend/src/voice/webhook_router.py) | `company_id` comes from the phone-number assignment row, not from a token. Correct approach, but the trust boundary is the telephony provider's signature, not a HireBuddha credential. |

The email router is the standout. Its own code comments admit it:

```python
# backend/src/ai/email_router.py
async def create_email_connection(
    data: EmailConnectionCreate,
    db: AsyncSession = Depends(get_db),
    # current_user will be injected by auth middleware in production
    company_id: Optional[str] = None
):
    """Create a new email connection with encrypted credentials."""
    # For now, use a placeholder company_id (auth middleware will provide real one)
```

There is no such middleware. `CompanySuspensionMiddleware` does not inject anything, and it lets a request with no `Authorization` header straight through. The frontend passes `companyId` explicitly from [EmailConnectionWizard.tsx:86](../../frontend/src/components/EmailConnectionWizard.tsx:86), which is why it works in the UI — but that also means the client picks its own tenant. Compare with `social_router.py`, which took the same feature and did it correctly with `get_current_user_and_company`.

---

## 10. CompanySuspensionMiddleware

Registered once, on the **main backend only** ([main.py:26-27](../../backend/src/main.py:26)) — not on the gateway.

```python
# backend/src/main.py
from src.common.middleware import CompanySuspensionMiddleware
app.add_middleware(CompanySuspensionMiddleware)
```

### 10.1 What it does

```mermaid
flowchart TD
    REQ["Incoming request"] --> P{"path starts with /api/v1/auth or is / or /docs or /openapi.json"}
    P -->|"yes"| PASS["call_next - allowed"]
    P -->|"no"| H{"Authorization header starts with Bearer"}
    H -->|"no"| PASS
    H -->|"yes"| DEC["open new AsyncSessionLocal - decode_access_token"]
    DEC --> V{"payload valid"}
    V -->|"no"| PASS
    V -->|"yes"| CID{"company_id claim present"}
    CID -->|"no"| PASS
    CID -->|"yes"| Q["SELECT companies WHERE id = company_id"]
    Q --> S{"company.status == suspended"}
    S -->|"yes"| BLOCK["403 JSON - Company is suspended. Please contact support."]
    S -->|"no"| PASS
    DEC -.->|"any exception"| SWALLOW["log error, PASS"]
```

Key behaviours:

| Behaviour | Consequence |
|---|---|
| Skips all `/api/v1/auth*` paths | A suspended company's users can still **log in** and get tokens. They are blocked on the next business request. |
| Passes through when there is no `Authorization` header | Unauthenticated endpoints are untouched. Also means it provides zero protection for the unauthenticated email router. |
| Opens a **fresh `AsyncSessionLocal`** and runs one extra `SELECT` per request | An additional DB round trip on every authenticated API call, outside the request's own session. |
| Reads `company_id` **from the JWT claim** | If a user is moved between companies, the middleware checks the *old* company until the token expires, while `get_current_user` checks the new one. |
| Swallows every exception and continues | A DB outage silently disables suspension enforcement rather than failing closed. |

### 10.2 Double enforcement

Suspension is checked in two independent places, which is why the middleware's gaps are mostly benign:

```python
# backend/src/auth/dependencies.py — inside _authenticate_user
if user.company and user.company.status == "suspended":
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Company account is suspended. Please contact support."
    )
```

That dependency-level check uses the eager-loaded `user.company`, so it is correct even after a company move, and it costs no extra query. It is the stronger of the two. The middleware's own docstring admits it exists only because "the requirement specifically asked for Middleware".

### 10.3 How a company gets suspended

```mermaid
stateDiagram-v2
    [*] --> active: company created
    active --> suspended: "PATCH /api/v1/companies/{id} status=suspended"
    suspended --> active: "PATCH /api/v1/companies/{id} status=active"

    state suspended {
        [*] --> CanStillLogin: "/api/v1/auth/* is skipped"
        CanStillLogin --> Blocked403: any other API call
    }
```

The only writer is `PATCH /api/v1/companies/{company_id}` ([company_router.py:110](../../backend/src/auth/company_router.py:110)) with `CompanyUpdate.status`. In the UI it is a toggle in Platform Management:

```tsx
// frontend/src/pages/PlatformManagement.tsx
const newStatus = company.status === 'active' ? 'suspended' : 'active';
await companyService.updateCompany(company.id, { status: newStatus });
```

Nothing else — no billing job, no dunning process, no cron — ever sets `status = "suspended"`. Suspension is entirely a manual admin action today. And, per section 7.6, the endpoint's permission check is weak enough that a `tenant_user` can suspend their own company.

---

## 11. Internal service-to-service auth

### 11.1 The `INTERNAL_TOKEN` shared secret

| Property | Value |
|---|---|
| Setting | `INTERNAL_TOKEN` on [gateway_config.py:32](../../backend/src/gateway/gateway_config.py:32) |
| Default | `"change-me-in-production"` — and `backend/.env` still holds exactly that |
| Header | `X-Internal-Token` |
| Comparison | `token != settings.INTERNAL_TOKEN` — a plain `!=`, not `hmac.compare_digest` |
| Scope | Only paths starting with `/internal/event` |

```python
# backend/src/gateway/auth_middleware.py
if path.startswith("/internal/event"):
    token = request.headers.get("X-Internal-Token", "")
    if token != settings.INTERNAL_TOKEN:
        return _unauthorized("Invalid or missing X-Internal-Token")
    tenant.is_internal = True
    tenant.source_channel = "internal"
```

There is a second, belt-and-braces check as a dependency — `require_internal` at [auth_middleware.py:135](../../backend/src/gateway/auth_middleware.py:135) — which the endpoint uses:

```python
# backend/src/gateway/internal_event.py
async def unified_internal_event(
    event: InternalEvent,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_internal),
):
```

`require_internal` does not re-check the secret; it only asserts that `request.state.tenant.is_internal` is `True`, which the middleware set. So the real gate is the middleware.

### 11.2 What the internal channel can do

`POST /internal/event` accepts an `InternalEvent` whose `client_id` field is a **caller-supplied tenant UUID** ([internal_event.py:48](../../backend/src/gateway/internal_event.py:48)). The event is wrapped in an `EventEnvelope` and published to the event bus, which routes it to that tenant's agents.

That is the trust model: **the internal token is a tenant-impersonation credential.** Anyone holding it can inject an event into any tenant. That is intentional for cron jobs and the vector indexer, but it means the secret must be treated as root.

`emit_internal_event` at [internal_event.py:157](../../backend/src/gateway/internal_event.py:157) is the in-process shortcut for platform code — it skips HTTP and the token entirely and publishes straight to the bus.

### 11.3 Trust zones

```mermaid
graph TB
    subgraph UNTRUSTED["Zone 0 - Untrusted public internet"]
        BROWSER["Browser SPA"]
        TELCO["Twilio / Tata Tele webhooks"]
        ATTACKER["Anyone"]
    end

    subgraph EDGE["Zone 1 - Gateway :8001 - GatewayAuthMiddleware"]
        RESTP["/api/v1/* - passthrough, NOT enforced here"]
        WH["/webhook/inbound - client_id query param"]
        STREAM["/stream/audio and /stream/video - client_id query param"]
        INTEP["/internal/event - X-Internal-Token ENFORCED"]
    end

    subgraph APP["Zone 2 - Backend :8000 - real authorisation"]
        DEPS["get_current_user + RoleChecker"]
        SUSPM["CompanySuspensionMiddleware"]
        HANDLERS["Route handlers with company_id scoping"]
    end

    subgraph INTERNAL["Zone 3 - Trusted internal services"]
        CRON["arq cron jobs"]
        VDB["Vector indexer"]
        AGENTS["Agent kernel"]
    end

    subgraph DATA["Zone 4 - Data - no RLS"]
        PG[("PostgreSQL")]
        REDIS[("Redis")]
    end

    BROWSER -->|"Bearer JWT"| RESTP
    TELCO -->|"provider signature"| WH
    ATTACKER -.->|"blocked - 401"| INTEP
    CRON -->|"X-Internal-Token"| INTEP
    VDB -->|"X-Internal-Token"| INTEP
    AGENTS -->|"in-process emit_internal_event, no token"| APP

    RESTP --> SUSPM --> DEPS --> HANDLERS --> PG
    INTEP --> AGENTS
    WH --> HANDLERS
    STREAM --> AGENTS
    HANDLERS --> REDIS
```

Boundary notes:

- **Zone 1 does not authorise REST.** The middleware's own docstring says so: *"Missing / invalid credentials are NOT blocked here for REST / Webhook paths — the internal handlers enforce auth. Only /internal/event is blocked at middleware."* If the backend on port 8000 is reachable directly, bypassing the gateway changes nothing security-wise — which is good design, but it also means the gateway is not a security control.
- **`/webhook/inbound` and `/stream/*` take `client_id` straight from a query parameter** with no verification at all ([auth_middleware.py:86-96](../../backend/src/gateway/auth_middleware.py:86)). The comment in the class docstring mentions "signature validation" for webhooks, but the middleware performs none — any signature checking has to happen inside the webhook handler.
- **There is no mTLS, no service mesh, no network policy in this code.** The only thing separating zone 3 from zone 0 is the shared secret and whatever the deployment's firewall does.

---

## 12. OAuth: login, social connections, email connections

Three distinct OAuth-ish flows exist and they share almost nothing.

### 12.1 Flow A — social login (Google / Microsoft) for platform sign-in

Backend: `POST /api/v1/auth/oauth/{provider}` at [router.py:102](../../backend/src/auth/router.py:102). Frontend: [oauth.service.ts](../../frontend/src/services/oauth.service.ts) plus [OAuthCallback.tsx](../../frontend/src/pages/auth/OAuthCallback.tsx).

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant FE as "SPA"
    participant P as "Google or Microsoft"
    participant BE as "POST /auth/oauth/{provider}"
    participant DB as PostgreSQL

    U->>FE: clicks provider button
    FE->>P: redirect to authorize with client_id, redirect_uri, scope openid email profile, state=provider
    P->>U: consent screen
    U->>P: approves
    P->>FE: redirect to /auth/callback?code=...&state=provider
    FE->>FE: OAuthCallback reads state as provider, code from query
    FE->>BE: POST /auth/oauth/{provider} {code, redirect_uri}
    BE->>P: POST token endpoint with client_id, client_secret, code, grant_type authorization_code
    P-->>BE: {access_token}
    BE->>P: GET userinfo or graph.microsoft.com/v1.0/me with that token
    P-->>BE: {email, name}
    BE->>DB: get_or_create_oauth_user
    alt user exists
        DB-->>BE: existing User
    else new user
        BE->>DB: INSERT companies type TENANT, onboarding pending, created_via oauth
        BE->>DB: INSERT users role tenant_admin, is_verified true, random hashed password
        BE->>DB: provision CreditWallet
    end
    BE->>DB: INSERT refresh_tokens
    BE-->>FE: {access_token, refresh_token} + Set-Cookie
    FE->>FE: localStorage.setItem both, redirect to /dashboard
```

Provider configuration comes from raw `os.getenv` inside the handler, not from `settings`:

| Env var | Used at |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | [router.py:112-113](../../backend/src/auth/router.py:112) |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | [router.py:135-136](../../backend/src/auth/router.py:135) |
| `VITE_GOOGLE_CLIENT_ID` / `VITE_MICROSOFT_CLIENT_ID` | [oauth.service.ts:3-4](../../frontend/src/services/oauth.service.ts:3) |

Three problems with this flow, all visible in the code:

1. **The login-page buttons are not wired.** [LoginPage.tsx:76-85](../../frontend/src/pages/auth/LoginPage.tsx:76) renders "Google" and "Microsoft" buttons with **no `onClick` handler**, and does not import `oauthService`. `oauthService` is referenced only by `OAuthCallback.tsx`. The flow is unreachable from the UI as written.
2. **`state` is used as a provider label, not as a CSRF nonce.** `state: 'google'` is guessable and constant, so it provides no CSRF protection on the callback. The OAuth spec's whole point for `state` is unpredictability.
3. **Account linking is by email with no verification of provider trust.** `get_or_create_oauth_user` matches on email alone ([service.py:221](../../backend/src/auth/service.py:221)). If an attacker can get a provider to assert an email that already exists as a password account, they take over that account. Microsoft's `userPrincipalName` fallback ([router.py:152](../../backend/src/auth/router.py:152)) is especially loose.

### 12.2 Flow B — social connections (agent posting credentials)

This is *not* login. It stores third-party OAuth tokens so agents can act on a tenant's social accounts. Router: [social_router.py](../../backend/src/ai/social_router.py). Service: [social_connection_service.py](../../backend/src/ai/social_connection_service.py).

Critically, **the backend does not run the OAuth handshake for these.** `POST /api/social-connections` accepts an already-obtained `access_token` and `refresh_token` in the request body. The handshake happens somewhere outside this codebase (or by hand).

```mermaid
sequenceDiagram
    autonumber
    participant TA as tenant_admin
    participant SR as "POST /api/social-connections"
    participant DEP as get_current_user_and_company
    participant SEC as "security.encrypt_api_key - AES-256-GCM"
    participant DB as social_connections
    participant AG as "Agent tool at runtime"
    participant PLAT as "LinkedIn / X / Meta / Google"

    TA->>SR: {platform, access_token, refresh_token, token_expires_at, oauth_metadata}
    SR->>DEP: resolve (user, company)
    DEP-->>SR: company
    SR->>SR: reject if platform not in VALID_PLATFORMS
    SR->>DB: SELECT existing by company_id + platform + platform_user_id
    SR->>SEC: encrypt access_token and refresh_token
    SEC-->>SR: base64 nonce plus ciphertext
    SR->>DB: INSERT company_id, encrypted tokens, scopes, oauth_metadata
    SR-->>TA: 201 SocialConnectionResponse - tokens never echoed back

    Note over AG,PLAT: Later, during an agent run
    AG->>DB: resolve_connection company_id, platform
    DB-->>AG: row
    AG->>AG: decrypt_api_key
    alt token_expires_at within 10 minutes
        AG->>PLAT: POST platform token_url with refresh_token, client_id, client_secret from oauth_metadata
        PLAT-->>AG: new access_token, expires_in
        AG->>DB: UPDATE encrypted tokens, status active
    end
    AG->>PLAT: authenticated API call
```

Storage details:

| Aspect | Detail |
|---|---|
| Encryption | AES-256-GCM via [security.py:36](../../backend/src/common/security.py:36) `encrypt_api_key` |
| Key | `settings.ENCRYPTION_MASTER_KEY`, truncated or `\0`-padded to 32 bytes |
| Format | `base64(12-byte nonce ‖ ciphertext ‖ GCM tag)` |
| Refresh threshold | `TOKEN_REFRESH_THRESHOLD_MINUTES = 10` ([social_connection_service.py:68](../../backend/src/ai/social_connection_service.py:68)) |
| Platforms with refresh config | `linkedin`, `twitter`, `facebook`, `instagram`, `google_ads`, `youtube`, `tiktok`, `reddit` |
| `VALID_PLATFORMS` (create allow-list) | the above plus `quora`, minus none — 9 entries at [social_router.py:65](../../backend/src/ai/social_router.py:65) |

Note `quora` is in `VALID_PLATFORMS` but has no entry in `PLATFORM_REFRESH_CONFIG`, so its tokens can be stored but never refreshed. Note also that `client_secret` for each platform is stored **inside `oauth_metadata`**, a plain JSONB column — unlike the tokens, it is **not encrypted**.

### 12.3 Flow C — email connections (app passwords, not OAuth)

Despite living next to the OAuth code, email connections use **IMAP/SMTP app passwords**, not OAuth.

```mermaid
stateDiagram-v2
    [*] --> provider: wizard opens
    provider --> credentials: user picks gmail, outlook, or custom
    credentials --> validate: "POST /email/connections - status pending_validation"
    validate --> complete: "POST /email/connections/{id}/validate - IMAP NOOP returns OK"
    validate --> validate: IMAP error, status auth_failed
    complete --> [*]: is_active true, status active
```

The app password is encrypted with the same `encrypt_api_key` and validated by a real `imaplib.IMAP4_SSL` login plus `NOOP` ([email_router.py:231-233](../../backend/src/ai/email_router.py:231)). The wizard is [EmailConnectionWizard.tsx](../../frontend/src/components/EmailConnectionWizard.tsx).

As covered in section 9.3, **none of these endpoints authenticate**. That is the single highest-severity finding in this document.

---

## 13. Onboarding and the company state machine

Onboarding state lives on the `companies` row, not on the user. Two columns carry it: `onboarding_status` (a string) and `onboarding_metadata` (JSONB).

### 13.1 The five steps

```python
# backend/src/auth/onboarding_router.py
ONBOARDING_STEPS = [
    "company_profile",
    "integrations",
    "first_agent",
    "phone_setup",
    "billing",
]
```

| Step | What the wizard shows | Does the backend do anything? |
|---|---|---|
| `company_profile` | Workspace name + industry dropdown | **Yes** — writes `company.name` and `company.logo_url` from `step_data` |
| `integrations` | Informational cards about Gemini / OpenAI / Email / WhatsApp | No — records completion only |
| `first_agent` | Informational cards about agent templates | No |
| `phone_setup` | Informational cards, marked `skippable` | No |
| `billing` | Informational cards about daily credits | No |

Only the first step has server-side behaviour ([onboarding_router.py:96-101](../../backend/src/auth/onboarding_router.py:96)). The other four are progress tracking — the actual integration/agent/phone/billing setup happens on their own pages later.

### 13.2 The endpoints

| Method | Path | Effect on `onboarding_status` |
|---|---|---|
| `GET` | `/api/v1/onboarding/status` | none — returns status, `completed_steps`, `current_step`, `completion_pct` |
| `POST` | `/api/v1/onboarding/step/{step_name}` | sets `in_progress`, appends to `metadata.completed_steps` |
| `POST` | `/api/v1/onboarding/complete` | sets `completed`, writes `metadata.completed_at` |
| `POST` | `/api/v1/onboarding/skip` | sets `completed`, writes `metadata.skipped = true` |

All four use plain `get_current_user` — **any role, any user in the company** can advance or skip onboarding for the whole company.

### 13.3 The state machine

```mermaid
stateDiagram-v2
    [*] --> pending: "company created - self_registration, oauth, or admin"

    pending --> in_progress: "POST /onboarding/step/{name}"
    in_progress --> in_progress: "further steps appended to completed_steps"

    in_progress --> completed: "POST /onboarding/complete"
    pending --> completed: "POST /onboarding/skip"
    in_progress --> completed: "POST /onboarding/skip - metadata.skipped true"

    completed --> [*]

    note right of pending
        onboarding_metadata seeded at creation:
        completed_steps empty list
        created_via self_registration or oauth or admin
        created_by set when admin-created
    end note

    note right of completed
        completed_at ISO timestamp written by /complete
        skipped true written by /skip
        NOTE - /skip does not write completed_at
    end note
```

### 13.4 `onboarding_metadata` shape

| Key | Written by | Value |
|---|---|---|
| `completed_steps` | `/step/{name}` | list of step names, append-only, de-duplicated |
| `created_via` | company creation | `"self_registration"` \| `"oauth"` \| `"admin"` |
| `created_by` | [company_router.py:82](../../backend/src/auth/company_router.py:82) | creating user's UUID, admin path only |
| `step_data` | `/step/{name}` | `{ step_name: {...arbitrary} }` — e.g. `company_profile: {name, industry}` |
| `completed_at` | `/complete` | ISO-8601 UTC timestamp |
| `skipped` | `/skip` | `true` |

### 13.5 The redirect logic, and where it disagrees with itself

The `onboarding_router` docstring claims *"the ProtectedRoute guard redirects users with onboarding_status != 'completed' to /onboarding"*. **`ProtectedRoute` does no such thing** — read [router/index.tsx:78-94](../../frontend/src/router/index.tsx:78); it only checks authentication and `allowedRoles`.

The real redirect lives in the login handler:

```tsx
// frontend/src/hooks/useAuth.tsx
if (currentUser.role === 'tenant_admin' || currentUser.role === 'tenant_user') {
    const { onboardingService } = await import('@/services/platform.service');
    const status = await onboardingService.getStatus();
    if (status.status !== 'completed') {
        window.location.href = '/onboarding';
        return;
    }
}
```

So onboarding is enforced **only at login**, **only for tenant roles**, and a failed status call falls through to the dashboard. `register()` sends everyone to `/onboarding` unconditionally. Navigating directly to `/dashboard` with `onboarding_status = "pending"` works fine.

---

## 14. Frontend route protection and token storage

### 14.1 Token storage and attachment

Tokens live in **`localStorage`**, set in three places: [auth.service.ts:9-10](../../frontend/src/services/auth.service.ts:9) (login), `:20-21` (register), and [oauth.service.ts:72-73](../../frontend/src/services/oauth.service.ts:72) (OAuth callback).

```mermaid
sequenceDiagram
    autonumber
    participant C as "Component"
    participant AX as "apiClient - axios instance"
    participant LS as localStorage
    participant API as "Backend /api/v1"

    C->>AX: apiClient.get('/ai/entities')
    AX->>LS: getItem('access_token')
    LS-->>AX: token
    AX->>AX: "request interceptor sets Authorization Bearer token"
    AX->>API: GET with header
    alt 200
        API-->>AX: data
        AX-->>C: data
    else 401 and not already retried
        API-->>AX: 401
        AX->>AX: "response interceptor sets originalRequest._retry"
        AX->>LS: getItem('refresh_token')
        AX->>API: "POST /auth/refresh via bare axios, no interceptor"
        alt refresh ok
            API-->>AX: new access_token + refresh_token
            AX->>LS: setItem both
            AX->>API: replay original request with new token
            API-->>C: data
        else refresh fails
            AX->>LS: removeItem both
            AX->>AX: "window.location.href = '/login'"
        end
    end
```

The interceptor pair is at [api.client.ts:17](../../frontend/src/services/api.client.ts:17) (request) and `:29` (response). Base URL defaults to `https://gateway.hirebuddha.com/api/v1`, overridable with `VITE_API_BASE_URL`.

Two things to know:

- **`localStorage` is readable by any JavaScript on the page.** An XSS bug hands over both tokens. The `HttpOnly` refresh cookie the backend already sets would be the safer store, but nothing reads it (section 5.5).
- **The `_retry` flag is per-request, not global.** Several parallel 401s each fire their own `/auth/refresh`. Because refresh **rotates**, the second one presents a token the first already revoked and gets a 401, which sends the user to `/login`. Expect intermittent unexpected logouts on pages that fan out many requests at mount.

### 14.2 Route gating

```mermaid
flowchart TD
    NAV["User navigates"] --> KIND{"Route wrapper"}

    KIND -->|"PublicRoute"| PUB{"loading"}
    PUB -->|"yes"| PL1["PageLoader"]
    PUB -->|"no"| PUB2{"isAuthenticated"}
    PUB2 -->|"yes"| RD["Navigate to /dashboard"]
    PUB2 -->|"no"| SHOWPUB["render login / register / reset"]

    KIND -->|"ProtectedRoute"| PR{"loading"}
    PR -->|"yes"| PL2["PageLoader"]
    PR -->|"no"| PR2{"isAuthenticated"}
    PR2 -->|"no"| RL["Navigate to /login"]
    PR2 -->|"yes"| PR3{"allowedRoles set"}
    PR3 -->|"no"| SHOW["render page"]
    PR3 -->|"yes"| PR4{"user.role in allowedRoles"}
    PR4 -->|"no"| RD2["Navigate to /dashboard"]
    PR4 -->|"yes"| SHOW

    KIND -->|"no wrapper"| RAW["/auth/callback renders unguarded"]
```

`isAuthenticated` is `!!user`, **not** `!!token` ([useAuth.tsx:108](../../frontend/src/hooks/useAuth.tsx:108)). The user object only appears after `GET /auth/me` succeeds during `initAuth`, so a valid token with a failed `/auth/me` behaves as logged out. That is the safe default.

### 14.3 Role-gated routes

| Path | `allowedRoles` |
|---|---|
| `/ai/tool-registry` | `APP_ADMIN` |
| `/settings/billing` | `APP_ADMIN` |
| `/reports/analytics/app-admin` | `APP_ADMIN` |
| `/ai-config` | `APP_ADMIN`, `TENANT_ADMIN` |
| `/reports/analytics/app-user` | `APP_ADMIN`, `APP_USER` |
| `/reports/analytics/partner-admin` | `APP_ADMIN`, `PARTNER_ADMIN` |
| `/platform-management` | `APP_ADMIN`, `PARTNER_ADMIN`, `TENANT_ADMIN` |
| `/reports/analytics/tenant-admin` | `APP_ADMIN`, `PARTNER_ADMIN`, `TENANT_ADMIN` |
| `/admin/agent-kernel/*` (5 routes) | `APP_ADMIN`, `PARTNER_ADMIN`, `TENANT_ADMIN` |
| `/reports/analytics/partner-user` | `APP_ADMIN`, `PARTNER_ADMIN`, `PARTNER_USER` |
| everything else (~25 routes) | authentication only |

`MainLayout` separately hides nav items by role ([MainLayout.tsx:68-133](../../frontend/src/components/layout/MainLayout.tsx:68)). Note `/partner` — the partner dashboard — is `<ProtectedRoute>` with **no** `allowedRoles`, so any authenticated user can open it; it will simply get 403s from `/partner/*`. Frontend gating is cosmetic; the backend is the real boundary.

---

## 15. Security checklist and known gaps

Ordered roughly by severity. Everything here is observable in the code, not speculation.

### Critical

| # | Gap | Evidence |
|---|---|---|
| 1 | **`/api/v1/email/*` has no authentication whatsoever.** Read, create, delete, and validate another tenant's mailbox credentials by passing their `company_id` or `connection_id`. `validate` decrypts the stored app password and logs into the mailbox. | [email_router.py:94](../../backend/src/ai/email_router.py:94), [:159](../../backend/src/ai/email_router.py:159), [:179](../../backend/src/ai/email_router.py:179), [:204](../../backend/src/ai/email_router.py:204) |
| 2 | **Privilege escalation via `PATCH /users/{id}`.** `UserUpdate` includes `role`, and the handler applies it after only a company-match check. A `tenant_admin` can promote themselves to `app_admin`. | [user_router.py:48-72](../../backend/src/auth/user_router.py:48), [schemas.py:70](../../backend/src/auth/schemas.py:70) |
| 3 | **Production secrets are the committed defaults.** `SECRET_KEY=dev_secret_key_change_in_production`, `INTERNAL_TOKEN=change-me-in-production`, `JWT_SECRET=change-me-in-production` in `backend/.env`. Anyone with these mints tokens for any user and impersonates any tenant on `/internal/event`. | `backend/.env`, [gateway_config.py:32](../../backend/src/gateway/gateway_config.py:32) |
| 4 | **Any authenticated user can suspend their own company**, locking out its admins. No role check on `PATCH /companies/{id}`. | [company_router.py:118](../../backend/src/auth/company_router.py:118) |

### High

| # | Gap | Evidence |
|---|---|---|
| 5 | No logout endpoint. Refresh tokens survive sign-out for up to 7 days. | [auth.service.ts:30](../../frontend/src/services/auth.service.ts:30) — client-side only |
| 6 | Refresh tokens stored in **plaintext**. A read-only DB leak yields working sessions. | [models.py:50](../../backend/src/auth/models.py:50) |
| 7 | Refresh-token reuse detected but not acted on — no family revocation. | [service.py:186](../../backend/src/auth/service.py:186) |
| 8 | Access tokens cannot be revoked — no `jti`, no denylist. Valid until `exp`. | [security.py:18](../../backend/src/common/security.py:18) |
| 9 | Password reset is frontend-only; the two endpoints do not exist. | [PasswordReset.tsx:23](../../frontend/src/pages/auth/PasswordReset.tsx:23) vs. empty backend grep |
| 10 | No password policy server-side. `password: str`, no length or complexity rule. | [schemas.py:5](../../backend/src/auth/schemas.py:5) |
| 11 | No rate limiting on `/auth/login`. The gateway's `200/minute` limiter is per remote IP and global, not per account, and the backend has none. | [app.py:79](../../backend/src/gateway/app.py:79) |
| 12 | `is_active` and `is_verified` are never enforced at login. | [dependencies.py:16](../../backend/src/auth/dependencies.py:16) |
| 13 | OAuth `state` is the provider name, not a CSRF nonce; account linking is by unverified email. | [oauth.service.ts:17](../../frontend/src/services/oauth.service.ts:17), [service.py:221](../../backend/src/auth/service.py:221) |

### Medium

| # | Gap | Evidence |
|---|---|---|
| 14 | `INTERNAL_TOKEN` compared with `!=`, not a constant-time compare. | [auth_middleware.py:80](../../backend/src/gateway/auth_middleware.py:80) |
| 15 | `social_connections.oauth_metadata` holds each platform's `client_secret` **unencrypted** in JSONB, while the tokens beside it are AES-GCM encrypted. | [social_connection_service.py:174](../../backend/src/ai/social_connection_service.py:174) |
| 16 | `ENCRYPTION_MASTER_KEY` has a hard-coded 37-char default that is silently truncated to 32 bytes. | [config.py:9](../../backend/src/common/config.py:9), [security.py:40-44](../../backend/src/common/security.py:40) |
| 17 | `CompanySuspensionMiddleware` swallows all exceptions — fails open on a DB error. | [middleware.py:49](../../backend/src/common/middleware.py:49) |
| 18 | SSE stream takes the JWT as a **query parameter**, so it lands in access logs and browser history. | [ai/router.py:328](../../backend/src/ai/router.py:328), [dependencies.py:72](../../backend/src/auth/dependencies.py:72) |
| 19 | `print()` debug statements in the auth path leak user emails to stdout. | [dependencies.py:18](../../backend/src/auth/dependencies.py:18), `:34`, `:44`, `:48` |
| 20 | Gateway `JWT_SECRET` ≠ backend `SECRET_KEY`, so gateway JWT decode always fails silently. | `backend/.env` lines 6 and 18 |
| 21 | Tokens in `localStorage` — XSS-exposed. The `HttpOnly` refresh cookie already exists but is unused. | [api.client.ts:19](../../frontend/src/services/api.client.ts:19) |
| 22 | Concurrent 401s each trigger their own refresh; rotation makes all but the first fail and force a logout. | [api.client.ts:35](../../frontend/src/services/api.client.ts:35) |
| 23 | `/webhook/inbound` and `/stream/*` take `client_id` from an unverified query param despite the docstring promising signature validation. | [auth_middleware.py:86](../../backend/src/gateway/auth_middleware.py:86) |

### Low / hygiene

- No CSRF token anywhere, mitigated by the fact that auth is a header, not a cookie.
- `users.role` is a free-text column with no DB constraint and no Python enum.
- Five copy-pasted implementations of the "own + children" cascade that already disagree about `partner_user`.
- Two different functions named `_require_admin` with different definitions of admin.
- `GET /auth/admin-only` ([router.py:76](../../backend/src/auth/router.py:76)) is a leftover smoke-test endpoint that ships in production.
- `test_register_new_user` in [test_01_auth.py:15](../../backend/tests/e2e/test_01_auth.py:15) asserts `data["email"]`, but `/auth/register` returns a `Token`. The test is stale relative to the route.
- The verification email links to `/verify-email?token=`, a frontend route that does not exist and falls through to the `*` → `/dashboard` catch-all.

---

## Key files reference

| File | Lines | What it does |
|---|---|---|
| [backend/src/auth/models.py](../../backend/src/auth/models.py) | 55 | `Company`, `User`, `RefreshToken` ORM models — the whole identity schema |
| [backend/src/auth/schemas.py](../../backend/src/auth/schemas.py) | 85 | Pydantic request/response shapes for auth, companies, users, onboarding |
| [backend/src/auth/dependencies.py](../../backend/src/auth/dependencies.py) | 85 | `_authenticate_user`, `get_current_user`, `get_current_user_and_company`, `get_current_user_from_query`, `RoleChecker` |
| [backend/src/auth/service.py](../../backend/src/auth/service.py) | 307 | User creation, password check, refresh-token create/verify/rotate, OAuth upsert, email verification |
| [backend/src/auth/router.py](../../backend/src/auth/router.py) | 182 | `/auth/register`, `/login`, `/token`, `/me`, `/refresh`, `/oauth/{provider}`, `/verify-email`, `/admin-only` |
| [backend/src/auth/company_router.py](../../backend/src/auth/company_router.py) | 134 | Company CRUD, partner/tenant listing, suspension via PATCH |
| [backend/src/auth/user_router.py](../../backend/src/auth/user_router.py) | 76 | User listing, admin creation, update |
| [backend/src/auth/profile_router.py](../../backend/src/auth/profile_router.py) | 99 | Avatar and company-logo upload into the artifact store |
| [backend/src/auth/partner_router.py](../../backend/src/auth/partner_router.py) | 354 | Read-only partner console — tenant health scores and portfolio analytics |
| [backend/src/auth/onboarding_router.py](../../backend/src/auth/onboarding_router.py) | 171 | The 5-step wizard state machine on `companies.onboarding_*` |
| [backend/src/common/security.py](../../backend/src/common/security.py) | 66 | Argon2 hashing, JWT mint/decode, AES-256-GCM key encryption |
| [backend/src/common/middleware.py](../../backend/src/common/middleware.py) | 56 | `CompanySuspensionMiddleware` |
| [backend/src/common/config.py](../../backend/src/common/config.py) | 95 | `Settings` — `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `ENCRYPTION_MASTER_KEY` |
| [backend/src/gateway/auth_middleware.py](../../backend/src/gateway/auth_middleware.py) | 148 | `TenantContext`, `GatewayAuthMiddleware`, `require_internal`, `get_tenant` |
| [backend/src/gateway/internal_event.py](../../backend/src/gateway/internal_event.py) | 192 | `POST /internal/event` and the in-process `emit_internal_event` helper |
| [backend/src/gateway/gateway_config.py](../../backend/src/gateway/gateway_config.py) | 73 | `INTERNAL_TOKEN`, `JWT_SECRET`, CORS, rate limit |
| [backend/src/main.py](../../backend/src/main.py) | 192 | Router mounting and middleware registration order |
| [frontend/src/hooks/useAuth.tsx](../../frontend/src/hooks/useAuth.tsx) | 123 | `AuthProvider` — session bootstrap, login, register, logout, onboarding redirect |
| [frontend/src/services/api.client.ts](../../frontend/src/services/api.client.ts) | 71 | Axios instance with the bearer-token and 401-refresh interceptors |
| [frontend/src/services/auth.service.ts](../../frontend/src/services/auth.service.ts) | 49 | Thin wrappers over the auth endpoints; owns `localStorage` |
| [frontend/src/services/oauth.service.ts](../../frontend/src/services/oauth.service.ts) | 78 | Google/Microsoft authorize redirect + callback exchange |
| [frontend/src/router/index.tsx](../../frontend/src/router/index.tsx) | 603 | `ProtectedRoute`, `PublicRoute`, and every route's `allowedRoles` |
| [frontend/src/pages/auth/PasswordReset.tsx](../../frontend/src/pages/auth/PasswordReset.tsx) | 212 | Forgot/reset pages calling endpoints that do not exist |
| [frontend/src/pages/OnboardingWizard.tsx](../../frontend/src/pages/OnboardingWizard.tsx) | 267 | The 5-step wizard UI |
| [backend/tests/e2e/test_01_auth.py](../../backend/tests/e2e/test_01_auth.py) | — | E2E coverage for register, login, refresh, me, invalid tokens |
| [backend/tests/e2e/test_02_rbac_companies.py](../../backend/tests/e2e/test_02_rbac_companies.py) | — | E2E coverage for role fencing and suspension |

---

## Gotchas and things that surprise newcomers

- **The role is not in the JWT.** Every request re-reads the user row. Role changes apply instantly, but there is one guaranteed `SELECT users` per authenticated request, plus another from `CompanySuspensionMiddleware`.
- **`sub` is the email, not the user UUID.** Change a user's email and every outstanding token for them becomes invalid.
- **`RoleChecker` has no hierarchy.** `app_admin` is locked out of any endpoint whose list forgets to name it. Always include it explicitly.
- **`app_admin` bypasses the tenant filter by *skipping* the `WHERE`, not by widening it.** Read `if user_role != "app_admin"` as "this is the isolation boundary".
- **Nothing scopes queries for you.** No RLS, no ORM mixin, no middleware. A missing `WHERE company_id` is a cross-tenant leak that no test will catch.
- **Templates have `company_id = NULL` and are visible to every tenant.** Do not put customer data in a template.
- **Self-registration makes you `tenant_admin`, but the DB column default is `tenant_user`.** The two disagree; the service wins.
- **The refresh cookie is set but never read.** Refresh always comes from the JSON body and `localStorage`.
- **There is no logout endpoint.** Signing out only clears `localStorage`.
- **Two `_require_admin` functions exist with different meanings.** `ai/api/admin.py` counts `tenant_admin` as admin; `billing/cron_router.py` does not.
- **The OAuth buttons on the login page have no `onClick`.** The backend flow works; the UI never triggers it.
- **`/api/v1/email/*` is completely unauthenticated.** Do not copy that router as a template — copy `social_router.py` instead.
- **The gateway is not a security boundary for REST.** Its own docstring says the backend enforces auth. Only `/internal/event` is blocked at the gateway.
- **`SECRET_KEY` and `JWT_SECRET` are different variables** that must hold the same value for gateway JWT parsing to work. Today they do not.
- **Onboarding is enforced only at login, only for tenant roles.** Deep-linking to `/dashboard` skips it.

---

## Where to go next

- [03 — Data model](03-data-model.md) — the full table set, including everything that carries a `company_id`.
- [13 — Gateway and real-time](13-gateway-and-realtime.md) — the five gateway interfaces and how webhooks and WebSockets derive tenancy.
- [14 — Billing and credits](14-billing-and-credits.md) — `CreditWallet` provisioning at company creation, and how suspension interacts with balance.
- [15 — Governance and HITL](15-governance-and-hitl.md) — approval gates layered on top of RBAC.
- [16 — Frontend architecture](16-frontend.md) — the wider routing, layout, and service-layer picture.
- [17 — API reference](17-api-reference.md) — the complete endpoint list with its guards.
- [19 — Testing](19-testing.md) — where the `test_01_auth` / `test_02_rbac_companies` E2E suites fit.
