"""
Phone Pool Router — CRUD and claim/release for the centralized phone number pool.

Endpoints:
  - POST   /phone-pool            — (app_admin) Add number to pool
  - POST   /phone-pool/bulk       — (app_admin) Bulk add numbers
  - POST   /phone-pool/sync       — (app_admin) Sync numbers from Twilio/Tata accounts
  - GET    /phone-pool             — List numbers (tenant sees available + own; admin sees all)
  - POST   /phone-pool/{id}/claim  — (tenant_admin) Claim an available number
  - POST   /phone-pool/{id}/release — (tenant_admin) Release a claimed number
  - DELETE /phone-pool/{id}        — (app_admin) Remove from pool
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
from sqlalchemy import or_

from src.common.database import get_db
from src.auth.models import User
from src.auth.dependencies import get_current_user, RoleChecker
from src.voice.phone_pool_models import PhoneNumber
from src.config.models import IntegrationRegistry
from src.common.security import decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/phone-pool", tags=["Phone Number Pool"])

admin_only = RoleChecker(["app_admin"])


# --- Schemas ---

class PhonePoolCreate(BaseModel):
    phone_number: str
    provider: str  # twilio | tata_tele
    country_code: str = "+91"
    label: Optional[str] = None
    monthly_cost_usd: Optional[float] = None
    provider_sid: Optional[str] = None
    capabilities: Optional[dict] = None
    notes: Optional[str] = None


class PhonePoolBulkCreate(BaseModel):
    numbers: List[PhonePoolCreate]


class PhonePoolResponse(BaseModel):
    id: str
    phone_number: str
    provider: str
    country_code: str
    status: str
    label: Optional[str] = None
    monthly_cost_usd: Optional[float] = None
    provider_sid: Optional[str] = None
    capabilities: Optional[dict] = None
    claimed_by_company_id: Optional[str] = None
    claimed_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


# --- Endpoints ---

@router.post("", response_model=PhonePoolResponse)
async def add_number_to_pool(
    body: PhonePoolCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Add a single phone number to the pool (app_admin only)."""
    # Check for duplicate
    existing = await db.execute(
        select(PhoneNumber).where(PhoneNumber.phone_number == body.phone_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Number {body.phone_number} already exists in pool")

    entry = PhoneNumber(
        phone_number=body.phone_number,
        provider=body.provider,
        country_code=body.country_code,
        label=body.label,
        monthly_cost_usd=body.monthly_cost_usd,
        provider_sid=body.provider_sid,
        capabilities=body.capabilities or {"voice": True, "sms": False},
        notes=body.notes,
        added_by_user_id=current_user.id,
        status="available",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return _to_response(entry)


@router.post("/bulk")
async def bulk_add_numbers(
    body: PhonePoolBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Bulk-add phone numbers to the pool (app_admin only)."""
    added = []
    skipped = []

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
            capabilities=item.capabilities or {"voice": True, "sms": False},
            notes=item.notes,
            added_by_user_id=current_user.id,
            status="available",
        )
        db.add(entry)
        added.append(item.phone_number)

    await db.commit()
    return {
        "added": len(added),
        "skipped": len(skipped),
        "added_numbers": added,
        "skipped_numbers": skipped,
    }


class SyncRequest(BaseModel):
    provider: Optional[str] = None  # 'twilio', 'tata_tele', or None for both


@router.post("/sync")
async def sync_numbers_from_providers(
    body: SyncRequest = SyncRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """
    Sync phone numbers from Twilio and/or Tata Tele accounts into the pool.

    Fetches all numbers from the provider account(s) using credentials
    stored in the IntegrationRegistry and upserts them into the pool.
    """
    results = {"twilio": None, "tata_tele": None}
    providers = [body.provider] if body.provider else ["twilio", "tata_tele"]

    # Helper: find integration entry with APP-company fallback
    async def _find_integration(provider_name: str):
        # 1. Try user's company
        res = await db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == current_user.company_id,
                IntegrationRegistry.provider_name == provider_name,
                IntegrationRegistry.status == "active",
            )
        )
        entry = res.scalars().first()
        if entry:
            return entry
        # 2. APP company fallback
        from src.auth.models import Company
        app_res = await db.execute(select(Company.id).where(Company.type == "APP").limit(1))
        app_id = app_res.scalar_one_or_none()
        if app_id and app_id != current_user.company_id:
            res = await db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == app_id,
                    IntegrationRegistry.provider_name == provider_name,
                    IntegrationRegistry.status == "active",
                )
            )
            return res.scalars().first()
        return None

    # --- Twilio sync ---
    if "twilio" in providers:
        entry = await _find_integration("twilio")
        if entry and entry.encrypted_api_key:
            auth_token = decrypt_api_key(entry.encrypted_api_key)
            account_sid = (entry.service_metadata or {}).get("account_sid")
            if account_sid and auth_token:
                try:
                    results["twilio"] = await _sync_twilio(
                        db, account_sid, auth_token, current_user.id
                    )
                except Exception as e:
                    logger.error(f"Twilio sync error: {e}", exc_info=True)
                    results["twilio"] = {"error": str(e)}
            else:
                results["twilio"] = {"error": "account_sid missing in service_metadata"}
        else:
            results["twilio"] = {"error": "No active twilio integration found"}

    # --- Tata Tele sync ---
    if "tata_tele" in providers:
        entry = await _find_integration("tata_tele")
        if entry:
            # The Smartflo API token is stored in service_metadata.api_key
            # (encrypted_api_key holds a different credential used for click-to-call)
            api_key = None
            metadata = entry.service_metadata or {}
            if metadata.get("api_key"):
                api_key = metadata["api_key"]
            elif entry.encrypted_api_key:
                api_key = decrypt_api_key(entry.encrypted_api_key)

            if api_key:
                try:
                    results["tata_tele"] = await _sync_tata_tele(
                        db, api_key, current_user.id,
                        service_metadata=metadata
                    )
                except Exception as e:
                    logger.error(f"Tata Tele sync error: {e}", exc_info=True)
                    results["tata_tele"] = {"error": str(e)}
            else:
                results["tata_tele"] = {"error": "API key could not be resolved"}
        else:
            results["tata_tele"] = {"error": "No active tata_tele integration found"}

    return results


async def _sync_twilio(
    db: AsyncSession, account_sid: str, auth_token: str, added_by_user_id
) -> dict:
    """
    Fetch all incoming phone numbers from Twilio account and upsert into pool.

    Twilio API: GET /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json
    Auth: HTTP Basic (account_sid, auth_token)
    Response: { incoming_phone_numbers: [...], next_page_uri: ... }

    Also cross-checks customer_phone_numbers table so numbers already
    assigned to agents are imported into the pool as 'claimed'.
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
                country_code = "+1"  # default
                if raw.startswith("+91"):
                    country_code = "+91"
                elif raw.startswith("+44"):
                    country_code = "+44"
                elif raw.startswith("+"):
                    country_code = raw[:3] if len(raw) > 10 else raw[:2]

                # Check if already assigned in customer_phone_numbers
                assigned_check = await db.execute(
                    select(PhoneNumber).where(
                        PhoneNumber.phone_number.in_([phone, f"+{phone}", raw]),
                        PhoneNumber.is_active == True,
                    )
                )
                assignment = assigned_check.scalar_one_or_none()

                capabilities = num.get("capabilities", {})

                if assignment:
                    # Import as claimed
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
                        status="claimed",
                        claimed_by_company_id=assignment.company_id,
                        claimed_at=assignment.assigned_at,
                    )
                    db.add(entry)
                    skipped.append(phone)
                else:
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

            # Handle pagination
            next_uri = data.get("next_page_uri")
            page_url = f"https://api.twilio.com{next_uri}" if next_uri else None

    await db.commit()
    return {"added": len(added), "skipped": len(skipped), "added_numbers": added}


async def _sync_tata_tele(db: AsyncSession, api_key: str, added_by_user_id, service_metadata: dict = None) -> dict:
    """
    Fetch DID numbers from Tata Tele Smartflo account and upsert into pool.

    Smartflo API: GET https://api-smartflo.tatateleservices.com/v1/number/my_numbers
    Auth: The Smartflo API accepts the token in the Authorization header.
          We try multiple formats for compatibility.

    Also cross-checks customer_phone_numbers table so numbers already
    assigned to agents are imported into the pool as 'claimed'.
    """

    added, skipped, imported_from_assignments = [], [], []
    base_url = (service_metadata or {}).get("api_url", "https://api-smartflo.tatateleservices.com")

    logger.info(f"Tata Tele sync: using token={api_key[:8]}…{api_key[-4:]}, base_url={base_url}")

    # Try multiple endpoints — Smartflo docs reference /v1/number/my_numbers
    endpoints = [
        f"{base_url}/v1/number/my_numbers",
        f"{base_url}/v1/my_number/my_numbers",
        f"{base_url}/v1/numbers",
        f"{base_url}/v1/did/list",
    ]

    # Try multiple auth header formats
    auth_variants = [
        {"Authorization": f"Bearer {api_key}", "accept": "application/json"},
        {"Authorization": api_key, "Content-Type": "application/json", "Accept": "application/json"},
    ]

    numbers_data = []
    api_errors = []  # Track errors from all attempts
    async with httpx.AsyncClient(timeout=30.0) as client:
        for url in endpoints:
            for headers in auth_variants:
                try:
                    resp = await client.get(url, headers=headers)
                    auth_label = 'Bearer' if 'Bearer' in headers.get('Authorization', '') else 'raw'
                    logger.info(
                        f"Tata Tele {url} (auth={auth_label}) "
                        f"→ {resp.status_code}"
                    )
                    if resp.status_code == 200:
                        payload = resp.json()
                        logger.info(f"Tata Tele response payload type={type(payload).__name__}, keys={list(payload.keys()) if isinstance(payload, dict) else 'N/A'}")
                        # Handle various response shapes
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

    # --- Step 1: Import numbers already assigned in customer_phone_numbers ---
    # These are numbers assigned to agents (on the Phone Numbers screen) but
    # not yet present in the phone_number_pool table.
    assigned_result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.provider == "tata_tele",
            PhoneNumber.is_active == True,
        )
    )
    assigned_numbers = assigned_result.scalars().all()

    for assignment in assigned_numbers:
        # Normalise phone: strip '+' for consistent pool storage
        phone = assignment.phone_number.lstrip("+")

        # Check if already in pool
        existing = await db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == phone)
        )
        if existing.scalar_one_or_none():
            continue  # already in pool, nothing to do

        # Import as a claimed entry in the pool
        entry = PhoneNumber(
            phone_number=phone,
            provider="tata_tele",
            country_code="+91",
            label=assignment.customer_name or None,
            capabilities={"voice": True, "sms": False},
            added_by_user_id=added_by_user_id,
            status="claimed",
            claimed_by_company_id=assignment.company_id,
            claimed_at=assignment.assigned_at,
        )
        db.add(entry)
        imported_from_assignments.append(phone)
        logger.info(f"Tata Tele sync: imported assigned number {phone} into pool as 'claimed'")

    # --- Step 2: If API returned numbers, upsert into pool ---
    for num in numbers_data:
        # Normalise: the API may return phone as string or inside a dict
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

        # Check phone_number_pool (including numbers just imported above)
        existing = await db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == phone)
        )
        if existing.scalar_one_or_none():
            skipped.append(phone)
            continue

        # Also check customer_phone_numbers with both formats (with and without '+')
        assigned_check = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.phone_number.in_([phone, f"+{phone}", f"+91{phone}"]),
                PhoneNumber.is_active == True,
            )
        )
        assignment = assigned_check.scalar_one_or_none()

        if assignment:
            # Number is assigned to an agent — import as claimed
            entry = PhoneNumber(
                phone_number=phone,
                provider="tata_tele",
                country_code="+91",
                label=label or assignment.customer_name,
                provider_sid=did_sid or None,
                capabilities={"voice": True, "sms": False},
                added_by_user_id=added_by_user_id,
                status="claimed",
                claimed_by_company_id=assignment.company_id,
                claimed_at=assignment.assigned_at,
            )
            db.add(entry)
            skipped.append(phone)
        else:
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

    result = {
        "added": len(added),
        "skipped": len(skipped),
        "added_numbers": added,
        "imported_assigned": len(imported_from_assignments),
    }

    # If API call failed and we got 0 numbers from the API, report errors
    if not numbers_data and api_errors:
        result["warning"] = (
            f"Could not fetch numbers from Smartflo API ({len(api_errors)} attempts failed). "
            f"Numbers already assigned to agents were imported from local records."
        )
        result["api_errors"] = api_errors[:3]  # Limit to first 3 errors for readability
        logger.warning(f"Tata Tele sync: API calls failed — {api_errors[0]}")

    return result



@router.get("")
async def list_pool_numbers(
    status: Optional[str] = None,
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List phone numbers in the pool.
    
    - app_admin: sees all numbers
    - tenant_admin: sees available + own claimed numbers
    """
    query = select(PhoneNumber)

    if current_user.role not in ("app_admin",):
        # Tenant sees available numbers + their own claimed numbers
        query = query.where(
            or_(
                PhoneNumber.status == "available",
                PhoneNumber.claimed_by_company_id == current_user.company_id,
            )
        )

    if status:
        query = query.where(PhoneNumber.status == status)
    if provider:
        query = query.where(PhoneNumber.provider == provider)

    query = query.order_by(PhoneNumber.created_at.desc())
    result = await db.execute(query)
    numbers = result.scalars().all()

    return [_to_response(n) for n in numbers]


@router.post("/{number_id}/claim")
async def claim_number(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Claim an available number for the caller's company (tenant_admin+)."""
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

    entry.status = "claimed"
    entry.claimed_by_company_id = current_user.company_id
    entry.claimed_by_user_id = current_user.id
    entry.claimed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(entry)

    return {
        "status": "claimed",
        "number": _to_response(entry),
    }


@router.post("/{number_id}/release")
async def release_number(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release a claimed number back to the pool."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found")

    # Only the owning company or app_admin can release
    if current_user.role != "app_admin" and entry.claimed_by_company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorized to release this number")

    if entry.status != "claimed":
        raise HTTPException(status_code=400, detail="Number is not currently claimed")

    entry.status = "available"
    entry.claimed_by_company_id = None
    entry.claimed_by_user_id = None
    entry.claimed_at = None

    await db.commit()
    await db.refresh(entry)

    return {
        "status": "released",
        "number": _to_response(entry),
    }


@router.delete("/{number_id}")
async def remove_from_pool(
    number_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Remove a number from the pool entirely (app_admin only)."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found")

    if entry.status == "claimed":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a claimed number. Release it first.",
        )

    await db.delete(entry)
    await db.commit()
    return {"status": "deleted", "number": entry.phone_number}


# --- Helpers ---

def _to_response(entry: PhoneNumber) -> dict:
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
        "claimed_by_company_id": str(entry.claimed_by_company_id) if entry.claimed_by_company_id else None,
        "claimed_at": entry.claimed_at.isoformat() if entry.claimed_at else None,
        "notes": entry.notes,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
