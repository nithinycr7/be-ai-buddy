"""Auth orchestration (SPEC §3, §5, §6, §8).

Login methods (password / student PIN / parent OTP / family-switch), session
issuance + rotation, and logout. All methods talk only to Mongo.

Identity mapping note: a **student** token carries ``sct`` = the business
``student_id`` (e.g. ``STU001``) that the existing data plane already scopes by,
while ``sub`` = the stable ``users._id``. Parents get ``kids`` (their linked
business student_ids); a kid-mode token (family switch) sets ``role=student``,
``sct`` = the child, and ``pid`` = the parent for provenance.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.config import settings
from ..core.passwords import verify_secret
from ..core.tokens import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    refresh_expiry,
)
from . import otp_service

log = logging.getLogger(__name__)

_ACCESS_TTL_SECONDS = settings.ACCESS_TOKEN_TTL_MIN * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _epoch() -> int:
    return int(time.time())


def _student_mode(user: Optional[dict]) -> str:
    """Content source for a student (two-axis identity): school|self.
    Defaults to ``school`` (B2B pilot)."""
    return ((user or {}).get("enrollment") or {}).get("type") or "school"


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _user_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "tenant": doc["tenant"],
        "role": doc["role"],
        "name": doc.get("name"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "class_no": doc.get("class_no"),
        "section": doc.get("section"),
        "avatar": doc.get("avatar"),
    }


# --- audit --------------------------------------------------------------------

async def _audit(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    actor_id: Optional[str],
    action: str,
    target: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    try:
        await db.audit_log.insert_one({
            "tenant": tenant,
            "actor_id": actor_id,
            "action": action,
            "target": target,
            "ip": ip,
            "at": _now(),
        })
    except Exception:  # auditing must never break the auth path
        log.exception("audit_log write failed (%s)", action)


# --- sessions -----------------------------------------------------------------

async def _create_session(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    user_id: str,
    device_id: Optional[str],
    user_agent: Optional[str],
    scope: str = "full",
    allowed_students: Optional[list[str]] = None,
    auth_time: Optional[int] = None,
    label: Optional[str] = None,
) -> tuple[str, str]:
    """Create a session row and return ``(session_id, raw_refresh_token)``.

    ``scope`` is the security boundary of the session:
      - ``full``   — a directly-authenticated user (parent/teacher/admin/student).
                     Its refresh mints that user's own role token.
      - ``device`` — a paired learning device. Its refresh can ONLY mint student
                     tokens for ``allowed_students`` — never a parent token, even
                     though the session is owned by the parent (SPEC device model).
    ``auth_time`` is the epoch of the last *strong* auth backing this session
    (drives step-up); it does NOT advance on silent refresh.
    """
    raw = new_refresh_token()
    doc = {
        "tenant": tenant,
        "user_id": user_id,
        "device_id": device_id or "unknown",
        "scope": scope,
        "allowed_students": allowed_students or [],
        "auth_time": auth_time if auth_time is not None else _epoch(),
        "label": label,
        "refresh_token_hash": hash_refresh_token(raw),
        "issued_at": _now(),
        "expires_at": refresh_expiry(),
        "rotated_from": None,
        "rotation_count": 0,
        "revoked": False,
        "user_agent": user_agent,
    }
    res = await db.sessions.insert_one(doc)
    return str(res.inserted_id), raw


async def _get_children(db: AsyncIOMotorDatabase, *, tenant: str, parent_id: str) -> list[dict]:
    """Linked child profiles for a parent (active links only)."""
    links = db.parent_links.find({"tenant": tenant, "parent_id": parent_id, "status": "active"})
    children: list[dict] = []
    async for link in links:
        sid = link.get("student_id")
        child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": sid})
        if not child:
            continue
        children.append({
            "student_id": sid,
            "name": child.get("name"),
            "class_no": child.get("class_no"),
            "section": child.get("section"),
            "avatar": child.get("avatar"),
            "mascot": child.get("mascot"),
            "has_pin": bool(child.get("pin_hash")),
        })
    return children


# --- token issuance -----------------------------------------------------------

async def _issue_for_user(
    db: AsyncIOMotorDatabase,
    user: dict,
    *,
    device_id: Optional[str],
    user_agent: Optional[str],
    ip: Optional[str] = None,
) -> dict:
    """Issue a fresh access+refresh pair for a directly-authenticated user."""
    tenant = user["tenant"]
    user_id = str(user["_id"])
    role = user["role"]

    sct = user.get("student_id") if role == "student" else None
    mode = _student_mode(user) if role == "student" else None
    children = None
    kids = None
    if role == "parent":
        children = await _get_children(db, tenant=tenant, parent_id=user_id)
        kids = [c["student_id"] for c in children]

    auth_time = _epoch()  # strong login now
    sid, raw_refresh = await _create_session(
        db, tenant=tenant, user_id=user_id, device_id=device_id, user_agent=user_agent,
        scope="full", auth_time=auth_time,
    )
    access = create_access_token(
        sub=user_id, role=role, tenant=tenant, sid=sid, sct=sct, kids=kids,
        auth_time=auth_time, mode=mode,
    )
    await _audit(db, tenant=tenant, actor_id=user_id, action=f"login.{role}", ip=ip)

    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": _ACCESS_TTL_SECONDS,
        "role": role,
        "tenant": tenant,
        "user": _user_public(user),
        "children": children,
    }


# --- login methods ------------------------------------------------------------

async def password_login(
    db: AsyncIOMotorDatabase,
    *,
    identifier: str,
    password: str,
    device_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Email/phone + password for teacher / admin / superadmin (SPEC §8)."""
    ident = identifier.strip().lower()
    user = await db.users.find_one({
        "$or": [{"email": ident}, {"phone": identifier.strip()}, {"phone": otp_service.normalize_phone(identifier)}],
        "role": {"$in": ["teacher", "admin", "superadmin"]},
    })
    if not user or not verify_secret(password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return await _issue_for_user(db, user, device_id=device_id, user_agent=user_agent, ip=ip)


async def student_login(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    student_code: str,
    pin: str,
    device_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """School-issued device path: opaque student_code + PIN, with lockout (§3.5)."""
    code = student_code.strip().upper()
    user = await db.users.find_one({"tenant": tenant, "role": "student", "student_code": code})
    # Uniform error so a wrong code is indistinguishable from a wrong PIN.
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code or PIN")
    if not user:
        raise invalid

    locked_until = _aware(user.get("locked_until"))
    if locked_until and locked_until > _now():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account locked. Ask your parent or school to reset your PIN.",
        )

    if not verify_secret(pin, user.get("pin_hash")):
        await _register_failed_attempt(db, user)
        await _audit(db, tenant=tenant, actor_id=str(user["_id"]), action="login.student.fail", ip=ip)
        raise invalid

    # success — clear lockout counters
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"failed_attempts": 0, "locked_until": None, "first_login_at": user.get("first_login_at") or _now()}},
    )
    return await _issue_for_user(db, user, device_id=device_id, user_agent=user_agent, ip=ip)


async def _register_failed_attempt(db: AsyncIOMotorDatabase, user: dict) -> None:
    attempts = int(user.get("failed_attempts", 0)) + 1
    update: dict[str, Any] = {"failed_attempts": attempts}
    if attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
        from datetime import timedelta
        update["locked_until"] = _now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MIN)
        update["failed_attempts"] = 0  # reset counter; lockout now gates further tries
    await db.users.update_one({"_id": user["_id"]}, {"$set": update})


async def parent_otp_login(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    phone: str,
    code: str,
    device_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Verify the parent's phone OTP and issue a parent session (SPEC §3.3)."""
    ok = await otp_service.verify_otp(db, tenant=tenant, phone=phone, code=code)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")
    norm = otp_service.normalize_phone(phone)
    user = await db.users.find_one({"tenant": tenant, "role": "parent", "phone": norm})
    if not user:
        # Parent verified a phone but isn't onboarded yet — claim flow is P2.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No parent account for this number. Ask your school for an invite.",
        )
    if user.get("status") == "suspended":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return await _issue_for_user(db, user, device_id=device_id, user_agent=user_agent, ip=ip)


# --- family mode --------------------------------------------------------------

async def family_switch(
    db: AsyncIOMotorDatabase,
    *,
    parent_claims: dict,
    student_id: str,
    pin: Optional[str],
    ip: Optional[str] = None,
) -> dict:
    """Parent → kid-mode access token for a linked child (SPEC §3.3).

    Reuses the parent's session (``sid``) — no new refresh token. The child PIN,
    if set, is a *soft* sibling separator (low-stakes — access is already gated
    by the parent's authenticated device, §3.5).
    """
    tenant = parent_claims["tenant"]
    parent_id = parent_claims["sub"]
    sid = parent_claims["sid"]

    link = await db.parent_links.find_one({
        "tenant": tenant, "parent_id": parent_id, "student_id": student_id, "status": "active",
    })
    if not link:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your child")

    child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": student_id})
    if not child:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Child profile not found")

    if child.get("pin_hash"):
        if not pin or not verify_secret(pin, child.get("pin_hash")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong profile PIN")

    access = create_access_token(
        sub=str(child["_id"]), role="student", tenant=tenant, sid=sid,
        sct=student_id, pid=parent_id,
        auth_time=parent_claims.get("auth_time"), mode=_student_mode(child),
    )
    await _audit(db, tenant=tenant, actor_id=parent_id, action="family.switch", target=student_id, ip=ip)
    return {
        "access_token": access,
        "refresh_token": None,  # parent session/refresh persists
        "token_type": "bearer",
        "expires_in": _ACCESS_TTL_SECONDS,
        "role": "student",
        "tenant": tenant,
        "user": _user_public(child),
        "children": None,
    }


# --- refresh / logout ---------------------------------------------------------

async def refresh(
    db: AsyncIOMotorDatabase,
    *,
    refresh_token: str,
    student_id: Optional[str] = None,
    device_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Rotate the refresh token and mint a fresh access token (SPEC §5).

    ``sid`` is stable across rotations. If ``student_id`` is given and the
    session belongs to a parent linked to that child, returns a kid-mode access
    token directly (so the app lands back in the last-used profile)."""
    token_hash = hash_refresh_token(refresh_token)
    sess = await db.sessions.find_one({"refresh_token_hash": token_hash})
    bad = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if not sess or sess.get("revoked"):
        raise bad
    if _aware(sess.get("expires_at")) and _aware(sess["expires_at"]) < _now():
        raise bad

    tenant = sess["tenant"]
    sid = str(sess["_id"])
    scope = sess.get("scope", "full")
    auth_time = sess.get("auth_time")

    # rotate the refresh token in place (sid stays stable)
    new_raw = new_refresh_token()
    await db.sessions.update_one(
        {"_id": sess["_id"]},
        {"$set": {
            "refresh_token_hash": hash_refresh_token(new_raw),
            "rotated_from": token_hash,
            "issued_at": _now(),
            "expires_at": refresh_expiry(),
        }, "$inc": {"rotation_count": 1}},
    )

    # --- DEVICE session: can ONLY mint a student token, never a parent token ---
    if scope == "device":
        allowed = sess.get("allowed_students") or []
        target = student_id or sess.get("pinned_student_id") or (allowed[0] if allowed else None)
        if not target or (allowed and target not in allowed):
            raise bad
        child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": target})
        if not child:
            raise bad
        access = create_access_token(
            sub=str(child["_id"]), role="student", tenant=tenant, sid=sid,
            sct=target, did=sess.get("device_id"), auth_time=auth_time,
            mode=_student_mode(child),
        )
        return {
            "access_token": access, "refresh_token": new_raw, "token_type": "bearer",
            "expires_in": _ACCESS_TTL_SECONDS, "role": "student", "tenant": tenant,
            "user": _user_public(child), "children": None,
        }

    # --- FULL session: mints the owning user's own role token ------------------
    user = await db.users.find_one({"_id": ObjectId(sess["user_id"])})
    if not user or user.get("status") == "suspended":
        raise bad
    role = user["role"]

    # Optionally land straight back into kid mode (parent staying in a child).
    if student_id and role == "parent":
        link = await db.parent_links.find_one({
            "tenant": tenant, "parent_id": str(user["_id"]),
            "student_id": student_id, "status": "active",
        })
        child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": student_id}) if link else None
        if child:
            access = create_access_token(
                sub=str(child["_id"]), role="student", tenant=tenant, sid=sid,
                sct=student_id, pid=str(user["_id"]), auth_time=auth_time,
                mode=_student_mode(child),
            )
            return {
                "access_token": access, "refresh_token": new_raw, "token_type": "bearer",
                "expires_in": _ACCESS_TTL_SECONDS, "role": "student", "tenant": tenant,
                "user": _user_public(child), "children": None,
            }

    sct = user.get("student_id") if role == "student" else None
    mode = _student_mode(user) if role == "student" else None
    children = None
    kids = None
    if role == "parent":
        children = await _get_children(db, tenant=tenant, parent_id=str(user["_id"]))
        kids = [c["student_id"] for c in children]
    access = create_access_token(
        sub=str(user["_id"]), role=role, tenant=tenant, sid=sid, sct=sct, kids=kids,
        auth_time=auth_time, mode=mode,
    )
    return {
        "access_token": access, "refresh_token": new_raw, "token_type": "bearer",
        "expires_in": _ACCESS_TTL_SECONDS, "role": role, "tenant": tenant,
        "user": _user_public(user), "children": children,
    }


async def logout(db: AsyncIOMotorDatabase, *, refresh_token: str) -> None:
    """Revoke the session backing a refresh token (SPEC §5)."""
    token_hash = hash_refresh_token(refresh_token)
    sess = await db.sessions.find_one({"refresh_token_hash": token_hash})
    if sess:
        await db.sessions.update_one({"_id": sess["_id"]}, {"$set": {"revoked": True}})
        await _audit(db, tenant=sess.get("tenant", ""), actor_id=sess.get("user_id"), action="logout")


async def get_children_for_parent(db: AsyncIOMotorDatabase, *, tenant: str, parent_id: str) -> list[dict]:
    return await _get_children(db, tenant=tenant, parent_id=parent_id)


def pre_login_tenant(explicit: Optional[str], header: Optional[str]) -> str:
    """Tenant for pre-login flows (OTP) where there's no token yet (SPEC §3.0)."""
    tenant = explicit or header
    if tenant:
        return tenant
    if settings.is_production():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant required")
    return "demo-school"


async def resolve_tenant_by_code(db: AsyncIOMotorDatabase, *, school_code: str) -> dict:
    """One-time helper: human school code → tenant the app then remembers (§3.0)."""
    t = await db.tenants.find_one({"school_code": school_code.strip().upper()})
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return {"tenant": t["tenant"], "name": t.get("name"), "board": t.get("board")}
