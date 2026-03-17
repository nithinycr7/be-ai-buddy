from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class ConceptType(str, Enum):
    CONCEPT      = "concept"
    EQUATION     = "equation"
    RELATIONSHIP = "relationship"
    PROCESS      = "process"
    MEMORY       = "memory"


class LearningMode(str, Enum):
    DIAGRAM                = "diagram"
    EQUATION_VISUALIZATION = "equation_visualization"
    PROCESS_FLOW           = "process_flow"
    MINDMAP                = "mindmap"
    STEP_BY_STEP           = "step_by_step"
    MNEMONIC               = "mnemonic"


class LearnRequest(BaseModel):
    query:          str           = Field(..., description="Student question or concept name")
    grade:          int           = Field(..., ge=3, le=9)
    curriculum:     str           = Field(default="CBSE")
    preferred_mode: Optional[LearningMode] = None
    student_id:     Optional[str] = None
    force_refresh:  bool          = False


class QuickCheck(BaseModel):
    question: str
    options:  list[str]
    answer:   str
    hint:     str


class LearnResponse(BaseModel):
    concept:          str
    grade:            int
    curriculum:       str
    type:             str
    learning_mode:    str
    explanation:      str
    analogy:          str
    visual_data:      dict[str, Any]
    fun_fact:         str
    common_mistake:   str
    related_concepts: list[str]
    quick_check:      dict[str, Any]
    available_modes:  list[str]
    cached:           bool = False


class ConceptSearchResult(BaseModel):
    slug:         str
    name:         str
    concept_type: str
    subject:      str
    grade_min:    int
    grade_max:    int
