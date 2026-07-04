"""Device pairing + management (device-bound, student-scoped sessions).
HTTP layer only — orchestration in device_service.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.security import CurrentUser, get_current_user, require_fresh_auth, require_role
from ..db.mongo import get_db
from ..models.auth import DeviceClaimRequest, PairStartRequest, ProfileSwitchRequest, TokenPair
from ..services import device_service

router = APIRouter(tags=["devices"])


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# --- parent: manage trusted devices (step-up required to add/remove) ----------
@router.post("/parent/devices/pair/start")
async def pair_start(
    body: PairStartRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(require_fresh_auth("parent")),
):
    return await device_service.start_pairing(
        db, parent_claims=user.claims, student_ids=body.student_ids,
        pinned_student_id=body.pinned_student_id, label=body.label, ip=_ip(request))


@router.get("/parent/devices")
async def list_devices(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(require_role("parent")),
):
    return await device_service.list_devices(db, tenant=user.tenant, parent_id=user.user_id)


@router.delete("/parent/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(require_fresh_auth("parent")),
):
    await device_service.revoke_device(
        db, tenant=user.tenant, parent_id=user.user_id, device_id=device_id, ip=_ip(request))
    return None


# --- device: claim a grant (no token) -----------------------------------------
@router.post("/auth/device/claim", response_model=TokenPair)
async def device_claim(body: DeviceClaimRequest, request: Request,
                       db: AsyncIOMotorDatabase = Depends(get_db)):
    return await device_service.claim_device(
        db, code=body.code, qr_token=body.qr_token, device_id=body.device_id,
        label=body.label, user_agent=request.headers.get("user-agent"), ip=_ip(request))


# --- device: switch profile on a shared device --------------------------------
@router.post("/auth/device/switch", response_model=TokenPair)
async def device_switch(
    body: ProfileSwitchRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # device-session validation is enforced inside switch_profile (403 if not a device session)
    return await device_service.switch_profile(
        db, device_claims=user.claims, student_id=body.student_id, pin=body.pin, ip=_ip(request))
