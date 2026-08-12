"""
Onboarding Router — Manages the multi-step onboarding wizard for new tenants.

Steps:
  1. company_profile  — Set company name, logo, industry
  2. integrations     — Configure AI provider keys (Google / OpenAI / etc.)
  3. first_agent      — Clone a template or create a basic agent
  4. phone_setup      — (Optional) Claim a phone number from the pool
  5. billing          — Review wallet and pricing info

The frontend calls these endpoints to track progress and the ProtectedRoute
guard redirects users with onboarding_status != "completed" to /onboarding.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from src.common.database import get_db
from src.auth.models import Company, User
from src.auth.schemas import OnboardingStatusResponse, OnboardingStepRequest
from src.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

ONBOARDING_STEPS = [
    "company_profile",
    "integrations",
    "first_agent",
    "phone_setup",
    "billing",
]


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current onboarding progress for the caller's company."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    meta = company.onboarding_metadata or {}
    completed = meta.get("completed_steps", [])
    remaining = [s for s in ONBOARDING_STEPS if s not in completed]

    return OnboardingStatusResponse(
        status=company.onboarding_status or "pending",
        completed_steps=completed,
        total_steps=len(ONBOARDING_STEPS),
        current_step=remaining[0] if remaining else None,
        completion_pct=round(len(completed) / len(ONBOARDING_STEPS) * 100, 1),
        metadata=meta,
    )


@router.post("/step/{step_name}", response_model=OnboardingStatusResponse)
async def complete_onboarding_step(
    step_name: str,
    body: OnboardingStepRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an onboarding step as completed and persist any step-specific data."""
    if step_name not in ONBOARDING_STEPS:
        raise HTTPException(status_code=400, detail=f"Unknown step '{step_name}'. Valid: {ONBOARDING_STEPS}")

    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    meta = dict(company.onboarding_metadata or {})
    completed = list(meta.get("completed_steps", []))

    if step_name not in completed:
        completed.append(step_name)

    meta["completed_steps"] = completed

    # Store step-specific data if provided
    if body and body.step_data:
        meta.setdefault("step_data", {})[step_name] = body.step_data

    # Handle company_profile step — update company name/logo
    if step_name == "company_profile" and body and body.step_data:
        sd = body.step_data
        if sd.get("name"):
            company.name = sd["name"]
        if sd.get("logo_url"):
            company.logo_url = sd["logo_url"]

    company.onboarding_metadata = meta
    company.onboarding_status = "in_progress"

    await db.commit()
    await db.refresh(company)

    remaining = [s for s in ONBOARDING_STEPS if s not in completed]
    return OnboardingStatusResponse(
        status=company.onboarding_status,
        completed_steps=completed,
        total_steps=len(ONBOARDING_STEPS),
        current_step=remaining[0] if remaining else None,
        completion_pct=round(len(completed) / len(ONBOARDING_STEPS) * 100, 1),
        metadata=meta,
    )


@router.post("/complete", response_model=OnboardingStatusResponse)
async def finalize_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Finalize onboarding — sets status to 'completed'."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.onboarding_status = "completed"
    meta = dict(company.onboarding_metadata or {})
    meta["completed_at"] = __import__("datetime").datetime.utcnow().isoformat()
    company.onboarding_metadata = meta

    await db.commit()
    await db.refresh(company)

    completed = meta.get("completed_steps", [])
    return OnboardingStatusResponse(
        status="completed",
        completed_steps=completed,
        total_steps=len(ONBOARDING_STEPS),
        current_step=None,
        completion_pct=100.0,
        metadata=meta,
    )


@router.post("/skip")
async def skip_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Allow a user to skip onboarding entirely — sets status to completed."""
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.onboarding_status = "completed"
    meta = dict(company.onboarding_metadata or {})
    meta["skipped"] = True
    company.onboarding_metadata = meta

    await db.commit()
    return {"status": "skipped", "message": "Onboarding skipped successfully"}
