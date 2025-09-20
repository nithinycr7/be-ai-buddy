from jose import jwt, JWTError, ExpiredSignatureError
from datetime import datetime, timedelta
from typing import Dict
from app.core.config import settings


def create_access_token(data: Dict, expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token with an expiration time.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.JWT_TTL))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
    return encoded_jwt


def decode_access_token(token: str) -> Dict:
    """
    Decode and validate a JWT access token.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        return payload
    except ExpiredSignatureError:
        raise ValueError("Token expired")
    except JWTError:
        raise ValueError("Invalid token")
