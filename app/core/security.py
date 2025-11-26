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

async def get_tenant(x_tenant_id: str = Header(default="demo-school", alias="X-Tenant-ID")) -> str:
    """
    Extracts the tenant ID from the X-Tenant-ID header.
    Defaults to 'demo-school' for development convenience.
    """
    return x_tenant_id
