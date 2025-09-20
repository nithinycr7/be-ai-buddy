from fastapi import APIRouter, Depends, HTTPException

from ..models.school import SchoolCreate
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.mongo import get_db
from app.services.school import SchoolService

router = APIRouter(prefix="/schools", tags=["Schools"])


def get_school_service(db: AsyncIOMotorDatabase = Depends(get_db)):
    return SchoolService(db)

@router.post("/", response_model=dict)
async def create_school(payload: SchoolCreate,service: SchoolService = Depends(get_school_service) ):
     result = await service.create_school(payload)
     if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
     return result


@router.get("/")
async def list_schools(
    service: SchoolService = Depends(get_school_service)
):
    schools = await service.get_schools()
    return {"schools": schools}