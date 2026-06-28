"""JWT access tokens + opaque refresh tokens (SPEC §5).

- Access token: signed JWT, short-lived. Carries role + tenant so the hot path
  does **no DB lookup** for authz.
- Refresh token: opaque random string, long-lived + rotating, stored **hashed**
  in the ``sessions`` collection (never as a JWT). Hashing helper lives here so
  issuance + lookup agree on the algorithm.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from .config import settings
from .passwords import generate_opaque_token


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or wrong-typed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    sub: str,
    role: str,
    tenant: str,
    sid: str,
    sct: Optional[str] = None,
    kids: Optional[list[str]] = None,
    pid: Optional[str] = None,
    auth_time: Optional[int] = None,
    mode: Optional[str] = None,
    did: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """Issue a signed access JWT.

    Claims (SPEC §5): ``sub`` (acting user id), ``role``, ``tenant``, ``sid``
    (session id — stable across refresh rotations), ``sct`` (active student in
    kid/family mode), ``kids`` (a parent's linked students), ``pid`` (the parent
    behind a kid-mode session, for provenance/audit), ``auth_time`` (epoch secs
    of last *strong* auth — drives step-up), ``mode`` (content source:
    school|self), ``did`` (paired device id, when issued from a device session).
    """
    now = _now()
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "tenant": tenant,
        "sid": sid,
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
    }
    if sct is not None:
        payload["sct"] = sct
    if kids is not None:
        payload["kids"] = kids
    if pid is not None:
        payload["pid"] = pid
    if auth_time is not None:
        payload["auth_time"] = auth_time
    if mode is not None:
        payload["mode"] = mode
    if did is not None:
        payload["did"] = did
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature + expiry and return claims. Raises ``TokenError``."""
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALG],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid access token") from exc
    if claims.get("type") != "access":
        raise TokenError("not an access token")
    return claims


# --- Refresh tokens (opaque + hashed at rest) ---------------------------------

def new_refresh_token() -> str:
    """A fresh opaque refresh token to hand to the client (store only its hash)."""
    return generate_opaque_token(32)


def hash_refresh_token(token: str) -> str:
    """Deterministic hash for refresh-token lookup. SHA-256 is fine here: the
    token is high-entropy random, so we don't need a slow KDF (unlike PINs)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    return _now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
