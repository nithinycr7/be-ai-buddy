from __future__ import annotations
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Dict, Any, Union
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
    completed: bool = False
    progress: float = 0.0 # 0-100

class QuizOption(BaseModel):
    key: str
    description: str

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
    structured_content: Optional[Dict[str, Any]] = None
    tokens_used: Optional[int] = None
    generation_count: Optional[int] = None

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
    question_type: str = "MCQ"  # MCQ, FILL_BLANK, SOLVE, HOTS, STORY_BASED
    difficulty: str = "medium"  # easy, medium, hard
    options: List[QuizOption] = Field(default_factory=list)
    correct: Union[str, List[str]] = Field(default_factory=list)  # String for FILL_BLANK/SOLVE, List for MCQ
    hint: Optional[str] = None
    explanation: Optional[str] = None

class Quiz(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    subject: str
    topic: str
    class_no: int
    section: str
    tenant: str
    questions: List[QuizQuestion]
    auto_generated: bool = True
    source: Optional[str] = Field(default=None, description="Origin: teacher_custom, teacher_textbook, auto_transcript, auto_summary")
    transcript_id: Optional[str] = None
    generation_confidence: float = 0.0
    teacher_edited: bool = False
    teacher_approved: bool = False
    published: bool = True
    keywords: List[str] = Field(default_factory=list)
    difficulty_level: str = "medium"
    created_at: Optional[str] = None
    previous_attempt: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True

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

# New models for Daily Quiz Feature
class StudentQuizAttempt(BaseModel):
    """Detailed quiz attempt with per-question analytics"""
    id: Optional[str] = Field(default=None, alias="_id")
    quiz_id: str
    student_id: str
    daily_id: str
    tenant: str
    attempt_number: int
    started_at: str
    completed_at: Optional[str] = None
    responses: Dict[str, Any] = Field(default_factory=dict)  # {qid: {answer, is_correct, time_spent, hint_used}}
    score: float = 0.0
    xp_earned: int = 0
    time_taken_seconds: int = 0

class StreakTracking(BaseModel):
    """Student streak and XP tracking"""
    id: Optional[str] = Field(default=None, alias="_id")
    student_id: str
    tenant: str
    current_streak: int = 0
    longest_streak: int = 0
    total_xp: int = 0
    badges: List[str] = Field(default_factory=list)
    last_quiz_date: Optional[str] = None
    updated_at: str

class QuizAnalytics(BaseModel):
    """Analytics data for quiz questions"""
    id: Optional[str] = Field(default=None, alias="_id")
    quiz_id: str
    question_id: str
    tenant: str
    total_attempts: int = 0
    correct_count: int = 0
    avg_time_seconds: float = 0.0
    hint_usage_count: int = 0
    difficulty_rating: float = 0.5  # calculated from success rate


class QuizQuestionPublic(BaseModel):
    qid: str
    question: str
    question_type: str = "MCQ"
    difficulty: str = "medium"
    options: List[QuizOption] = Field(default_factory=list)
    # Excludes correct, hint, explanation

class QuizPublic(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    daily_id: str
    subject: str
    topic: str
    class_no: int
    section: str
    tenant: str
    questions: List[QuizQuestionPublic]
    # Include metadata but exclude sensitive fields if any
    auto_generated: bool = True
    keywords: List[str] = Field(default_factory=list)
    difficulty_level: str = "medium"
    created_at: Optional[str] = None
    previous_attempt: Optional[Dict[str, Any]] = None # To restore state

    class Config:
        populate_by_name = True

class AnswerVerificationRequest(BaseModel):
    quiz_id: str
    daily_id: str
    student_id: str
    qid: str
    answer: Union[str, List[str]]
    attempt_number: int = 1
    time_spent: int = 0

class AnswerVerificationResponse(BaseModel):
    is_correct: bool
    message: str
    hint: Optional[str] = None
    explanation: Optional[str] = None
    correct_answer: Optional[Union[str, List[str]]] = None
    xp_earned: int = 0


class StudentDailyProgress(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    student_id: str
    daily_id: str
    tenant: str
    school_id: Optional[str] = None
    
    summary_viewed: bool = False
    story_generated: bool = False
    
    quiz_score: float = 0.0 # 0-80
    quiz_attempts: int = 0
    
    total_score: float = 0.0 # 0-100
    is_complete: bool = False # True if all questions attempted
    
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    class Config:
        populate_by_name = True


class Badge(BaseModel):
    id: str
    name: str
    icon: str
    description: str
    condition: str


class StudentBadge(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    student_id: str
    badge_id: str
    awarded_at: str
    tenant: str



