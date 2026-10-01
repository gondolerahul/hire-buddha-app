from pydantic import AfterValidator, BaseModel, EmailStr
from typing import Annotated, Optional, List, Dict, Any, Literal
from uuid import UUID

from src.auth.roles import Role

# An address as accounts store it: lower case (AU-26). ``EmailStr`` lower-cases
# only the domain, so "Owner@x.com" and "owner@x.com" were two accounts, and a
# login had to match the case used at sign-up.
Email = Annotated[EmailStr, AfterValidator(str.lower)]

class UserCreate(BaseModel):
    email: Email
    password: str
    full_name: str

class UserCreateAdmin(UserCreate):
    company_id: UUID
    role: Role

class UserLogin(BaseModel):
    email: Email
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class EmailRequest(BaseModel):
    email: Email


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str


class RegistrationResponse(BaseModel):
    email: EmailStr
    message: str


class LogoutRequest(BaseModel):
    refresh_token: str
    all_sessions: bool = False  # also end every other session of this user

class OAuthRequest(BaseModel):
    code: str
    redirect_uri: str
    # PKCE (RFC 7636): the verifier for the code_challenge the authorize request
    # sent. Forwarded to the provider's token endpoint when given.
    code_verifier: Optional[str] = None

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
    status: Optional[Literal["active", "suspended"]] = None

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
    role: Optional[Role] = None

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
