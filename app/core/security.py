from __future__ import annotations
from fastapi import Header, HTTPException, status, Depends
from .config import settings

async def api_key_guard(x_api_key: str | None = Header(default=None)):
    expected = settings.API_KEY_VALUE
    if not expected or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )
    return True

async def get_tenant(x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID")) -> str:
    """
    Extracts the tenant ID from the X-Tenant-ID header.

    In production a tenant header is REQUIRED (no cross-school fallback). In dev we
    default to 'demo-school' so the demo keeps working without the header.
    """
    if x_tenant_id:
        return x_tenant_id
    if settings.is_production():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required X-Tenant-ID header",
        )
    return "demo-school"
