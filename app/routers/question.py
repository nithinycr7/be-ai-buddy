from __future__ import annotations


from fastapi import APIRouter,Depends,HTTPException
from ..db.mongo import get_db
from ..core.security import api_key_guard, get_tenant
from app.services.question import QuestionService
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.question import Question


router = APIRouter(prefix="/questions", tags=["Question"], dependencies=[Depends(api_key_guard)])


def get_question_service(db: AsyncIOMotorDatabase = Depends(get_db)):
    return QuestionService(db)


@router.post("/", response_model=Question)
async def create_question(question: Question, service: QuestionService = Depends(get_question_service), tenant: str = Depends(get_tenant)):

    question_dict = question.model_dump(by_alias=True)  # Convert Pydantic model → dict
    created_question = await service.create_question(question_dict, tenant=tenant)
    return created_question

@router.get("/")
async def list_questions(service: QuestionService = Depends(get_question_service), tenant: str = Depends(get_tenant)):
       return await service.get_all_questions(tenant=tenant)