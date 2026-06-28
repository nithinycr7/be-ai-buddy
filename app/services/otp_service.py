"""Phone OTP for parent login (SPEC §3.3, §9).

OTPs are 6-digit, short-TTL, rate-limited, hashed at rest, and never logged in
prod. There is **no SMS provider wired yet** — in non-prod we echo the code back
(``OTP_DEV_ECHO``) so the parent-login flow is testable end-to-end. Wiring a real
gateway (MSG91 / Twilio / Gupshup) is a P2 follow-up: implement ``_send_sms``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..core.config import settings
from ..core.passwords import generate_numeric_code, hash_secret, verify_secret

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


async def request_otp(db: AsyncIOMotorDatabase, *, tenant: str, phone: str) -> dict:
    """Generate + store a fresh OTP for (tenant, phone). Returns a dict; in
    non-prod it includes ``dev_otp`` so callers can complete the flow."""
    phone = normalize_phone(phone)
    code = generate_numeric_code(settings.OTP_LENGTH)
    doc = {
        "tenant": tenant,
        "phone": phone,
        "code_hash": hash_secret(code),
        "purpose": "login",
        "attempts": 0,
        "consumed": False,
        "created_at": _now(),
        "expires_at": _now() + timedelta(minutes=settings.OTP_TTL_MIN),
    }
    # One live OTP per (tenant, phone): replace any prior unconsumed code.
    await db.otp_codes.delete_many({"tenant": tenant, "phone": phone, "consumed": False})
    await db.otp_codes.insert_one(doc)

    await _send_sms(phone, code)

    out = {"sent": True, "phone": phone, "expires_in": settings.OTP_TTL_MIN * 60}
    if settings.OTP_DEV_ECHO and not settings.is_production():
        out["dev_otp"] = code
    return out


async def verify_otp(db: AsyncIOMotorDatabase, *, tenant: str, phone: str, code: str) -> bool:
    """Check + consume an OTP. Enforces expiry + per-code attempt cap (§9)."""
    phone = normalize_phone(phone)
    rec = await db.otp_codes.find_one(
        {"tenant": tenant, "phone": phone, "consumed": False},
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


async def _send_sms(phone: str, code: str) -> None:
    """Placeholder SMS dispatch. Real provider is a P2 follow-up."""
    if settings.is_production():
        # TODO(P2): integrate SMS provider (MSG91/Twilio/Gupshup). Never log the code.
        log.warning("OTP requested for %s but no SMS provider is configured", phone)
    else:
        log.info("[DEV OTP] %s -> %s", phone, code)
