
from fastapi import APIRouter, Depends, HTTPException, Body
from app.db.mongo import get_db
from app.core.security import get_tenant, require_role
from app.services.manual_quiz_service import ManualQuizService
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(dependencies=[Depends(require_role("teacher", "admin"))])

class CustomQuizRequest(BaseModel):
    source: str = "custom" # custom | textbook
    class_no: int
    subject: str
    board: str = "CBSE"
    difficulty: str = "medium"
    num_questions: int = 10
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    topics: List[str] = []
    tenant: str = "default" # TODO: get from auth
    teacher_id: Optional[str] = None

@router.post("/custom")
async def generate_custom_quiz(payload: CustomQuizRequest, db=Depends(get_db), tenant: str = Depends(get_tenant)):
    service = ManualQuizService(db)
    try:
        data = payload.dict()
        data["tenant"] = tenant  # header wins over any body value
        quiz = await service.create_and_save_quiz(data)
        return quiz
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[dict])
async def list_quizzes(
    class_no: Optional[int] = None,
    subject: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    tenant: str = Depends(get_tenant)
):
    query = {"tenant": tenant}
    if class_no:
        query["class_no"] = class_no
    if subject:
        query["subject"] = subject
        
    cursor = db.quizzes.find(query).sort("created_at", -1).limit(limit)
    quizzes = await cursor.to_list(length=limit)
    
    # Map _id to id
    # Map _id to id and handle ObjectId serialization
    results = []
    for q in quizzes:
        q["id"] = str(q["_id"])
        if "_id" in q:
            del q["_id"]
        
        # Check other potential ObjectId fields
        if "daily_id" in q and hasattr(q["daily_id"], "__str__"): # Check if it's not a primitive
             q["daily_id"] = str(q["daily_id"])
             
        results.append(q)
        
    return results
