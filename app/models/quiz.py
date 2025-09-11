from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from utils.datetime import utc_now
from bson import ObjectId
from app.utils.objectid import PyObjectId   # ✅ import from utils

class Quiz(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    subject:str
    topic:str
    class_no: int = Field(..., ge=3, le=8)
    questions: List[str]
    created_at:  datetime = Field(default_factory=utc_now)
   
    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str}  # serialize ObjectId to string
    }