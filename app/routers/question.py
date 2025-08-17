

from fastapi import APIRouter,Depends,HTTPException
from ..db.mongo import get_db
from app.services.question import QuestionService
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.question import Question


router = APIRouter(prefix="/questions", tags=["Question"])


def get_question_service(db: AsyncIOMotorDatabase = Depends(get_db)):
    return QuestionService(db)


@router.post("/", response_model=Question)
async def create_question(question: Question, service: QuestionService = Depends(get_question_service)):
   
    question_dict = question.model_dump(by_alias=True)  # Convert Pydantic model → dict
    created_question = await service.create_question(question_dict)
    return created_question

@router.get("/")
async def list_questions(service: QuestionService = Depends(get_question_service)):
       return await service.get_all_questions()