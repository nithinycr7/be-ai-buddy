"""Parent invitations + claim (SPEC §3.2, §8 onboarding).

An invite resolves to ``(school, child)`` and is sent to the roster's parent
phone. **Claiming is idempotent at the parent level — keyed by (tenant, phone):**
if the parent already exists we *add the child*; we never create a duplicate
parent. Each child gets its own DPDP consent record (`parent_links.consent`).

Two claim paths:
  - ``claim_with_otp`` — unauthenticated (first-time, or returning-not-signed-in):
    phone+OTP → find-or-create parent → link child → issue session.
  - ``claim_authenticated`` — a signed-in parent adding another child (step-up
    enforced at the router): validates phone match → link child.

Security: the claimed phone MUST match the invite's roster phone, so a leaked
link can't be claimed from a different number.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.passwords import generate_opaque_token
from ..core.tokens import hash_refresh_token
from . import auth_service, otp_service

log = logging.getLogger(__name__)

INVITE_TTL_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _mask_phone(phone: str) -> str:
    return phone[:3] + "•••••" + phone[-2:] if phone and len(phone) >= 5 else "•••••"


async def create_invite(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    student_id: str,
    parent_phone: str,
    relationship: str = "guardian",
    parent_name: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Create a pending invite for a roster student. Returns ``{token, ...}``
    (raw token goes in the SMS link; only its hash is stored)."""
    phone = otp_service.normalize_phone(parent_phone)
    token = generate_opaque_token(24)
    doc = {
        "tenant": tenant,
        "student_id": student_id,
        "parent_phone": phone,
        "parent_name": parent_name,
        "relationship": relationship,
        "token_hash": hash_refresh_token(token),
        "status": "pending",
        "created_by": created_by,
        "created_at": _now(),
        "expires_at": _now() + timedelta(days=INVITE_TTL_DAYS),
    }
    await db.invites.insert_one(doc)
    return {"token": token, "tenant": tenant, "student_id": student_id, "parent_phone": phone}


async def _load_invite(db: AsyncIOMotorDatabase, token: str) -> dict:
    inv = await db.invites.find_one({"token_hash": hash_refresh_token(token)})
    bad = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation")
    if not inv:
        raise bad
    if inv.get("status") == "revoked":
        raise bad
    if _aware(inv.get("expires_at")) and _aware(inv["expires_at"]) < _now():
        raise bad
    return inv


async def resolve_invite(db: AsyncIOMotorDatabase, *, token: str) -> dict:
    """Public: turn an invite token into displayable child + school info, and
    whether a parent account already exists for that phone (drives the UI copy
    'Set up your account' vs 'Add <child>')."""
    inv = await _load_invite(db, token)
    tenant = inv["tenant"]
    child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": inv["student_id"]})
    school = await db.tenants.find_one({"tenant": tenant})
    existing_parent = await db.users.find_one({"tenant": tenant, "role": "parent", "phone": inv["parent_phone"]})
    already_linked = False
    if existing_parent and child:
        already_linked = bool(await db.parent_links.find_one({
            "tenant": tenant, "parent_id": str(existing_parent["_id"]),
            "student_id": inv["student_id"], "status": "active",
        }))
    return {
        "status": inv.get("status"),
        "tenant": tenant,
        "school_name": (school or {}).get("name"),
        "parent_phone_masked": _mask_phone(inv["parent_phone"]),
        "existing_parent": bool(existing_parent),
        "already_linked": already_linked,
        "child": {
            "student_id": inv["student_id"],
            "name": (child or {}).get("name"),
            "class_no": (child or {}).get("class_no"),
            "section": (child or {}).get("section"),
            "mascot": (child or {}).get("mascot"),
        } if child else None,
    }


async def _find_or_create_parent(db, *, tenant: str, phone: str, name: Optional[str]) -> dict:
    parent = await db.users.find_one({"tenant": tenant, "role": "parent", "phone": phone})
    if parent:
        return parent
    doc = {
        "tenant": tenant, "role": "parent", "status": "active",
        "phone": phone, "name": name, "failed_attempts": 0, "locked_until": None,
        "created_at": _now(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def _link_child(db, *, tenant: str, parent_id: str, invite: dict, method: str) -> None:
    """Idempotent parent↔child link + per-child consent (DPDP)."""
    await db.parent_links.update_one(
        {"tenant": tenant, "parent_id": parent_id, "student_id": invite["student_id"]},
        {"$set": {
            "tenant": tenant, "parent_id": parent_id, "student_id": invite["student_id"],
            "relationship": invite.get("relationship", "guardian"), "status": "active",
            "consent": {"granted": True, "granted_at": _now(), "method": method,
                        "scope": ["learning", "progress"]},
        }, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    await db.invites.update_one(
        {"_id": invite["_id"]},
        {"$set": {"status": "claimed", "claimed_at": _now(), "claimed_by": parent_id}},
    )


async def claim_with_otp(
    db: AsyncIOMotorDatabase,
    *,
    token: str,
    phone: str,
    code: str,
    relationship: Optional[str] = None,
    device_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Unauthenticated claim: verify OTP → find-or-create parent → link child →
    issue a parent session. Idempotent (second invite just adds another child)."""
    inv = await _load_invite(db, token)
    tenant = inv["tenant"]
    norm = otp_service.normalize_phone(phone)
    if norm != inv["parent_phone"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This number doesn't match the school invitation.")
    if not await otp_service.verify_otp(db, tenant=tenant, phone=norm, code=code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")

    if relationship:
        inv["relationship"] = relationship
    parent = await _find_or_create_parent(db, tenant=tenant, phone=norm, name=inv.get("parent_name"))
    await _link_child(db, tenant=tenant, parent_id=str(parent["_id"]), invite=inv, method="otp")
    await auth_service._audit(db, tenant=tenant, actor_id=str(parent["_id"]),
                              action="parent.claim.otp", target=inv["student_id"], ip=ip)
    # fresh session reflecting the newly linked child
    return await auth_service._issue_for_user(db, parent, device_id=device_id, user_agent=user_agent, ip=ip)


async def claim_authenticated(
    db: AsyncIOMotorDatabase,
    *,
    parent_claims: dict,
    token: str,
    relationship: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """A signed-in parent adds another child (step-up enforced at the router)."""
    tenant = parent_claims["tenant"]
    parent_id = parent_claims["sub"]
    inv = await _load_invite(db, token)
    if inv["tenant"] != tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation is for a different school")

    parent = await db.users.find_one({"_id": ObjectId(parent_id)})
    if not parent or parent.get("role") != "parent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a parent account")
    if otp_service.normalize_phone(parent.get("phone", "")) != inv["parent_phone"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This invitation was sent to a different number.")

    if relationship:
        inv["relationship"] = relationship
    await _link_child(db, tenant=tenant, parent_id=parent_id, invite=inv, method="authenticated")
    await auth_service._audit(db, tenant=tenant, actor_id=parent_id,
                              action="parent.claim.authed", target=inv["student_id"], ip=ip)
    children = await auth_service.get_children_for_parent(db, tenant=tenant, parent_id=parent_id)
    return {"linked": inv["student_id"], "children": children}
