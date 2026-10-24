from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from uuid import UUID
from src.common.tenancy.session import get_control_db
from src.auth.models import Company, User
from src.auth.schemas import CompanyCreate, CompanyResponse, CompanyUpdate
from src.auth.dependencies import get_current_user, RoleChecker
from src.auth.roles import Role
from src.auth.visibility import visible_company_ids

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("", response_model=List[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    """The companies the caller can see: all (app_admin), own + tenants (partners), or own."""
    query = select(Company).order_by(Company.name)
    scope = await visible_company_ids(db, current_user)
    if scope is not None:
        query = query.where(Company.id.in_(scope))
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/partners", response_model=List[CompanyResponse])
async def get_partners(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(RoleChecker(["app_admin"]))
):
    result = await db.execute(select(Company).filter(Company.type == "PARTNER"))
    return result.scalars().all()

@router.get("/tenants", response_model=List[CompanyResponse])
async def get_tenants(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(RoleChecker(["app_admin", "partner_admin"]))
):
    if current_user.role == "app_admin":
        result = await db.execute(select(Company).filter(Company.type == "TENANT"))
    else:
        # A partner admin's resold tenants (Phase 15 T8-3); a Silver partner's referred customers are
        # on the partner portal, without their data.
        from src.partners.scope import data_scope
        scope = await data_scope(db, current_user.company_id)
        result = await db.execute(select(Company).filter(Company.type == "TENANT", Company.id.in_(scope)))
    return result.scalars().all()

@router.post("", response_model=CompanyResponse)
async def create_company(
    company: CompanyCreate,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(RoleChecker(["app_admin", "partner_admin"]))
):
    # Validation logic
    if current_user.role == "partner_admin":
        if company.type != "TENANT":
            raise HTTPException(status_code=403, detail="Partner admins can only create Tenants")
        # Only a partner whose type creates tenants (Gold), in good standing (Phase 15 T8-2, §11.1, §11.3).
        from src.partners.lifecycle import require_may_create_tenants
        await require_may_create_tenants(db, current_user.company_id)
        company.parent_id = current_user.company_id
    # The tree's rules (Phase 15 T8-1): a tenant under the platform or a partner, no cycles.
    from src.partners.tree import require_valid_parent
    await require_valid_parent(db, company.type, company.parent_id)
    
    new_company = Company(
        name=company.name,
        type=company.type,
        parent_id=company.parent_id,
        status="active",
        onboarding_status="pending",
        onboarding_metadata={
            "completed_steps": [],
            "created_via": "admin",
            "created_by": str(current_user.id),
        },
    )
    # Its country, and the billing currency that follows it (Phase 15 T2-3, FX-1).
    from src.auth.geography import set_geography
    await set_geography(db, new_company, company.country_code, billing_state=company.billing_state)
    db.add(new_company)
    await db.flush()

    # A tenant's wallet, and today's daily credits from its policy (Phase 15 T4-1,
    # T5-5); a company's own daily amount is a staff override on the Daily
    # credits page, not a field of this form (DC-1).
    if company.type == "PARTNER":
        # Staff adding a partner directly (applications are the usual way, T8-5): its profile, active.
        from src.partners.lifecycle import create_profile
        await create_profile(db, new_company, partner_type=company.partner_type or "GOLD", status="active",
                             recruiter_id=new_company.parent_id, reason="added by staff")
    if company.type == "TENANT":
        from src.auth.service import _provision_new_tenant
        await _provision_new_tenant(db, new_company)
        parent_type = None
        if new_company.parent_id is not None:
            parent_type = (await db.execute(select(Company.type).where(Company.id == new_company.parent_id))
                           ).scalar_one_or_none()
        if parent_type == "PARTNER":
            # The tenant is the partner's: resold, with its admin access (Phase 15 T8-2, T8-4).
            from src.partners.access import grant_for_created_tenant
            from src.partners.scope import assign
            await assign(db, tenant_id=new_company.id, partner_id=new_company.parent_id, relationship="resold",
                         source="created", actor_id=current_user.id)
            await grant_for_created_tenant(db, partner_id=new_company.parent_id, tenant_id=new_company.id,
                                           actor_id=current_user.id)

    await db.commit()
    if company.type == "TENANT":
        from src.auth.service import grant_first_daily_credits
        await grant_first_daily_credits(db, new_company.id)
    await db.refresh(new_company)
    from src.auth.service import request_workspace
    await request_workspace(new_company.id)  # split tenancy: its own database (WS2 2.9)
    return new_company

@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    company_update: CompanyUpdate,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    """Rename a company, set its time zone, or change its status (AU-03, AU-15).

    Rename and time zone: ``app_admin`` any company, ``partner_admin`` its own company and its
    tenants, ``tenant_admin`` its own company. Status (suspend / reactivate):
    ``app_admin`` any company and ``partner_admin`` its own tenants — never the
    caller's own company, which would lock the caller out with it.
    """
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    is_own = company.id == current_user.company_id
    is_partners_tenant = False
    if current_user.role == Role.PARTNER_ADMIN and not is_own:
        from src.partners.scope import data_scope
        is_partners_tenant = company.id in await data_scope(db, current_user.company_id)
    can_rename = (
        current_user.role == Role.APP_ADMIN
        or is_partners_tenant
        or (is_own and current_user.role in (Role.PARTNER_ADMIN, Role.TENANT_ADMIN))
    )
    can_set_status = not is_own and (current_user.role == Role.APP_ADMIN or is_partners_tenant)

    update_data = company_update.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] == company.status:
        del update_data["status"]  # unchanged — edit forms send it back
    if not can_rename:
        raise HTTPException(status_code=403, detail="Not authorized to update this company")
    if "status" in update_data and not can_set_status:
        raise HTTPException(status_code=403, detail="Not authorized to change this company's status")
    if "timezone" in update_data and update_data["timezone"] is None:
        del update_data["timezone"]  # a company always has a time zone
    if "monthly_spend_cap_usd" in update_data and update_data["monthly_spend_cap_usd"] != company.monthly_spend_cap_usd:
        # A locked cap stays as its locker set it (Phase 15 T5-4, Q5).
        from src.billing.locks import require_unlocked
        await require_unlocked(db, company.id, "spend_cap", current_user)

    for field, value in update_data.items():
        setattr(company, field, value)

    from src.common.tenancy.session import is_split
    if "timezone" in update_data and is_split():
        # Split mode reads the zone from the tenant directory (Phase 14 WS2).
        from sqlalchemy import update as sql_update
        from src.common.tenancy.models import TenantDirectoryEntry
        await db.execute(sql_update(TenantDirectoryEntry)
                         .where(TenantDirectoryEntry.company_id == company.id)
                         .values(timezone=update_data["timezone"]))
    await db.commit()
    await db.refresh(company)
    if "timezone" in update_data:
        from src.common.timezones import forget_company_timezone
        forget_company_timezone(company.id)
        if is_split():
            import redis.asyncio as redis_lib
            from src.common.tenancy.directory import publish_change
            from src.common.config import settings
            client = redis_lib.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
            try:
                await publish_change(client, company.id)
            finally:
                await client.aclose()
    return company
