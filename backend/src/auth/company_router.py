from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from uuid import UUID
from src.common.database import get_db
from src.auth.models import Company, User
from src.auth.schemas import CompanyCreate, CompanyResponse, CompanyUpdate
from src.auth.dependencies import get_current_user, RoleChecker

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("", response_model=List[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all companies. app_admin sees all; partner_admin sees own + children."""
    if current_user.role == "app_admin":
        result = await db.execute(select(Company).order_by(Company.name))
    elif current_user.role in ("partner_admin", "partner_user"):
        from sqlalchemy import or_
        result = await db.execute(
            select(Company).where(
                or_(
                    Company.id == current_user.company_id,
                    Company.parent_id == current_user.company_id,
                )
            ).order_by(Company.name)
        )
    else:
        # Tenants only see their own company
        result = await db.execute(
            select(Company).where(Company.id == current_user.company_id)
        )
    return result.scalars().all()

@router.get("/partners", response_model=List[CompanyResponse])
async def get_partners(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["app_admin"]))
):
    result = await db.execute(select(Company).filter(Company.type == "PARTNER"))
    return result.scalars().all()

@router.get("/tenants", response_model=List[CompanyResponse])
async def get_tenants(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["app_admin", "partner_admin"]))
):
    if current_user.role == "app_admin":
        result = await db.execute(select(Company).filter(Company.type == "TENANT"))
    else:
        # Partner admin can see their own tenants
        result = await db.execute(select(Company).filter(
            Company.type == "TENANT", 
            Company.parent_id == current_user.company_id
        ))
    return result.scalars().all()

@router.post("", response_model=CompanyResponse)
async def create_company(
    company: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["app_admin", "partner_admin"]))
):
    # Validation logic
    if current_user.role == "partner_admin":
        if company.type != "TENANT":
            raise HTTPException(status_code=403, detail="Partner admins can only create Tenants")
        company.parent_id = current_user.company_id
    
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
    db.add(new_company)
    await db.flush()

    # Auto-provision CreditWallet if applicable
    if company.type == "TENANT" and company.apply_default_daily_credits:
        from src.auth.service import _provision_new_tenant
        await _provision_new_tenant(db, new_company)
        # Apply custom daily credits override if specified
        if company.custom_daily_credits is not None:
            try:
                from src.billing.billing_models import CreditWallet
                from decimal import Decimal
                result = await db.execute(
                    select(CreditWallet).where(CreditWallet.company_id == new_company.id)
                )
                wallet = result.scalar_one_or_none()
                if wallet:
                    wallet.daily_credits = Decimal(str(company.custom_daily_credits))
            except Exception:
                pass

    await db.commit()
    await db.refresh(new_company)
    return new_company

@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    company_update: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check permissions
    if current_user.role != "app_admin" and current_user.company_id != company_id:
        # Also allow partner admins to update their own tenants?
        # For now, stick to the current user's company or app_admin
        raise HTTPException(status_code=403, detail="Not authorized to update this company")
    
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    update_data = company_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)
    
    await db.commit()
    await db.refresh(company)
    return company
