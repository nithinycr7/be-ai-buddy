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
     # ⭐️ Recommended Contact Information ⭐️
    phone_number: str       # School's main phone number
    email: EmailStr         # School's main, official email address (use Pydantic's EmailStr for validation)
    

class SchoolCreate(SchoolBase):
    admin_email: EmailStr
    admin_first_name: str
    admin_last_name: str

class SchoolInDB(SchoolBase):
    created_at:datetime = Field(default_factory=utc_now)
