
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any, Union
from app.utils.objectid import PyObjectId   # ✅ import from utils
from datetime import datetime
from utils.datetime import utc_now
from bson import ObjectId

class LecturePlan(BaseModel):
    lessonObjectives: List[str] = []
    preRequisites: List[str] = []
    teachingAids: List[str] = []
    stepwisePlan: Dict[str, str] = {}   # {"Period 1": "...", "Period 2": "..."}
    assessmentIdeas: List[str] = []


class QuickNotes(BaseModel):
    keyDefinitions: List[str] = []
    keywords: List[str] = []
    diagramsExamples: List[str] = []
    importantPoints: List[str] = []


# --- Main Lesson Plan ---
class LessonPlan(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    teacher_id: PyObjectId
    class_no: int = Field(..., ge=3, le=12)  # supports 3rd to 12th
    section: Optional[str] = None
    subject: str
    chapter: str
    periods: int= Field(..., ge=1)
    
    lecturePlan: Optional[LecturePlan] = None
    quickNotes: Optional[QuickNotes] = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str},  # serialize ObjectId to string
    }
