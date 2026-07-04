"""Auth dependencies (SPEC §6).

- ``api_key_guard`` — retained for **service-to-service** calls only (workers).
- ``get_current_user`` — verifies the JWT, returns the acting identity. Use on
  user-facing routes.
- ``require_role(...)`` — role gate built on ``get_current_user``.
- ``get_tenant`` — **token-aware with header fallback**. If a valid Bearer token
  is present, tenant comes from the (trustworthy) token; otherwise it falls back
  to the ``X-Tenant-ID`` header. This keeps existing routes working during the
  migration and automatically upgrades them to token-derived tenant once the
  frontend sends real tokens. (SPEC §10.)
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from .config import settings
from .exceptions import ForbiddenError
from .tokens import TokenError, decode_access_token


async def api_key_guard(x_api_key: str | None = Header(default=None)):
    expected = settings.API_KEY_VALUE
    if not expected or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return True


class CurrentUser:
    """The verified acting identity for a request.

    ``student_id`` is the business student id (``sct`` claim) — present for a
    student login *and* for a parent in kid/family mode. ``parent_id`` (``pid``)
    is set only in kid mode. ``kids`` lists a parent's linked students.
    """

    __slots__ = ("user_id", "role", "tenant", "sid", "student_id", "parent_id", "kids", "claims")

    def __init__(self, claims: dict):
        self.user_id: str = claims.get("sub")
        self.role: str = claims.get("role")
        self.tenant: str = claims.get("tenant")
        self.sid: Optional[str] = claims.get("sid")
        self.student_id: Optional[str] = claims.get("sct")
        self.parent_id: Optional[str] = claims.get("pid")
        self.kids: list[str] = claims.get("kids") or []
        self.claims = claims


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """Strict: require a valid access token. 401 otherwise."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not claims.get("tenant") or not claims.get("role"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    return CurrentUser(claims)


async def get_optional_user(authorization: str | None = Header(default=None)) -> Optional[CurrentUser]:
    """Lenient: return the user if a valid token is present, else ``None``.
    Used by ``get_tenant`` during the migration."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        return CurrentUser(decode_access_token(token))
    except TokenError:
        return None


def require_role(*roles: str):
    """Dependency factory: allow only the listed roles. Superadmin always passes."""
    allowed = set(roles)

    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role == "superadmin" or user.role in allowed:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires role: {', '.join(sorted(allowed))}",
        )

    return _guard


def require_fresh_auth(*roles: str):
    """Step-up (AAL) gate for sensitive actions — pairing a device, changing
    settings, recovery (SPEC review). Requires a *recent* strong auth: the
    token's ``auth_time`` must be within ``FRESH_AUTH_WINDOW_MIN``. A silently
    refreshed token does NOT advance ``auth_time``, so a stale session is forced
    to re-verify (re-OTP) before the action. Optionally also role-gates."""
    import time

    allowed = set(roles)

    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if allowed and user.role != "superadmin" and user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        auth_time = user.claims.get("auth_time")
        window = settings.FRESH_AUTH_WINDOW_MIN * 60
        if not isinstance(auth_time, (int, float)) or (time.time() - auth_time) > window:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="reauth_required",
                headers={"WWW-Authenticate": 'Bearer error="reauth_required"'},
            )
        return user

    return _guard


def assert_can_access_student(user: "CurrentUser", student_id: Optional[str]) -> None:
    """Resource ownership (SPEC §6.4): a student may only touch their OWN
    student_id; a parent only their linked children; teacher/admin/superadmin
    may act within their tenant (tenant isolation already enforced upstream)."""
    if not student_id:
        return
    if user.role == "student":
        if user.student_id != student_id:
            raise ForbiddenError("Not your data")
    elif user.role == "parent":
        if student_id not in (user.kids or []):
            raise ForbiddenError("Not your child")
    # teacher / admin / superadmin: allowed within tenant


async def get_tenant(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    user: Optional[CurrentUser] = Depends(get_optional_user),
) -> str:
    """Resolve the tenant for a request.

    Priority: (1) the verified token's tenant (trustworthy), (2) the
    ``X-Tenant-ID`` header (legacy clients + internal worker calls). In
    production a tenant is required from one of these — no cross-school fallback.
    In dev we default to ``demo-school`` so the demo keeps working.
    """
    if user and user.tenant:
        return user.tenant
    if x_tenant_id:
        return x_tenant_id
    if settings.is_production():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing tenant (token or X-Tenant-ID header required)",
        )
    return "demo-school"
