from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from uuid import UUID

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str

class UserCreateAdmin(UserCreate):
    company_id: UUID
    role: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class OAuthRequest(BaseModel):
    code: str
    redirect_uri: str

class TokenData(BaseModel):
    email: Optional[str] = None

class CompanyBase(BaseModel):
    name: str
    type: str # APP, PARTNER, TENANT
    status: str = "active"

class CompanyCreate(CompanyBase):
    parent_id: Optional[UUID] = None
    apply_default_daily_credits: bool = True  # whether to apply default daily credits
    custom_daily_credits: Optional[float] = None  # custom daily credit amount override

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None

class CompanyResponse(CompanyBase):
    id: UUID
    logo_url: Optional[str] = None
    parent_id: Optional[UUID] = None
    onboarding_status: Optional[str] = "pending"
    
    class Config:
        from_attributes = True

# --- Onboarding Schemas ---

class OnboardingStatusResponse(BaseModel):
    status: str  # pending, in_progress, completed
    completed_steps: List[str] = []
    total_steps: int = 5
    current_step: Optional[str] = None
    completion_pct: float = 0.0
    metadata: Optional[Dict[str, Any]] = None

class OnboardingStepRequest(BaseModel):
    step_name: str  # company_profile, integrations, first_agent, phone_setup, billing
    step_data: Optional[Dict[str, Any]] = None  # arbitrary data for this step

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    company_id: UUID
    role: str
    is_active: bool
    profile_picture_url: Optional[str] = None

    class Config:
        from_attributes = True
