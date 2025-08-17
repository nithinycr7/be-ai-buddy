from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum
from app.utils.datetime import utc_now
from app.utils.objectid import PyObjectId   # ✅ import from utils
from bson import ObjectId

class QuestionType(str,Enum):
    MCQ="MCQ"
    TRUE_FALSE = "TRUE_FALSE"
    FILL_BLANK = "FILL_BLANK"
    MATCH = "MATCH"
    SHORT_ANSWER = "SHORT_ANSWER"

class QuizOption(BaseModel):
    id: str
    text: str


class Question(BaseModel):
    # id: Optional[str] = Field(default=None, alias="_id")
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    subject:str
    topic:str
    class_no: int = Field(..., ge=3, le=12)
    question_text: Union[str, dict]  # can be plain text or structured (like MATCH)
    options: Optional[List[QuizOption]] = None 
    correct_answer: Optional[Union[str, List[str], dict]] = None
    type: QuestionType
    created_at:  datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str}  # serialize ObjectId to string
    }
    # class Config:
    #     populate_by_name = True  # renamed from allow_population_by_field_name
    #     arbitrary_types_allowed = True
    #     model_serializer = {ObjectId: lambda v: str(v)}  # <--- this serializes ObjectId to string
