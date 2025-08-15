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
