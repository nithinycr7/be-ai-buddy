"""Trusted learning devices + pairing (device-bound, student-scoped sessions).

The security boundary: a paired device's refresh token is a **device session**
(`scope="device"`) that can ONLY ever mint student tokens for its
`allowed_students` — never a parent token — even though the parent owns it. This
is what makes it safe to leave a tablet signed-in at home (review: the one real
gap in plain family-switch).

Pairing = a one-time grant the *authenticated parent* generates (step-up
enforced at the router), rendered as a QR token + a short numeric code. The
device consumes it once to bootstrap its session.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.config import settings
from ..core.passwords import generate_numeric_code, generate_opaque_token, verify_secret
from ..core.tokens import create_access_token, hash_refresh_token
from .auth_service import (
    _ACCESS_TTL_SECONDS,
    _audit,
    _create_session,
    _epoch,
    _student_mode,
    _user_public,
)

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _child_profiles(db: AsyncIOMotorDatabase, *, tenant: str, student_ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for sid in student_ids:
        child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": sid})
        if not child:
            continue
        out.append({
            "student_id": sid,
            "name": child.get("name"),
            "class_no": child.get("class_no"),
            "section": child.get("section"),
            "avatar": child.get("avatar"),
            "mascot": child.get("mascot"),
            "has_pin": bool(child.get("pin_hash")),
        })
    return out


# --- pairing ------------------------------------------------------------------

async def start_pairing(
    db: AsyncIOMotorDatabase,
    *,
    parent_claims: dict,
    student_ids: Optional[list[str]] = None,
    pinned_student_id: Optional[str] = None,
    label: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Create a one-time pairing grant (QR token + numeric code). Step-up auth is
    enforced by the router (`require_fresh_auth`)."""
    tenant = parent_claims["tenant"]
    parent_id = parent_claims["sub"]

    # Default to all of the parent's linked children; otherwise validate ownership.
    links = db.parent_links.find({"tenant": tenant, "parent_id": parent_id, "status": "active"})
    owned = [l["student_id"] async for l in links]
    if not owned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No linked children to pair")
    if student_ids:
        bad = [s for s in student_ids if s not in owned]
        if bad:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your child")
        allowed = student_ids
    else:
        allowed = owned
    if pinned_student_id and pinned_student_id not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pinned child not in allowed set")

    code = generate_numeric_code(settings.PAIRING_CODE_LENGTH)
    qr_token = generate_opaque_token(24)
    grant = {
        "tenant": tenant,
        "parent_id": parent_id,
        "student_ids": allowed,
        "pinned_student_id": pinned_student_id,
        "label": label,
        "code": code,
        "qr_token_hash": hash_refresh_token(qr_token),
        "consumed": False,
        "created_at": _now(),
        "expires_at": _now() + timedelta(minutes=settings.PAIRING_TTL_MIN),
    }
    await db.pairing_grants.insert_one(grant)
    await _audit(db, tenant=tenant, actor_id=parent_id, action="device.pair.start", ip=ip)
    return {
        "code": code,
        "qr_token": qr_token,
        "expires_in": settings.PAIRING_TTL_MIN * 60,
        "students": await _child_profiles(db, tenant=tenant, student_ids=allowed),
        "pinned_student_id": pinned_student_id,
    }


async def claim_device(
    db: AsyncIOMotorDatabase,
    *,
    code: Optional[str] = None,
    qr_token: Optional[str] = None,
    device_id: str,
    label: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Consume a pairing grant and bootstrap a device session (student-scoped).

    Returns a student TokenPair for the pinned/first child + the profile list so
    a shared device can render the selector."""
    if not device_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="device_id required")

    q = None
    if qr_token:
        q = {"qr_token_hash": hash_refresh_token(qr_token)}
    elif code:
        q = {"code": code.strip()}
    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="code or qr_token required")

    grant = await db.pairing_grants.find_one(q)
    bad = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code")
    if not grant or grant.get("consumed"):
        raise bad
    if _aware(grant.get("expires_at")) and _aware(grant["expires_at"]) < _now():
        raise bad

    # single-use: atomically consume
    res = await db.pairing_grants.update_one(
        {"_id": grant["_id"], "consumed": False}, {"$set": {"consumed": True, "consumed_at": _now()}}
    )
    if res.modified_count != 1:
        raise bad  # lost the race — already consumed

    tenant = grant["tenant"]
    parent_id = grant["parent_id"]
    allowed = grant["student_ids"]
    pinned = grant.get("pinned_student_id")
    auth_time = _epoch()

    # device session: scope=device, owned by the parent, restricted to allowed kids
    sid, raw_refresh = await _create_session(
        db, tenant=tenant, user_id=parent_id, device_id=device_id, user_agent=user_agent,
        scope="device", allowed_students=allowed, auth_time=auth_time,
        label=label or grant.get("label"),
    )
    if pinned:
        await db.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"pinned_student_id": pinned}})

    # register/refresh the device record
    await db.devices.update_one(
        {"tenant": tenant, "device_id": device_id},
        {"$set": {
            "tenant": tenant, "device_id": device_id, "parent_id": parent_id,
            "label": label or grant.get("label"), "allowed_students": allowed,
            "pinned_student_id": pinned, "session_id": sid, "trusted": True,
            "last_seen": _now(),
        }, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )

    # first profile to open: pinned, else the only child, else the first
    target = pinned or (allowed[0] if len(allowed) == 1 else allowed[0])
    child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": target})
    access = create_access_token(
        sub=str(child["_id"]), role="student", tenant=tenant, sid=sid,
        sct=target, did=device_id, auth_time=auth_time, mode=_student_mode(child),
    )
    await _audit(db, tenant=tenant, actor_id=parent_id, action="device.pair.claim", target=device_id, ip=ip)
    return {
        "access_token": access, "refresh_token": raw_refresh, "token_type": "bearer",
        "expires_in": _ACCESS_TTL_SECONDS, "role": "student", "tenant": tenant,
        "user": _user_public(child),
        "children": await _child_profiles(db, tenant=tenant, student_ids=allowed),
        "pinned_student_id": pinned,
    }


async def switch_profile(
    db: AsyncIOMotorDatabase,
    *,
    device_claims: dict,
    student_id: str,
    pin: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Shared-device 'Who's learning?' switch: mint a student token for another
    allowed child on the SAME device session (no new refresh)."""
    tenant = device_claims["tenant"]
    sid = device_claims.get("sid")
    sess = await db.sessions.find_one({"_id": ObjectId(sid)}) if sid else None
    if not sess or sess.get("revoked") or sess.get("scope") != "device":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a device session")
    allowed = sess.get("allowed_students") or []
    if student_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Profile not on this device")

    child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": student_id})
    if not child:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if child.get("pin_hash"):
        if not pin or not verify_secret(pin, child.get("pin_hash")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong profile PIN")

    access = create_access_token(
        sub=str(child["_id"]), role="student", tenant=tenant, sid=str(sess["_id"]),
        sct=student_id, did=sess.get("device_id"), auth_time=sess.get("auth_time"),
        mode=_student_mode(child),
    )
    return {
        "access_token": access, "refresh_token": None, "token_type": "bearer",
        "expires_in": _ACCESS_TTL_SECONDS, "role": "student", "tenant": tenant,
        "user": _user_public(child), "children": None,
    }


# --- management (parent) ------------------------------------------------------

async def list_devices(db: AsyncIOMotorDatabase, *, tenant: str, parent_id: str) -> list[dict]:
    out: list[dict] = []
    cur = db.devices.find({"tenant": tenant, "parent_id": parent_id})
    async for d in cur:
        sess = await db.sessions.find_one({"_id": ObjectId(d.get("session_id"))}) if d.get("session_id") else None
        active = bool(sess and not sess.get("revoked"))
        out.append({
            "device_id": d["device_id"],
            "label": d.get("label"),
            "allowed_students": d.get("allowed_students", []),
            "pinned_student_id": d.get("pinned_student_id"),
            "trusted": d.get("trusted", False) and active,
            "last_seen": d.get("last_seen"),
            "created_at": d.get("created_at"),
        })
    return out


async def revoke_device(db: AsyncIOMotorDatabase, *, tenant: str, parent_id: str, device_id: str, ip: Optional[str] = None) -> None:
    dev = await db.devices.find_one({"tenant": tenant, "parent_id": parent_id, "device_id": device_id})
    if not dev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await db.sessions.update_many({"tenant": tenant, "device_id": device_id}, {"$set": {"revoked": True}})
    await db.devices.update_one({"_id": dev["_id"]}, {"$set": {"trusted": False, "revoked_at": _now()}})
    await _audit(db, tenant=tenant, actor_id=parent_id, action="device.revoke", target=device_id, ip=ip)


def ObjectId(sid):
    from bson import ObjectId
    return ObjectId(sid)
