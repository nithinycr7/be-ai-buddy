"""Credential hashing + generation (SPEC §9).

bcrypt for passwords *and* PINs (same KDF, per spec). All secrets are randomly
generated, never patterns (no 1234/DOB). Student login id is an opaque,
non-sequential code — never the roll number (SPEC §3.5).
"""
from __future__ import annotations

import secrets
import string

import bcrypt

# bcrypt has a hard 72-byte input limit; longer inputs are silently truncated.
_BCRYPT_MAX_BYTES = 72


def _prep(secret: str) -> bytes:
    return secret.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_secret(secret: str) -> str:
    """Hash a password or PIN. Returns the full bcrypt string (incl. salt)."""
    return bcrypt.hashpw(_prep(secret), bcrypt.gensalt()).decode("utf-8")


def verify_secret(secret: str, hashed: str | None) -> bool:
    """Constant-time verify of a password/PIN/OTP against its stored hash."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prep(secret), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Back-compat aliases — passwords and PINs use the same primitive.
hash_password = hash_secret
verify_password = verify_secret
hash_pin = hash_secret
verify_pin = verify_secret


def generate_pin(length: int = 4) -> str:
    """A random numeric PIN. Never sequential / never DOB-derived (SPEC §3.5)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_numeric_code(length: int = 6) -> str:
    """A random numeric code (e.g. OTP)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


# Unambiguous alphabet for printed login slips — no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_student_code(*, school_code: str, class_no: int | str, section: str) -> str:
    """Opaque, non-sequential student login id, e.g. ``DAVH-9A-7Q3K`` (SPEC §3.1).

    The school/class/section prefix is for human filing only; the entropy is the
    trailing random block, which is what defeats "guess the next id" (SPEC §3.5).
    """
    prefix = "".join(c for c in school_code.upper() if c.isalnum())[:4] or "SCH"
    rand = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"{prefix}-{class_no}{section}-{rand}".upper()


def generate_opaque_token(nbytes: int = 32) -> str:
    """URL-safe opaque token (refresh tokens, QR/invite tokens)."""
    return secrets.token_urlsafe(nbytes)
