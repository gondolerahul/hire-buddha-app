from pydantic import AfterValidator, BaseModel, EmailStr, Field
from typing import Annotated, Optional, List, Dict, Any, Literal
from datetime import datetime
from uuid import UUID

from src.auth.roles import Role

# An address as accounts store it: lower case (AU-26). ``EmailStr`` lower-cases
# only the domain, so "Owner@x.com" and "owner@x.com" were two accounts, and a
# login had to match the case used at sign-up.
Email = Annotated[EmailStr, AfterValidator(str.lower)]

def _gstin(value: Optional[str]) -> Optional[str]:
    from src.auth.geography import valid_gstin
    return valid_gstin(value)


def _state(value: Optional[str]) -> Optional[str]:
    from src.auth.geography import valid_state
    return valid_state(value)


# ISO 3166 alpha-2; the API checks it against the country profiles (Phase 15 T2-3).
CountryCode = Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")]


class UserCreate(BaseModel):
    email: Email
    password: str
    full_name: str
    # The workspace's country: its billing currency follows (FX-1). India when omitted.
    country_code: Optional[CountryCode] = None
    billing_state: Annotated[Optional[str], AfterValidator(_state)] = None

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
    # A partner added by staff (Phase 15 T8-2): Silver or Gold; Gold when omitted.
    partner_type: Optional[Literal["SILVER", "GOLD"]] = None
    # Its billing currency follows (FX-1, Phase 15 T2-3). India when omitted.
    country_code: Optional[CountryCode] = None
    billing_state: Annotated[Optional[str], AfterValidator(_state)] = None

def _iana_timezone(value: Optional[str]) -> Optional[str]:
    from src.common.timezones import is_valid_timezone

    if value is not None and not is_valid_timezone(value):
        raise ValueError(f"{value!r} is not an IANA time zone (e.g. Asia/Kolkata, Europe/London)")
    return value


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["active", "suspended"]] = None
    # What the company may be billed in a calendar month; null removes the cap (GH-18).
    monthly_spend_cap_usd: Optional[float] = Field(default=None, gt=0)
    # The business time zone schedules and reports use (Phase 14 WS1 1.10).
    timezone: Annotated[Optional[str], AfterValidator(_iana_timezone)] = None
    # Billing profile (Phase 15 T2-2): what invoices show. The country and the
    # billing currency are not changed here (FX-1).
    legal_name: Optional[str] = None
    gstin: Annotated[Optional[str], AfterValidator(_gstin)] = None
    billing_state: Annotated[Optional[str], AfterValidator(_state)] = None
    billing_address: Optional[Dict[str, Any]] = None

class CompanyResponse(CompanyBase):
    id: UUID
    logo_url: Optional[str] = None
    parent_id: Optional[UUID] = None
    onboarding_status: Optional[str] = "pending"
    monthly_spend_cap_usd: Optional[float] = None
    timezone: str = "Asia/Kolkata"
    country_code: str = "IN"
    billing_currency: str = "INR"
    billing_state: Optional[str] = None
    gstin: Optional[str] = None
    legal_name: Optional[str] = None
    billing_address: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

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

STAFF_FUNCTIONS = ("support", "sales", "finance", "ops")


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[Role] = None
    # An app_user's console functions (Phase 15 T9-12); set by app_admin only.
    staff_functions: Optional[List[Literal["support", "sales", "finance", "ops"]]] = None

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    company_id: UUID
    role: str
    is_active: bool
    profile_picture_url: Optional[str] = None
    staff_functions: List[str] = []

    class Config:
        from_attributes = True


class MeResponse(UserResponse):
    """``GET /auth/me``: the user, and how their company is billed (Phase 15 T2-5) —
    the screens show money in ``billing_currency``."""
    country_code: Optional[str] = None
    # Which workspace the screens show (Phase 15 T9-1): the company's type, and a partner's type.
    company_type: Optional[str] = None
    partner_type: Optional[str] = None
    billing_currency: Optional[str] = None
