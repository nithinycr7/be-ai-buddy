"""OTP for parent auth by EMAIL or PHONE (SPEC §3.3, §9).

OTPs are 6-digit, short-TTL, rate-limited, hashed at rest, and never logged in
prod. Delivery goes through the notifications abstraction — email-first is the
caller's choice via ``resolve_identifier``. No real SMS/email provider is wired
yet (dev-echo in non-prod, null in prod); wiring one is a P2 in ``notifications``.

The stored code is keyed by ``(tenant, identifier)`` where identifier is a
normalized email or phone, so the same machinery serves both channels.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.config import settings
from ..core.passwords import generate_numeric_code, hash_secret, verify_secret
from .notifications import get_email_sender, get_otp_sender

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone(phone: str) -> str:
    """Light normalization. Pilot rosters are India (+91); default the country
    code when a bare 10-digit number is supplied."""
    p = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not p.startswith("+"):
        digits = p
        if len(digits) == 10:
            p = "+91" + digits
        else:
            p = "+" + digits
    return p


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _looks_like_email(value: str) -> bool:
    return "@" in (value or "")


def normalize_identifier(identifier: str, channel: Optional[str] = None) -> Tuple[str, str]:
    """(normalized_identifier, channel). Infers channel from the value if not given."""
    ch = channel or ("email" if _looks_like_email(identifier) else "sms")
    if ch == "email":
        return normalize_email(identifier), "email"
    return normalize_phone(identifier), "sms"


def resolve_identifier(*, email: Optional[str] = None, phone: Optional[str] = None) -> Tuple[str, str]:
    """Pick the delivery target — EMAIL FIRST, then phone. Returns (identifier, channel)."""
    if email:
        return normalize_email(email), "email"
    if phone:
        return normalize_phone(phone), "sms"
    raise ValueError("email or phone required")


async def request_otp(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    identifier: Optional[str] = None,
    channel: Optional[str] = None,
    phone: Optional[str] = None,  # legacy callers
) -> dict:
    """Generate + store a fresh OTP for (tenant, identifier) and deliver it via the
    channel's sender. In non-prod the result includes ``dev_otp``. Accepts a legacy
    ``phone=`` kwarg (treated as an sms identifier)."""
    if identifier is None:
        if not phone:
            raise ValueError("identifier or phone required")
        identifier, channel = normalize_phone(phone), "sms"
    else:
        identifier, channel = normalize_identifier(identifier, channel)

    code = generate_numeric_code(settings.OTP_LENGTH)
    doc = {
        "tenant": tenant,
        "identifier": identifier,
        "channel": channel,
        "code_hash": hash_secret(code),
        "purpose": "login",
        "attempts": 0,
        "consumed": False,
        "created_at": _now(),
        "expires_at": _now() + timedelta(minutes=settings.OTP_TTL_MIN),
    }
    # One live OTP per (tenant, identifier): replace any prior unconsumed code.
    await db.otp_codes.delete_many({"tenant": tenant, "identifier": identifier, "consumed": False})
    await db.otp_codes.insert_one(doc)

    if channel == "email":
        await get_email_sender().send(
            to=identifier,
            subject="Your MyMedha sign-in code",
            body=f"Your one-time code is {code}. It expires in {settings.OTP_TTL_MIN} minutes.",
        )
    else:
        await get_otp_sender().send(phone=identifier, code=code)

    out = {"sent": True, "channel": channel, "identifier": identifier,
           "expires_in": settings.OTP_TTL_MIN * 60}
    if settings.OTP_DEV_ECHO and not settings.is_production():
        out["dev_otp"] = code
    return out


async def verify_otp(
    db: AsyncIOMotorDatabase,
    *,
    tenant: str,
    code: str,
    identifier: Optional[str] = None,
    phone: Optional[str] = None,  # legacy callers
) -> bool:
    """Check + consume an OTP for (tenant, identifier). Enforces expiry + per-code
    attempt cap (§9). Accepts a legacy ``phone=`` kwarg."""
    if identifier is None:
        if not phone:
            return False
        identifier = normalize_phone(phone)
    else:
        identifier, _ = normalize_identifier(identifier)

    rec = await db.otp_codes.find_one(
        {"tenant": tenant, "identifier": identifier, "consumed": False},
        sort=[("created_at", -1)],
    )
    if not rec:
        return False
    if rec["expires_at"].replace(tzinfo=timezone.utc) < _now():
        return False
    if rec.get("attempts", 0) >= settings.OTP_MAX_ATTEMPTS:
        return False

    if not verify_secret(code, rec.get("code_hash")):
        await db.otp_codes.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        return False

    await db.otp_codes.update_one({"_id": rec["_id"]}, {"$set": {"consumed": True}})
    return True
