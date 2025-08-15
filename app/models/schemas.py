from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any
from datetime import date

from typing import Literal

# ---------- Common ----------
class School(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    tenant: str = Field(..., description="School/Tenant Name")
    branch: Optional[str] = None
    location: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
  
class Teacher(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    teacher_id: Optional[str] = None
    name: str
    email: EmailStr
    phone: Optional[str] = None
    school_tenant: Optional[str] = None
    subjects: List[str] = []

class Parent(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    student_id: Optional[str] = None


class ContentPrefs(BaseModel):
    story_format: Literal["fiction", "comic", "real_life", "mythology"] = "fiction"
    story_length: Literal["tiny", "short", "medium", "long"] = "short"
    explanation_granularity: Literal["very_short", "short", "standard", "detailed"] = "standard"
    explanation_format: Literal["bullets", "paragraphs", "mix"] = "mix"
    examples_type: list[Literal["sports","space","animals","everyday","tech","history","nature","mythology"]] = ["everyday"]
    reference_figures: list[str] = []
    humor_level: Literal["none","light","playful"] = "light"
    tone: Literal["friendly","encouraging","neutral","formal","excited"] = "encouraging"
    language: str = "en-IN"
    include_steps: bool = True
    include_summary: Literal["none","one_liner","bullets"] = "bullets"
    diagram_preference: Literal["none","simple","detailed"] = "simple"


class Student(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    student_id: str = Field(..., description="External student ID (e.g., 124537)")
    school_tenant: Optional[str] = None
    class_no: int = Field(..., ge=1, le=12)
    section: str
    persona: Optional[str] = None
    parent_id: Optional[str] = None
    parent_email: Optional[EmailStr] = None
    parent_contact: Optional[str] = None
    academic_strengths: Optional[Dict[str, float]] = Field(default=None, description="e.g., {'Math':0.8, 'Science':0.6}")
    content_prefs: Optional[ContentPrefs] = None # NEW: default for tenant



class DailyClass(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    date: date
    class_no: int
    section: str
    subject: str
    topics: List[str] = []
    summary: Optional[str] = None

class QuizOption(BaseModel):
    key: str
    description: str

class QuizQuestion(BaseModel):
    qid: str
    question: str
    options: List[QuizOption]
    correct: List[str] = Field(default_factory=list)

class Quiz(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    class_no: int
    section: str
    subject: str
    topic_tags: List[str] = []
    questions: List[QuizQuestion]

class QuizResponse(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    quiz_id: str
    daily_id: str
    student_id: str
    date: date
    responses: Dict[str, List[str]] # {qid: ['a']}
    score: Optional[float] = None

class Transcript(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: Optional[str] = None
    student_id: Optional[str] = None
    text: str

class Summary(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    text: str

class Story(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    student_id: Optional[str] = None
    persona_used: Optional[str] = None
    text: str

class RAGDoc(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    chapter: str
    subject: str
    class_no: int
    section: Optional[str] = None
    text: str
    embedding: Optional[List[float]] = None
