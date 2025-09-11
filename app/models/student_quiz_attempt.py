
from pydantic import BaseModel, Field
from typing import Optional, List
from app.utils.objectid import PyObjectId   # ✅ import from utils
from datetime import datetime
from utils.datetime import utc_now


class QuestionAttempt(BaseModel):
    question_id: PyObjectId = Field(...)
    selected_option: str  # option id (like "a", "b", "c")
    is_correct: bool

class StudentQuizAttempt(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    student_id:str
    quiz_id: PyObjectId = Field(..., description="Reference to the Quiz _id")
    attempt:List[QuestionAttempt]=[]
    score:int=0
    submitted_at: datetime = Field(default_factory=utc_now)
