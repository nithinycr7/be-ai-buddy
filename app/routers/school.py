from fastapi import APIRouter, Depends, HTTPException

from ..models.school import SchoolCreate
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.mongo import get_db
from app.services.school import SchoolService
from app.dependencies import get_school_service, get_user_service 


router = APIRouter(prefix="/schools", tags=["Schools"])


@router.post("/", response_model=dict)
async def create_school(
    payload: SchoolCreate, # Use the injected service instance, which now has the UserService attached
    service: SchoolService = Depends(get_school_service) 
      ):
     result = await service.create_school(payload)
    
    # Use 'message' from your service, or check the result structure
     if not result or "message" not in result: 
        raise HTTPException(status_code=500, detail="School creation failed unexpectedly.")
        
     return result


@router.get("/")
async def list_schools(
    service: SchoolService = Depends(get_school_service)
):
    schools = await service.get_schools()
    return {"schools": schools}