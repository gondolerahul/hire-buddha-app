from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from uuid import UUID
from src.common.tenancy.session import get_control_db
from src.auth.models import User, Company
from src.auth.schemas import UserCreateAdmin, UserResponse, UserUpdate
from src.auth.dependencies import get_current_user, RoleChecker
from src.auth.roles import USER_ADMIN_ROLES
from src.auth.service import create_user_as_admin, update_user_as_admin
from src.auth.visibility import visible_company_ids

router = APIRouter(prefix="/users", tags=["users"])

@router.get("", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    # Only user admins list users; each sees the users of the companies it can see.
    if current_user.role not in USER_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    query = select(User)
    scope = await visible_company_ids(db, current_user)
    if scope is not None:
        query = query.where(User.company_id.in_(scope))
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=UserResponse)
async def create_user(
    user_in: UserCreateAdmin,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(RoleChecker(["app_admin", "partner_admin", "tenant_admin"]))
):
    # The plan's limit.users (Phase 15 T6-2), for the company the user joins.
    from sqlalchemy import func, select as _select

    from src.billing.features import check_limit, feature_locked
    target = getattr(user_in, "company_id", None) or current_user.company_id
    if str(getattr(current_user.role, "value", current_user.role)) != "app_admin":
        in_use = (await db.execute(_select(func.count(User.id)).where(
            User.company_id == target, User.is_active.is_(True)))).scalar() or 0
        refusal = await check_limit(db, target, "limit.users", in_use)
        if refusal:
            raise feature_locked("limit.users", refusal)
    return await create_user_as_admin(db, user_in, current_user)

@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    return await update_user_as_admin(db, user_id, user_update, current_user)
