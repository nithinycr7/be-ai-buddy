

from fastapi import APIRouter,Depends,HTTPException
from ..db.mongo import get_db
from app.services.quiz import QuizService
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel,Field

router = APIRouter(prefix="/quizzes", tags=["Quiz"])


def get_quiz_service(db: AsyncIOMotorDatabase = Depends(get_db)):
    return QuizService(db)

class QuizRequest(BaseModel):
    subject:str
    class_no: int = Field(..., ge=3, le=8)
    topic:str

@router.post("/",response_model=dict)
async def create_quiz(req:QuizRequest,service: QuizService = Depends(get_quiz_service)):

    result = await service.create_quiz_for_topic(subject=req.subject,topic=req.topic,class_no=req.class_no)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/")
async def list_quizzes(service: QuizService = Depends(get_quiz_service)):
     return await service.get_all_quizzes()

@router.get("/topic/{topic}")
async def get_quizzes_by_topic(topic: str, service: QuizService = Depends(get_quiz_service)):
    return await service.get_quizzes_by_topic(topic)