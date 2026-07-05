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
from .notifications import get_email_sender, get_otp_sender

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


def _mask_email(email: str) -> Optional[str]:
    if not email or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    head = name[0] if name else "•"
    return f"{head}•••@{domain}"


async def create_invite(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    student_id: str,
    parent_email: Optional[str] = None,
    parent_phone: Optional[str] = None,
    relationship: str = "guardian",
    parent_name: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Create a pending invite for a roster student. Email is the priority contact;
    phone is the fallback — at least one is required. Returns ``{token, ...}``
    (the raw token goes in the invite link; only its hash is stored)."""
    email = otp_service.normalize_email(parent_email) if parent_email else None
    phone = otp_service.normalize_phone(parent_phone) if parent_phone else None
    if not email and not phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="An email or phone is required to invite a parent")
    token = generate_opaque_token(24)
    doc = {
        "tenant": tenant,
        "student_id": student_id,
        "parent_email": email,
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
    return {"token": token, "tenant": tenant, "student_id": student_id,
            "parent_email": email, "parent_phone": phone}


async def send_invite(db: AsyncIOMotorDatabase, *, token: str, tenant: str,
                      parent_email: Optional[str], parent_phone: Optional[str],
                      base_url: str) -> dict:
    """Deliver the invite link — EMAIL FIRST, SMS fallback. Delivery goes through
    the notifications senders (dev-echo/null until a provider is wired)."""
    link = f"{base_url.rstrip('/')}/auth/invite/{token}"
    if parent_email:
        await get_email_sender().send(
            to=otp_service.normalize_email(parent_email),
            subject="Your child is invited to MyMedha",
            body=f"Tap to set up your account and follow your child's learning: {link}",
        )
        return {"sent": True, "channel": "email"}
    if parent_phone:
        # No SMS body sender for links yet; reuse the OTP sender's channel as the
        # delivery point (dev-echo logs it). A real SMS gateway lands in notifications.
        await get_otp_sender().send(phone=otp_service.normalize_phone(parent_phone), code=link)
        return {"sent": True, "channel": "sms"}
    return {"sent": False, "channel": None}


async def send_invite_otp(db: AsyncIOMotorDatabase, *, token: str) -> dict:
    """Send an OTP to the invite's OWN stored contact (email priority). The client
    passes only the token — the full email/phone never leaves the server, so the
    onboarding screen can offer one-tap 'Send code' against a masked contact with
    no PII exposure. Returns only channel + masked (+ dev_otp in non-prod)."""
    inv = await _load_invite(db, token)
    inv_email = inv.get("parent_email")
    inv_phone = inv.get("parent_phone")
    if inv_email:
        identifier, channel, masked = otp_service.normalize_email(inv_email), "email", _mask_email(inv_email)
    elif inv_phone:
        identifier, channel, masked = otp_service.normalize_phone(inv_phone), "sms", _mask_phone(inv_phone)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This invitation has no contact on file")
    res = await otp_service.request_otp(db, tenant=inv["tenant"], identifier=identifier, channel=channel)
    out = {"sent": True, "channel": channel, "masked": masked, "expires_in": res.get("expires_in")}
    if res.get("dev_otp"):  # non-prod only; never the full identifier
        out["dev_otp"] = res["dev_otp"]
    return out


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
    inv_email = inv.get("parent_email")
    inv_phone = inv.get("parent_phone")
    child = await db.users.find_one({"tenant": tenant, "role": "student", "student_id": inv["student_id"]})
    school = await db.tenants.find_one({"tenant": tenant})
    # An existing parent may be found by either contact on the invite.
    existing_parent = None
    if inv_email:
        existing_parent = await db.users.find_one({"tenant": tenant, "role": "parent", "email": inv_email})
    if not existing_parent and inv_phone:
        existing_parent = await db.users.find_one({"tenant": tenant, "role": "parent", "phone": inv_phone})
    already_linked = False
    if existing_parent and child:
        already_linked = bool(await db.parent_links.find_one({
            "tenant": tenant, "parent_id": str(existing_parent["_id"]),
            "student_id": inv["student_id"], "status": "active",
        }))
    # Email-first: default_channel tells the UI which to verify with.
    default_channel = "email" if inv_email else ("sms" if inv_phone else None)
    return {
        "status": inv.get("status"),
        "tenant": tenant,
        "school_name": (school or {}).get("name"),
        # Masked only — the full contact never leaves the server (it's PII behind a
        # public bearer link). The onboarding screen confirms the masked value and
        # the OTP is sent server-side via send_invite_otp (no typing, no leak).
        "parent_email_masked": _mask_email(inv_email) if inv_email else None,
        "parent_phone_masked": _mask_phone(inv_phone) if inv_phone else None,
        "default_channel": default_channel,
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


async def _find_or_create_parent(db, *, tenant: str, email: Optional[str],
                                 phone: Optional[str], name: Optional[str]) -> dict:
    """Idempotent by (tenant, email) first, then (tenant, phone). If found by one
    contact and the invite carries the other, backfill the missing contact so the
    parent record accumulates both — no duplicate parents."""
    email = otp_service.normalize_email(email) if email else None
    phone = otp_service.normalize_phone(phone) if phone else None

    parent = None
    if email:
        parent = await db.users.find_one({"tenant": tenant, "role": "parent", "email": email})
    if not parent and phone:
        parent = await db.users.find_one({"tenant": tenant, "role": "parent", "phone": phone})

    if parent:
        backfill = {}
        if email and not parent.get("email"):
            backfill["email"] = email
        if phone and not parent.get("phone"):
            backfill["phone"] = phone
        if backfill:
            await db.users.update_one({"_id": parent["_id"]}, {"$set": backfill})
            parent.update(backfill)
        return parent

    doc = {
        "tenant": tenant, "role": "parent", "status": "active",
        "email": email, "phone": phone, "name": name,
        "failed_attempts": 0, "locked_until": None, "created_at": _now(),
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
    identifier: Optional[str] = None,
    code: str,
    relationship: Optional[str] = None,
    device_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Unauthenticated claim: verify OTP → find-or-create parent → link child →
    issue a parent session. Idempotent (a second invite adds another child).
    ``identifier`` is optional: when omitted (the confirm-masked path), the invite's
    OWN stored contact is used (email priority). When provided (the 'use a different
    contact' path), it must match the invite's email or phone."""
    inv = await _load_invite(db, token)
    tenant = inv["tenant"]
    inv_email = otp_service.normalize_email(inv["parent_email"]) if inv.get("parent_email") else None
    inv_phone = inv.get("parent_phone")

    if identifier:
        norm, channel = otp_service.normalize_identifier(identifier)
        matches = (channel == "email" and inv_email and norm == inv_email) or \
                  (channel == "sms" and inv_phone and norm == inv_phone)
        if not matches:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="This doesn't match the school invitation.")
    elif inv_email:
        norm, channel = inv_email, "email"
    elif inv_phone:
        norm, channel = otp_service.normalize_phone(inv_phone), "sms"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This invitation has no contact on file")
    if not await otp_service.verify_otp(db, tenant=tenant, identifier=norm, code=code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")

    if relationship:
        inv["relationship"] = relationship
    # Carry BOTH invite contacts onto the parent, regardless of which was verified.
    parent = await _find_or_create_parent(db, tenant=tenant, email=inv_email,
                                          phone=inv_phone, name=inv.get("parent_name"))
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
    p_email = otp_service.normalize_email(parent.get("email") or "")
    p_phone = otp_service.normalize_phone(parent["phone"]) if parent.get("phone") else ""
    inv_email = otp_service.normalize_email(inv["parent_email"]) if inv.get("parent_email") else ""
    inv_phone = inv.get("parent_phone") or ""
    if not ((inv_email and p_email == inv_email) or (inv_phone and p_phone == inv_phone)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This invitation was sent to a different contact.")

    if relationship:
        inv["relationship"] = relationship
    await _link_child(db, tenant=tenant, parent_id=parent_id, invite=inv, method="authenticated")
    await auth_service._audit(db, tenant=tenant, actor_id=parent_id,
                              action="parent.claim.authed", target=inv["student_id"], ip=ip)
    children = await auth_service.get_children_for_parent(db, tenant=tenant, parent_id=parent_id)
    return {"linked": inv["student_id"], "children": children}
