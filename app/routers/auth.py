from fastapi import APIRouter, Depends, HTTPException
from datetime import timedelta
from app.schemas.auth import LoginRequest, LoginResponse, UserRole
from app.auth.password_handler import verify_password
from app.auth.jwt_handler import create_access_token

import os
from ..db.mongo import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])

USER_ID_ROLES = {UserRole.teacher, UserRole.student}
EMAIL_ROLES = {UserRole.parent, UserRole.admin, UserRole.superadmin}

# @router.post("/login", response_model=LoginResponse)
# async def login(data: LoginRequest):
#     db = await get_db()
#     user = db.users.find_one({"email": data.email})
#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     if not verify_password(data.password, user["password"]):
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     # Build JWT payload
#     token_data = {
#         "userId": str(user["_id"]),
#         "schoolId": str(user.get("schoolId")),
#         "roles": user.get("roles", []),
#     }

#     access_token = create_access_token(
#         data=token_data, expires_delta=timedelta(minutes=60)
#     )

#     return LoginResponse(access_token=access_token)


@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest):
    db = await get_db()

    identifier = data.identifier
    password = data.password
    
     # Find user by user_id or email depending on role
    user = await db.users.find_one({
        "$or": [
            {"user_id": identifier, "roles": {"$in": list(USER_ID_ROLES)}},
            {"email": identifier, "roles": {"$in": list(EMAIL_ROLES)}}
        ]
     })


    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # verify password
    if not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Build JWT payload
    token_data = {
        "userId": str(user["_id"]),
        "schoolId": str(user.get("schoolId")),
        "roles": user.get("roles", []),
    }

    access_token = create_access_token(data=token_data, expires_delta=timedelta(minutes=60))
    return LoginResponse(access_token=access_token)