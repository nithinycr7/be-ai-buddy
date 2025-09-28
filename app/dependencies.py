# In your dependency file (e.g., dependencies.py)
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
# Assuming get_database() yields the db connection
from app.db.mongo import get_db

from app.services.user import UserService
from app.services.school import SchoolService


# 1. UserService Provider (Already correct)
def get_user_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> UserService:
    """Dependency injector for the UserService."""
    return UserService(db)

# 2. SchoolService Provider (NEW/MODIFIED)
def get_school_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    # Inject the UserService using its provider function
    user_service: UserService = Depends(get_user_service) 
) -> SchoolService:
    """Dependency injector for the SchoolService, injecting UserService."""
    # Pass BOTH dependencies to the SchoolService constructor
    return SchoolService(db, user_service)