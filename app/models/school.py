from datetime import datetime
from app.utils.datetime import utc_now
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# -------- SCHOOL --------
class SchoolBase(BaseModel):
    school_id: str
    name: str
    address: str
    license_type: str
    max_students: int
    license_expiry: datetime

class SchoolCreate(SchoolBase):
    pass

class SchoolInDB(SchoolBase):
    created_at:datetime = Field(default_factory=utc_now)
