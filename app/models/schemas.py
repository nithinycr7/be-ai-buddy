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





class DailyClass(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    tenant: str = Field(default="demo-school", description="School/Tenant ID")
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

class StoryPersona(BaseModel):
    story_tone: Literal["Funny","Adventurous","Mystery","Serious","Inspirational"]
    themes: List[Literal["Space","Animals","Sports","Superheroes","Mythology","Technology","Art","Nature","Music","History"]] = Field(default_factory=list, max_items=5)
    difficulty: Literal["Easy","Balanced","Challenging"] = "Balanced"
    format: Literal["Short","Long","Comic-style","Real-life Example","Dialogue"] = "Comic-style"
    character_role: Literal["Kid Hero","Teacher Guide","Animal Character","Superhero","Scientist","Explorer"] = "Explorer"

# --- OPTIONAL: request body for partial updates ---
class UpdatePersonaRequest(BaseModel):
    story_persona: StoryPersona

class Student(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    student_id: str = Field(..., description="External student ID (e.g., 124537)")
    school_tenant: Optional[str] = None
    class_no: int = Field(..., ge=1, le=12)
    section: str
    parent_id: Optional[str] = None
    parent_email: Optional[EmailStr] = None
    parent_contact: Optional[str] = None
    academic_strengths: Optional[Dict[str, float]] = Field(default=None, description="e.g., {'Math':0.8, 'Science':0.6}")
    content_prefs: Optional[ContentPrefs] = None # NEW: default for tenant
    story_persona: Optional[StoryPersona] = None # NEW: structured persona     

# Progress Tracking Models
class StudentProgress(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    student_id: str
    daily_id: str
    tenant: str
    date: date
    class_no: int
    section: str
    subject: str
    
    # Activity tracking
    summary_viewed: bool = False
    summary_viewed_at: Optional[str] = None
    
    story_generated: bool = False
    story_id: Optional[str] = None
    story_generated_at: Optional[str] = None
    
    # Quiz performance
    quiz_taken: bool = False
    quiz_id: Optional[str] = None
    quiz_attempts: int = 0
    quiz_best_score: Optional[float] = None
    quiz_latest_score: Optional[float] = None
    quiz_first_attempt_at: Optional[str] = None
    quiz_last_attempt_at: Optional[str] = None
    
    # Auto-calculated
    completion_percentage: float = 0.0
    is_completed: bool = False
    completed_at: Optional[str] = None
    
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class QuizQuestion(BaseModel):
    qid: str
    question: str
    options: List[QuizOption]
    correct: List[str] = Field(default_factory=list)

class Quiz(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    subject: str
    topic: str
    class_no: int
    section: str
    tenant: str
    questions: List[QuizQuestion]
    created_at: Optional[str] = None

class QuizResponse(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    student_id: str
    quiz_id: str
    tenant: str
    
    attempt_number: int
    attempted_at: str
    
    responses: Dict[str, List[str]]  # {qid: [selected_option]}
    correct_answers: Dict[str, List[str]]  # {qid: [correct_option]}
    
    score: float  # Percentage
    correct_count: int
    total_questions: int
    
    time_taken_seconds: Optional[int] = None

