from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from app.auth.jwt_handler import decode_access_token

security = HTTPBearer()

class RBACMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, required_roles: dict):
        super().__init__(app)
        self.required_roles = required_roles  # { "/lessons": ["TEACHER", "STUDENT"] }

    async def dispatch(self, request: Request, call_next):
        # Skip unprotected routes (e.g., login, healthcheck)
        if request.url.path.startswith("/auth") or request.url.path.startswith("/docs"):
            return await call_next(request)

        # Extract JWT
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authorization token missing")

        token = auth_header.split(" ")[1]

        try:
            payload = decode_access_token(token)
            request.state.user = payload
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e))

        # Check roles against endpoint requirement
        required_roles = self.required_roles.get(request.url.path, [])
        user_roles = payload.get("roles", [])

        if required_roles and not any(role in user_roles for role in required_roles):
            raise HTTPException(status_code=403, detail="Forbidden: Insufficient role")

        return await call_next(request)
