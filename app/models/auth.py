"""Auth/identity API models (SPEC §4, §8).

DB documents (users, tenants, parent_links, sessions, otp_codes, audit_log) are
written as plain dicts in the service layer to match the existing codebase style;
these models cover the request/response surface of the ``/auth/*`` router.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

Role = str  # "student" | "parent" | "teacher" | "admin" | "superadmin"


# --- Responses ----------------------------------------------------------------

class UserPublic(BaseModel):
    id: str
    tenant: str
    role: Role
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    class_no: Optional[int] = None
    section: Optional[str] = None
    avatar: Optional[str] = None


class ChildProfile(BaseModel):
    student_id: str
    name: Optional[str] = None
    class_no: Optional[int] = None
    section: Optional[str] = None
    avatar: Optional[str] = None
    mascot: Optional[str] = None
    has_pin: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None  # omitted on family-switch (reuses parent session)
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime, seconds
    role: Role
    tenant: str
    user: Optional[UserPublic] = None
    children: Optional[List[ChildProfile]] = None  # parents only


# --- Requests -----------------------------------------------------------------

class PasswordLoginRequest(BaseModel):
    """Admin / teacher / superadmin. Tenant resolved from the user record."""
    identifier: str = Field(..., description="email or phone")
    password: str


class StudentLoginRequest(BaseModel):
    """School-issued device path (SPEC §3.1). Tenant resolved from context."""
    tenant: str
    student_code: str
    pin: str


class OtpRequestRequest(BaseModel):
    phone: str
    tenant: Optional[str] = None  # resolved from context (subdomain/deep link/first-run)


class OtpVerifyRequest(BaseModel):
    phone: str
    code: str
    tenant: Optional[str] = None


class FamilySwitchRequest(BaseModel):
    student_id: str
    pin: Optional[str] = None  # soft child PIN, if the parent set one


class RefreshRequest(BaseModel):
    refresh_token: str
    student_id: Optional[str] = None  # land straight back in kid mode (SPEC §5)


class LogoutRequest(BaseModel):
    refresh_token: str


# --- device pairing -----------------------------------------------------------

class PairStartRequest(BaseModel):
    """Parent generates a one-time pairing grant for a learning device."""
    student_ids: Optional[List[str]] = None      # default: all linked children
    pinned_student_id: Optional[str] = None      # "dedicated" device → one profile
    label: Optional[str] = None                  # e.g. "Aarav's tablet"


class DeviceClaimRequest(BaseModel):
    """The learning device consumes a pairing grant (QR token or numeric code)."""
    device_id: str
    code: Optional[str] = None
    qr_token: Optional[str] = None
    label: Optional[str] = None


class ProfileSwitchRequest(BaseModel):
    """Shared device 'Who's learning?' — switch to another allowed child."""
    student_id: str
    pin: Optional[str] = None


# --- parent invitation / claim ------------------------------------------------

class ClaimOtpRequest(BaseModel):
    """Unauthenticated claim of a school invitation (first-time / returning)."""
    token: str
    phone: str
    code: str
    relationship: Optional[str] = None


class ClaimAuthedRequest(BaseModel):
    """A signed-in parent adds another child via a new invitation."""
    token: str
    relationship: Optional[str] = None
