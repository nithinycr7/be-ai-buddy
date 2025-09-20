from fastapi import APIRouter, Depends, HTTPException
from app.models.user import UserCreate
from app.services.user import UserService
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.mongo import get_db

router = APIRouter(prefix="/users", tags=["Users"])



def get_user_service(db: AsyncIOMotorDatabase = Depends(get_db)):
    return UserService(db)

@router.post("/", response_model=dict)
async def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
     result = await service.create_user(payload)
     if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
     return result


@router.get("/")
async def list_users(
    school_id: str,
    role: str = None,
    service: UserService = Depends(get_user_service)
):
    users = await service.get_users(school_id=school_id, role=role)
    return {"users": users}