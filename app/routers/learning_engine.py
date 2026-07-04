from __future__ import annotations
from fastapi import APIRouter, Depends, Query

from app.core.security import get_tenant, require_role
from app.models.learning_engine_schemas import LearnRequest, LearnResponse, ConceptSearchResult
from app.services.learning_engine.service import LearningEngineService, get_learning_engine_service

router = APIRouter(
    prefix="/learn",
    tags=["learning-engine"],
    dependencies=[Depends(require_role("student", "teacher", "admin"))],
)


@router.post("/explain", response_model=LearnResponse)
def explain_concept(
    req: LearnRequest,
    tenant: str = Depends(get_tenant),
    service: LearningEngineService = Depends(get_learning_engine_service),
):
    """Student query + grade → structured visual learning response (auto mode-select)."""
    return service.explain(req, tenant=tenant)


@router.get("/search", response_model=list[ConceptSearchResult])
def search_concepts(
    q: str = Query(..., min_length=2),
    grade: int = Query(..., ge=3, le=9),
    curriculum: str = Query(default="CBSE"),
    subject: str | None = Query(default=None),
    service: LearningEngineService = Depends(get_learning_engine_service),
):
    """Autocomplete/search concepts for the search bar."""
    return service.search(q=q, grade=grade, curriculum=curriculum, subject=subject)


@router.get("/related/{slug}")
def get_related_concepts(
    slug: str,
    grade: int = Query(..., ge=3, le=9),
    curriculum: str = Query(default="CBSE"),
    service: LearningEngineService = Depends(get_learning_engine_service),
):
    """Related concepts for the sidebar / knowledge graph."""
    return service.related(slug=slug, grade=grade)
