"""Auth endpoints (SPEC §8).

All login paths resolve to the same JWT access + opaque refresh model. Tenant is
resolved from context (token / subdomain / X-Tenant-ID header / dev default) —
the student never types a school code daily (SPEC §3.0).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from ..core.config import settings
from ..core.security import CurrentUser, get_current_user, require_fresh_auth, require_role
from ..db.mongo import get_db
from ..models.auth import (
    ClaimAuthedRequest,
    ClaimOtpRequest,
    FamilySwitchRequest,
    LogoutRequest,
    OtpRequestRequest,
    OtpVerifyRequest,
    PasswordLoginRequest,
    RefreshRequest,
    StudentLoginRequest,
    TokenPair,
)
from ..services import auth_service, invite_service, otp_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _ctx(request: Request, x_device_id: Optional[str]) -> dict:
    return {
        "device_id": x_device_id,
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
    }


def _resolve_tenant(explicit: Optional[str], x_tenant_id: Optional[str]) -> str:
    """Tenant for pre-login flows (OTP) where there's no token yet (SPEC §3.0)."""
    tenant = explicit or x_tenant_id
    if tenant:
        return tenant
    if settings.is_production():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant required")
    return "demo-school"


@router.post("/login/password", response_model=TokenPair)
async def login_password(
    body: PasswordLoginRequest,
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    db = await get_db()
    return await auth_service.password_login(
        db, identifier=body.identifier, password=body.password, **_ctx(request, x_device_id)
    )


@router.post("/login/student", response_model=TokenPair)
async def login_student(
    body: StudentLoginRequest,
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    db = await get_db()
    return await auth_service.student_login(
        db, tenant=body.tenant, student_code=body.student_code, pin=body.pin,
        **_ctx(request, x_device_id),
    )


@router.post("/login/otp/request")
async def login_otp_request(
    body: OtpRequestRequest,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
):
    db = await get_db()
    tenant = _resolve_tenant(body.tenant, x_tenant_id)
    return await otp_service.request_otp(db, tenant=tenant, phone=body.phone)


@router.post("/login/otp/verify", response_model=TokenPair)
async def login_otp_verify(
    body: OtpVerifyRequest,
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    db = await get_db()
    tenant = _resolve_tenant(body.tenant, x_tenant_id)
    return await auth_service.parent_otp_login(
        db, tenant=tenant, phone=body.phone, code=body.code, **_ctx(request, x_device_id)
    )


@router.post("/family/switch", response_model=TokenPair)
async def family_switch(
    body: FamilySwitchRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("parent")),
):
    db = await get_db()
    return await auth_service.family_switch(
        db, parent_claims=user.claims, student_id=body.student_id, pin=body.pin,
        ip=request.client.host if request.client else None,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    db = await get_db()
    return await auth_service.refresh(
        db, refresh_token=body.refresh_token, student_id=body.student_id,
        device_id=x_device_id, ip=request.client.host if request.client else None,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest):
    db = await get_db()
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
async def children(user: CurrentUser = Depends(require_role("parent"))):
    db = await get_db()
    return await auth_service.get_children_for_parent(db, tenant=user.tenant, parent_id=user.user_id)


@router.get("/invite/{token}")
async def resolve_invite(token: str):
    """Public: resolve an invitation link → child + school + whether the parent
    already exists (drives 'Set up' vs 'Add child' copy)."""
    db = await get_db()
    return await invite_service.resolve_invite(db, token=token)


@router.post("/claim", response_model=TokenPair)
async def claim(
    body: ClaimOtpRequest,
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
):
    """Unauthenticated claim: invite + phone + OTP → find-or-create parent →
    link child + consent → parent session (idempotent for the 2nd child)."""
    db = await get_db()
    return await invite_service.claim_with_otp(
        db, token=body.token, phone=body.phone, code=body.code,
        relationship=body.relationship, **_ctx(request, x_device_id),
    )


@router.post("/parent/claim")
async def parent_claim(
    body: ClaimAuthedRequest,
    request: Request,
    user: CurrentUser = Depends(require_fresh_auth("parent")),
):
    """A signed-in parent adds another child (step-up required)."""
    db = await get_db()
    return await invite_service.claim_authenticated(
        db, parent_claims=user.claims, token=body.token, relationship=body.relationship,
        ip=request.client.host if request.client else None,
    )


@router.get("/resolve-tenant")
async def resolve_tenant(school_code: str):
    """One-time helper: human school code → tenant the app then remembers (§3.0)."""
    db = await get_db()
    t = await db.tenants.find_one({"school_code": school_code.strip().upper()})
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return {"tenant": t["tenant"], "name": t.get("name"), "board": t.get("board")}
