from pydantic import BaseModel


from enum import Enum

class UserRole(str, Enum):
    teacher = "teacher"
    student = "student"
    parent = "parent"
    admin = "admin"
    superadmin = "superadmin"


class LoginRequest(BaseModel):
    identifier: str  # Employee ID / Student ID / Email
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
