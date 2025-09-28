
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from app.utils.datetime import utc_now

# ---- Pydantic schema for request/response ----
class UserBase(BaseModel):
    user_id: str = Field(..., description="School-issued unique ID (e.g. T123, S567)")
    first_name: str
    last_name: str
    email: Optional[EmailStr] = None
    school_id: Optional[str] = None
    roles: List[str] = Field(..., description='List of roles (e.g. ["teacher", "class_coordinator"])')
    is_active: bool = True
        
    # ⭐️ Added username as Optional ⭐️
    username: Optional[str] = None

class UserCreate(UserBase):
    password: Optional[str] = None  # now optional

class UserLogin(BaseModel):
    user_id: str
    password: str

class UserInDB(UserBase):
    hashed_password: str
    created_at: datetime = Field(default_factory=utc_now)

class UserPublic(UserBase):
    id: str
