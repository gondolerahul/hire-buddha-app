"""
Unified Phone Number Router — single API surface for number inventory,
claiming, agent assignment, and provider sync.

Replaces both the old phone_pool_router.py and phone_number_router.py.

Endpoints:
  - POST   /phone-numbers              — (app_admin) Add number to inventory
  - POST   /phone-numbers/bulk         — (app_admin) Bulk add numbers
  - POST   /phone-numbers/sync         — (app_admin) Sync from Twilio / Tata accounts
  - GET    /phone-numbers              — List numbers (role-aware)
  - GET    /phone-numbers/{id}         — Get single number
  - PATCH  /phone-numbers/{id}         — Update number (name, agent, status, etc.)
  - POST   /phone-numbers/{id}/claim   — (tenant_admin) Claim an available number
  - POST   /phone-numbers/{id}/release — (tenant_admin) Release back to pool
  - POST   /phone-numbers/{id}/assign  — Assign agent to a claimed number
  - DELETE /phone-numbers/{id}         — (app_admin) Remove from inventory
"""

import logging
import httpx
from datetime import datetime
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_

from src.common.database import get_db
from src.auth.models import User
from src.auth.dependencies import get_current_user, RoleChecker
from src.voice.phone_pool_models import PhoneNumber
from src.config.models import IntegrationRegistry
from src.common.security import decrypt_api_key
from src.ai.models import HierarchicalEntity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/phone-numbers", tags=["Phone Numbers"])

admin_only = RoleChecker(["app_admin"])


# ── Schemas ──────────────────────────────────────────────────────────────

class PhoneNumberCreate(BaseModel):
    phone_number: str
    provider: str  # twilio | tata_tele
    country_code: str = "+91"
    label: Optional[str] = None
    monthly_cost_usd: Optional[float] = None
    provider_sid: Optional[str] = None
    capabilities: Optional[dict] = None
    notes: Optional[str] = None

    # Assignment fields (optional — skip to add as 'available')
    company_id: Optional[UUID] = None  # app_admin can assign to any company
    agent_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_metadata: Optional[dict] = None


class PhoneNumberBulk(BaseModel):
    numbers: List[PhoneNumberCreate]


class PhoneNumberUpdate(BaseModel):
    phone_number: Optional[str] = None
    provider: Optional[str] = None
    country_code: Optional[str] = None
    company_id: Optional[UUID] = None  # app_admin can reassign to different company
    customer_name: Optional[str] = None
    agent_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    label: Optional[str] = None
    notes: Optional[str] = None
    customer_metadata: Optional[dict] = None


class SyncRequest(BaseModel):
    provider: Optional[str] = None  # sync all or specific provider


class AssignRequest(BaseModel):
    agent_id: UUID
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_metadata: Optional[dict] = None


class ClaimRequest(BaseModel):
    target_company_id: Optional[UUID] = None  # app_admin can claim for any company


# ── CRUD ─────────────────────────────────────────────────────────────────

@router.post("")
async def create_phone_number(
    data: PhoneNumberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a phone number to the inventory.
    If agent_id is provided, the number is created as 'assigned' directly.
    Otherwise it is added as 'available'.
    """
    # Check for duplicate
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.phone_number == data.phone_number)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Phone number {data.phone_number} already exists")

    # Determine initial status
    if data.agent_id:
        # Verify agent exists
        agent_result = await db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == data.agent_id)
        )
        if not agent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Agent not found")

        status = "assigned"
        assigned_at = datetime.utcnow()
        # app_admin can assign to any company; others default to their own
        if data.company_id and current_user.role == "app_admin":
            company_id = data.company_id
        else:
            company_id = current_user.company_id
    else:
        status = "available"
        assigned_at = None
        # If app_admin provides company_id even without agent, set as 'claimed'
        if data.company_id and current_user.role == "app_admin":
            company_id = data.company_id
            status = "claimed"
        else:
            company_id = None

    entry = PhoneNumber(
        phone_number=data.phone_number,
        provider=data.provider,
        country_code=data.country_code,
        status=status,
        label=data.label,
        monthly_cost_usd=data.monthly_cost_usd,
        provider_sid=data.provider_sid,
        capabilities=data.capabilities,
        notes=data.notes,
        added_by_user_id=current_user.id,
        company_id=company_id,
        agent_id=data.agent_id,
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_metadata=data.customer_metadata,
        assigned_at=assigned_at,
        claimed_at=datetime.utcnow() if data.agent_id else None,
        is_active=True,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _to_response(entry)


@router.post("/bulk")
async def bulk_add(
    body: PhoneNumberBulk,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Bulk add phone numbers to the inventory (app_admin only)."""
    added, skipped = [], []
    for item in body.numbers:
        existing = await db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == item.phone_number)
        )
        if existing.scalar_one_or_none():
            skipped.append(item.phone_number)
            continue
        entry = PhoneNumber(
            phone_number=item.phone_number,
            provider=item.provider,
            country_code=item.country_code,
            label=item.label,
            monthly_cost_usd=item.monthly_cost_usd,
            provider_sid=item.provider_sid,
            capabilities=item.capabilities,
            notes=item.notes,
            added_by_user_id=current_user.id,
            status="available",
        )
        db.add(entry)
        added.append(item.phone_number)
    await db.commit()
    return {"added": len(added), "skipped": len(skipped), "added_numbers": added}


# ── Sync from Providers ──────────────────────────────────────────────────

@router.post("/sync")
async def sync_numbers(
    body: SyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Sync phone numbers from configured Twilio / Tata Tele accounts."""
    results = {}

    # Fetch integrations
    integrations_q = select(IntegrationRegistry).where(
        IntegrationRegistry.provider_name.in_(["twilio", "tata_tele"])
    )
    rows = (await db.execute(integrations_q)).scalars().all()
    providers_found = {r.provider_name for r in rows}

    for row in rows:
        if body.provider and row.provider_name != body.provider:
            continue
        try:
            meta = row.service_metadata or {}
            if row.provider_name == "twilio":
                account_sid = meta.get("account_sid", "")
                auth_token = decrypt_api_key(row.encrypted_api_key) if row.encrypted_api_key else meta.get("auth_token", "")
                results["twilio"] = await _sync_twilio(db, account_sid, auth_token, current_user.id)
            elif row.provider_name == "tata_tele":
                api_key = decrypt_api_key(row.encrypted_api_key) if row.encrypted_api_key else meta.get("api_key", "")
                results["tata_tele"] = await _sync_tata_tele(db, api_key, current_user.id, meta)
        except Exception as e:
            logger.error(f"Sync error for {row.provider_name}: {e}", exc_info=True)
            results[row.provider_name] = {"error": str(e)}

    if body.provider and body.provider not in providers_found:
        results[body.provider] = {"error": f"No {body.provider} integration configured in Integration Registry."}

    return results


async def _sync_twilio(
    db: AsyncSession, account_sid: str, auth_token: str, added_by_user_id
) -> dict:
    """
    Fetch all incoming phone numbers from Twilio account and upsert.
    """
    added, skipped = [], []
    page_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
        f"/IncomingPhoneNumbers.json?PageSize=200"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        while page_url:
            resp = await client.get(page_url, auth=(account_sid, auth_token))
            if resp.status_code != 200:
                raise Exception(f"Twilio API error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()

            for num in data.get("incoming_phone_numbers", []):
                phone = num.get("phone_number", "").lstrip("+")
                if not phone:
                    continue

                existing = await db.execute(
                    select(PhoneNumber).where(PhoneNumber.phone_number == phone)
                )
                if existing.scalar_one_or_none():
                    skipped.append(phone)
                    continue

                # Determine country code from E.164 number
                raw = num.get("phone_number", "")
                country_code = "+1"
                if raw.startswith("+91"):
                    country_code = "+91"
                elif raw.startswith("+44"):
                    country_code = "+44"
                elif raw.startswith("+"):
                    country_code = raw[:3] if len(raw) > 10 else raw[:2]

                capabilities = num.get("capabilities", {})
                entry = PhoneNumber(
                    phone_number=phone,
                    provider="twilio",
                    country_code=country_code,
                    label=num.get("friendly_name"),
                    provider_sid=num.get("sid"),
                    capabilities={
                        "voice": capabilities.get("voice", False),
                        "sms": capabilities.get("sms", False),
                        "mms": capabilities.get("mms", False),
                    },
                    added_by_user_id=added_by_user_id,
                    status="available",
                )
                db.add(entry)
                added.append(phone)

            next_uri = data.get("next_page_uri")
            page_url = f"https://api.twilio.com{next_uri}" if next_uri else None

    await db.commit()
    return {"added": len(added), "skipped": len(skipped), "added_numbers": added}


async def _sync_tata_tele(db: AsyncSession, api_key: str, added_by_user_id, service_metadata: dict = None) -> dict:
    """
    Fetch DID numbers from Tata Tele Smartflo account and upsert.

    Smartflo API: GET https://api-smartflo.tatateleservices.com/v1/number/my_numbers
    Auth: Authorization header with Bearer token.
    """
    added, skipped = [], []
    base_url = (service_metadata or {}).get("api_url", "https://api-smartflo.tatateleservices.com")

    logger.info(f"Tata Tele sync: using token={api_key[:8]}…{api_key[-4:]}, base_url={base_url}")

    # Try multiple endpoints
    endpoints = [
        f"{base_url}/v1/number/my_numbers",
        f"{base_url}/v1/my_number/my_numbers",
        f"{base_url}/v1/numbers",
        f"{base_url}/v1/did/list",
    ]

    auth_variants = [
        {"Authorization": f"Bearer {api_key}", "accept": "application/json"},
        {"Authorization": api_key, "Content-Type": "application/json", "Accept": "application/json"},
    ]

    numbers_data = []
    api_errors = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for url in endpoints:
            for headers in auth_variants:
                try:
                    resp = await client.get(url, headers=headers)
                    auth_label = 'Bearer' if 'Bearer' in headers.get('Authorization', '') else 'raw'
                    logger.info(f"Tata Tele {url} (auth={auth_label}) → {resp.status_code}")
                    if resp.status_code == 200:
                        payload = resp.json()
                        if isinstance(payload, list):
                            numbers_data = payload
                        elif isinstance(payload, dict):
                            numbers_data = (
                                payload.get("numbers")
                                or payload.get("data")
                                or payload.get("did_numbers")
                                or payload.get("results")
                                or payload.get("items")
                                or []
                            )
                        if numbers_data:
                            break
                    else:
                        error_detail = resp.text[:200]
                        api_errors.append(f"{url} ({auth_label}): HTTP {resp.status_code} — {error_detail}")
                        logger.warning(f"Tata Tele {url} returned {resp.status_code}: {error_detail}")
                except Exception as e:
                    api_errors.append(f"{url}: {e}")
                    logger.warning(f"Tata Tele {url} failed: {e}")
            if numbers_data:
                break

    logger.info(f"Tata Tele sync: found {len(numbers_data)} numbers from API")

    for num in numbers_data:
        if isinstance(num, str):
            phone = num.lstrip("+")
            label = None
            did_sid = None
        elif isinstance(num, dict):
            phone = (
                num.get("number") or num.get("did_number")
                or num.get("phone") or num.get("phone_number") or ""
            )
            if isinstance(phone, (int, float)):
                phone = str(int(phone))
            phone = str(phone).lstrip("+")
            label = num.get("name") or num.get("label") or num.get("description") or num.get("friendly_name")
            did_sid = str(num.get("id") or num.get("did_id") or num.get("number_id") or "")
        else:
            continue

        if not phone:
            continue

        existing = await db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == phone)
        )
        if existing.scalar_one_or_none():
            skipped.append(phone)
            continue

        entry = PhoneNumber(
            phone_number=phone,
            provider="tata_tele",
            country_code="+91",
            label=label,
            provider_sid=did_sid or None,
            capabilities={"voice": True, "sms": False},
            added_by_user_id=added_by_user_id,
            status="available",
        )
        db.add(entry)
        added.append(phone)

    await db.commit()

    result = {"added": len(added), "skipped": len(skipped), "added_numbers": added}

    if not numbers_data and api_errors:
        result["warning"] = (
            f"Could not fetch numbers from Smartflo API ({len(api_errors)} attempts failed)."
        )
        result["api_errors"] = api_errors[:3]
        logger.warning(f"Tata Tele sync: API calls failed — {api_errors[0]}")

    return result


# ── List / Get ───────────────────────────────────────────────────────────

@router.get("")
async def list_phone_numbers(
    status: Optional[str] = None,
    provider: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List phone numbers.

    - app_admin: sees all numbers
    - tenant_admin: sees available numbers + their own claimed/assigned numbers
    """
    query = select(PhoneNumber)

    if current_user.role not in ("app_admin",):
        query = query.where(
            or_(
                PhoneNumber.status == "available",
                PhoneNumber.company_id == current_user.company_id,
            )
        )

    if status:
        query = query.where(PhoneNumber.status == status)
    if provider:
        query = query.where(PhoneNumber.provider == provider)
    if is_active is not None:
        query = query.where(PhoneNumber.is_active == is_active)

    query = query.order_by(PhoneNumber.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    numbers = result.scalars().all()

    # Resolve agent names
    agent_ids = [n.agent_id for n in numbers if n.agent_id]
    agents = {}
    if agent_ids:
        agents_result = await db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id.in_(agent_ids))
        )
        agents = {a.id: a.name for a in agents_result.scalars().all()}

    # Resolve company names
    company_ids = [n.company_id for n in numbers if n.company_id]
    company_names = {}
    if company_ids:
        from src.auth.models import Company as CompanyModel
        companies_result = await db.execute(
            select(CompanyModel).where(CompanyModel.id.in_(company_ids))
        )
        company_names = {c.id: c.name for c in companies_result.scalars().all()}

    return {
        "total": len(numbers),
        "phone_numbers": [_to_response(n, agents, company_names) for n in numbers],
    }


@router.get("/{number_id}")
async def get_phone_number(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single phone number."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Phone number not found")

    # Non-admins can only see their own
    if current_user.role != "app_admin" and entry.company_id != current_user.company_id and entry.status != "available":
        raise HTTPException(status_code=403, detail="Not authorized")

    agents = {}
    if entry.agent_id:
        agent_result = await db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == entry.agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if agent:
            agents[agent.id] = agent.name

    return _to_response(entry, agents)


@router.patch("/{number_id}")
async def update_phone_number(
    number_id: UUID,
    data: PhoneNumberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update phone number details."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Phone number not found")

    # Verify ownership
    if current_user.role != "app_admin" and entry.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if data.phone_number is not None:
        # Check for duplicate
        dup_result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.phone_number == data.phone_number,
                PhoneNumber.id != number_id,
            )
        )
        if dup_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Phone number {data.phone_number} already exists")
        entry.phone_number = data.phone_number
    if data.provider is not None:
        entry.provider = data.provider
    if data.country_code is not None:
        entry.country_code = data.country_code
    if data.customer_name is not None:
        entry.customer_name = data.customer_name
    if data.label is not None:
        entry.label = data.label
    if data.notes is not None:
        entry.notes = data.notes
    if data.customer_metadata is not None:
        entry.customer_metadata = data.customer_metadata
    if data.is_active is not None:
        entry.is_active = data.is_active
    if data.company_id is not None and current_user.role == "app_admin":
        entry.company_id = data.company_id

    if data.agent_id is not None:
        # Verify agent exists — app_admin can assign agents from any company
        if current_user.role == "app_admin":
            agent_result = await db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.id == data.agent_id
                )
            )
        else:
            agent_result = await db.execute(
                select(HierarchicalEntity).where(
                    and_(
                        HierarchicalEntity.id == data.agent_id,
                        HierarchicalEntity.company_id == current_user.company_id,
                    )
                )
            )
        if not agent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Agent not found")
        entry.agent_id = data.agent_id
        if entry.status == "claimed":
            entry.status = "assigned"
            entry.assigned_at = datetime.utcnow()

    if data.customer_id is not None:
        entry.customer_id = data.customer_id

    entry.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(entry)
    return _to_response(entry)


# ── Claim / Release / Assign ────────────────────────────────────────────

@router.post("/{number_id}/claim")
async def claim_number(
    number_id: UUID,
    body: Optional[ClaimRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Claim an available number. App admin can specify target_company_id."""
    if current_user.role not in ("tenant_admin", "partner_admin", "app_admin"):
        raise HTTPException(status_code=403, detail="Only admins can claim phone numbers")

    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found")
    if entry.status != "available":
        raise HTTPException(status_code=400, detail=f"Number is not available (current status: {entry.status})")

    # Determine which company to claim for
    target_company_id = None
    if body and body.target_company_id and current_user.role == "app_admin":
        # Validate the target company exists
        from src.auth.models import Company as CompanyModel
        company_result = await db.execute(
            select(CompanyModel).where(CompanyModel.id == body.target_company_id)
        )
        if not company_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Target company not found")
        target_company_id = body.target_company_id

    entry.status = "claimed"
    entry.company_id = target_company_id or current_user.company_id
    entry.claimed_by_user_id = current_user.id
    entry.claimed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(entry)
    return {"status": "claimed", "number": _to_response(entry)}


@router.post("/{number_id}/release")
async def release_number(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release a claimed/assigned number back to the pool."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found")

    if current_user.role != "app_admin" and entry.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized to release this number")

    if entry.status not in ("claimed", "assigned"):
        raise HTTPException(status_code=400, detail="Number is not currently claimed or assigned")

    entry.status = "available"
    entry.company_id = None
    entry.claimed_by_user_id = None
    entry.claimed_at = None
    entry.agent_id = None
    entry.customer_id = None
    entry.customer_name = None
    entry.customer_metadata = None
    entry.assigned_at = None

    await db.commit()
    await db.refresh(entry)
    return {"status": "released", "number": _to_response(entry)}


@router.post("/{number_id}/assign")
async def assign_agent(
    number_id: UUID,
    data: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign an agent to a claimed number (transitions to 'assigned')."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found")

    if current_user.role != "app_admin" and entry.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if entry.status not in ("claimed", "assigned"):
        raise HTTPException(status_code=400, detail=f"Number must be claimed first (current status: {entry.status})")

    # Verify agent exists and belongs to the same company
    agent_result = await db.execute(
        select(HierarchicalEntity).where(HierarchicalEntity.id == data.agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Company matching — app_admin can assign any agent to any number
    if current_user.role == "app_admin":
        pass  # No restriction
    elif current_user.role in ("partner_admin", "partner_user"):
        # Partner admins can assign agents from their own company or child tenants
        from src.auth.models import Company as CompanyModel
        child_result = await db.execute(
            select(CompanyModel.id).where(CompanyModel.parent_id == current_user.company_id)
        )
        allowed_companies = {current_user.company_id} | {r[0] for r in child_result.fetchall()}
        if agent.company_id not in allowed_companies:
            raise HTTPException(
                status_code=403,
                detail="Agent must belong to your company or one of your tenants"
            )
    else:
        # Regular users: agent must belong to the same company as the phone number
        if entry.company_id and agent.company_id != entry.company_id:
            raise HTTPException(
                status_code=403,
                detail="Agent must belong to the same company as the phone number"
            )

    # Agent must be ACTIVE
    if agent.status != "ACTIVE":
        raise HTTPException(
            status_code=400,
            detail=f"Only ACTIVE agents can be assigned to phone numbers (agent status: {agent.status})"
        )

    # Agent must have voice configuration (check both direct and nested persona format)
    identity = agent.identity
    has_voice = False
    if identity and isinstance(identity, dict):
        if identity.get("voice"):
            has_voice = True
        persona = identity.get("persona")
        if isinstance(persona, dict) and persona.get("voice"):
            has_voice = True
    if not has_voice:
        raise HTTPException(
            status_code=400,
            detail="Only voice-enabled agents can be assigned to phone numbers. "
                   "Configure a voice identity in the agent's persona settings."
        )

    entry.status = "assigned"
    entry.agent_id = data.agent_id
    entry.customer_id = data.customer_id
    entry.customer_name = data.customer_name
    entry.customer_metadata = data.customer_metadata
    entry.assigned_at = datetime.utcnow()

    await db.commit()
    await db.refresh(entry)

    return {"status": "assigned", "number": _to_response(entry, {agent.id: agent.name})}


# ── Delete ───────────────────────────────────────────────────────────────

@router.delete("/{number_id}")
async def delete_phone_number(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a phone number from the inventory."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Phone number not found")

    # Only app_admin can delete any number; tenants can delete their own
    if current_user.role != "app_admin" and entry.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.delete(entry)
    await db.commit()
    return {"message": "Phone number deleted successfully"}


# ── Helpers ──────────────────────────────────────────────────────────────

def _to_response(entry: PhoneNumber, agents: dict = None, companies: dict = None) -> dict:
    agents = agents or {}
    companies = companies or {}
    return {
        "id": str(entry.id),
        "phone_number": entry.phone_number,
        "provider": entry.provider,
        "country_code": entry.country_code,
        "status": entry.status,
        "label": entry.label,
        "monthly_cost_usd": float(entry.monthly_cost_usd) if entry.monthly_cost_usd else None,
        "provider_sid": entry.provider_sid,
        "capabilities": entry.capabilities,
        "notes": entry.notes,
        "is_active": entry.is_active,
        # Ownership
        "company_id": str(entry.company_id) if entry.company_id else None,
        "company_name": companies.get(entry.company_id, None) if entry.company_id else None,
        "claimed_at": entry.claimed_at.isoformat() if entry.claimed_at else None,
        # Agent assignment
        "agent_id": str(entry.agent_id) if entry.agent_id else None,
        "agent_name": agents.get(entry.agent_id, None) if entry.agent_id else None,
        "customer_id": str(entry.customer_id) if entry.customer_id else None,
        "customer_name": entry.customer_name,
        "customer_metadata": entry.customer_metadata,
        "assigned_at": entry.assigned_at.isoformat() if entry.assigned_at else None,
        # Timestamps
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
