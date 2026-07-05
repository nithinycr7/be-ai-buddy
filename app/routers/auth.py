"""Auth endpoints (SPEC §8) — HTTP layer only; orchestration in auth_service/invite_service/otp_service.

All login paths resolve to the same JWT access + opaque refresh model. Tenant is
resolved from context (token / subdomain / X-Tenant-ID header / dev default).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.security import CurrentUser, get_current_user, require_fresh_auth, require_role
from ..db.mongo import get_db
from ..models.auth import (
    ClaimAuthedRequest, ClaimOtpRequest, FamilySwitchRequest, LogoutRequest,
    OtpRequestRequest, OtpVerifyRequest, PasswordLoginRequest, RefreshRequest,
    StudentLoginRequest, StudentSignupRequest, TokenPair,
)
from ..services import auth_service, invite_service, otp_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _ctx(request: Request, x_device_id: Optional[str]) -> dict:
    return {
        "device_id": x_device_id,
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
    }


@router.post("/login/password", response_model=TokenPair)
async def login_password(
    body: PasswordLoginRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    return await auth_service.password_login(
        db, identifier=body.identifier, password=body.password, **_ctx(request, x_device_id))


@router.post("/login/student", response_model=TokenPair)
async def login_student(
    body: StudentLoginRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    return await auth_service.student_login(
        db, tenant=body.tenant, student_code=body.student_code, pin=body.pin,
        **_ctx(request, x_device_id))


@router.post("/login/otp/request")
async def login_otp_request(
    body: OtpRequestRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
):
    tenant = auth_service.pre_login_tenant(body.tenant, x_tenant_id)
    return await otp_service.request_otp(db, tenant=tenant, identifier=body.contact, channel=body.channel)


@router.post("/login/otp/verify", response_model=TokenPair)
async def login_otp_verify(
    body: OtpVerifyRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    tenant = auth_service.pre_login_tenant(body.tenant, x_tenant_id)
    return await auth_service.parent_otp_login(
        db, tenant=tenant, identifier=body.contact, code=body.code, **_ctx(request, x_device_id))


@router.post("/signup/student", response_model=TokenPair)
async def signup_student(
    body: StudentSignupRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    """Open B2C self-study student self-signup (OTP-verified → 'direct' tenant)."""
    return await auth_service.signup_open_student(
        db, identifier=body.identifier, code=body.code, name=body.name,
        class_no=body.class_no, board=body.board or "CBSE", **_ctx(request, x_device_id))


@router.post("/family/switch", response_model=TokenPair)
async def family_switch(
    body: FamilySwitchRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(require_role("parent")),
):
    return await auth_service.family_switch(
        db, parent_claims=user.claims, student_id=body.student_id, pin=body.pin,
        ip=request.client.host if request.client else None)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    return await auth_service.refresh(
        db, refresh_token=body.refresh_token, student_id=body.student_id,
        device_id=x_device_id, ip=request.client.host if request.client else None)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    await auth_service.logout(db, refresh_token=body.refresh_token)
    return None


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    """Echo the verified identity (handy for the frontend to bootstrap state)."""
    return {
        "user_id": user.user_id, "role": user.role, "tenant": user.tenant,
        "student_id": user.student_id, "parent_id": user.parent_id, "kids": user.kids,
    }


@router.get("/children")
async def children(user: CurrentUser = Depends(require_role("parent")),
                   db: AsyncIOMotorDatabase = Depends(get_db)):
    return await auth_service.get_children_for_parent(db, tenant=user.tenant, parent_id=user.user_id)


@router.get("/invite/{token}")
async def resolve_invite(token: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Public: resolve an invitation link → child + school + whether the parent exists."""
    return await invite_service.resolve_invite(db, token=token)


@router.post("/claim", response_model=TokenPair)
async def claim(
    body: ClaimOtpRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    """Unauthenticated claim: invite + (email|phone) + OTP → find-or-create parent → link child."""
    return await invite_service.claim_with_otp(
        db, token=body.token, identifier=body.contact, code=body.code,
        relationship=body.relationship, **_ctx(request, x_device_id))


@router.post("/parent/claim")
async def parent_claim(
    body: ClaimAuthedRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(require_fresh_auth("parent")),
):
    """A signed-in parent adds another child (step-up required)."""
    return await invite_service.claim_authenticated(
        db, parent_claims=user.claims, token=body.token, relationship=body.relationship,
        ip=request.client.host if request.client else None)


@router.get("/resolve-tenant")
async def resolve_tenant(school_code: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """One-time helper: human school code → tenant the app then remembers (§3.0)."""
    return await auth_service.resolve_tenant_by_code(db, school_code=school_code)
