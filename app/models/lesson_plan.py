
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any, Union
from app.utils.objectid import PyObjectId   # ✅ import from utils
from datetime import datetime
from utils.datetime import utc_now
from bson import ObjectId

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.utils.objectid import PyObjectId
from datetime import datetime
from utils.datetime import utc_now
from bson import ObjectId

# --- Core Plan Content ---
class PlanContent(BaseModel):
    learning_outcomes: str = ""
    warmup: str = ""
    explanation: str = ""
    activities: str = ""
    practice: str = ""
    assessment: str = ""
    homework: str = ""
    reflection: str = ""

# --- 1. Drafts (Temporary) ---
class LecturePlanDraft(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    teacher_id: str
    class_no: int
    subject: str
    chapter: str
    
    plan: PlanContent
    
    is_saved: bool = False
    status: str = "draft" # draft, editing, completed
    
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str},
    }

# --- 2. Saved Plans (Permanent) ---
class LecturePlanSaved(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    teacher_id: str
    class_no: int
    subject: str
    chapter: str
    title: Optional[str] = None
    
    plan: PlanContent
    summary: Optional[str] = None
    
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str},
    }

# --- 3. Version History ---
class LecturePlanVersion(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    draft_id: str
    type: str # initial, edit
    
    sections_modified: List[str] = []
    prompt: Optional[str] = None
    
    previous_version: Optional[Dict[str, str]] = None # Only changed sections
    updated_version: Optional[Dict[str, str]] = None # Only changed sections
    
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {ObjectId: str},
    }
