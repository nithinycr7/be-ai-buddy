from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, HTTPException

from app.core.security import api_key_guard, get_tenant, require_role
from app.models.learning_engine_schemas import LearnRequest, LearnResponse, ConceptSearchResult
from app.services.learning_engine.concept_detector import detect_concept
from app.services.learning_engine.mode_selector import select_mode, get_all_modes
from app.services.learning_engine.explainer import (
    classify_concept,
    generate_explanation,
    get_cached_response,
    cache_response,
)
from app.db.sqlite_db import get_sqlite_db
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/learn",
    tags=["learning-engine"],
    dependencies=[Depends(require_role("student", "teacher", "admin"))],
)


@router.post("/explain", response_model=LearnResponse)
def explain_concept(
    req: LearnRequest,
    tenant: str = Depends(get_tenant),
):
    """
    Main endpoint: takes a student query + grade and returns a fully structured
    visual learning response. Automatically selects the best learning mode.
    """
    # 1. Detect concept from student query
    concept_info = detect_concept(req.query, req.grade, req.curriculum)
    slug         = concept_info["slug"]
    concept_name = concept_info["name"]
    subject      = concept_info["subject"]

    # 2. Get or classify concept_type
    if concept_info.get("concept_type"):
        concept_type = concept_info["concept_type"]
        llm_mode     = select_mode(concept_type, req.grade, req.preferred_mode)
    else:
        try:
            concept_type, llm_mode = classify_concept(concept_name, subject, req.grade)
        except Exception as e:
            logger.warning(f"Classification failed, defaulting to concept/diagram: {e}")
            concept_type = "concept"
            llm_mode     = "diagram"

    learning_mode = req.preferred_mode if req.preferred_mode else llm_mode

    # 3. Check cache
    if not req.force_refresh:
        cached = get_cached_response(slug, req.grade, req.curriculum, learning_mode)
        if cached:
            cached["available_modes"] = get_all_modes(concept_type, req.grade)
            cached["cached"] = True
            return LearnResponse(**cached)

    # 4. Generate explanation via LLM
    try:
        data = generate_explanation(
            concept_name=concept_name,
            concept_type=concept_type,
            subject=subject,
            grade=req.grade,
            curriculum=req.curriculum,
            learning_mode=learning_mode,
        )
    except Exception as e:
        logger.error(f"Explanation generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate explanation: {str(e)}")

    # 5. Cache the result
    try:
        cache_response(slug, req.grade, req.curriculum, learning_mode,
                       data, settings.AZURE_OPENAI_CHAT_DEPLOYMENT)
    except Exception as e:
        logger.warning(f"Cache write failed (non-fatal): {e}")

    # 6. Track session
    if req.student_id:
        try:
            with get_sqlite_db() as db:
                db.execute(
                    """INSERT INTO learning_sessions
                       (student_id, tenant_id, concept_slug, learning_mode, grade)
                       VALUES (?, ?, ?, ?, ?)""",
                    (req.student_id, tenant, slug, learning_mode, req.grade)
                )
        except Exception as e:
            logger.warning(f"Session tracking failed (non-fatal): {e}")

    data["available_modes"] = get_all_modes(concept_type, req.grade)
    data["cached"] = False
    return LearnResponse(**data)


@router.get("/search", response_model=list[ConceptSearchResult])
def search_concepts(
    q:          str = Query(..., min_length=2),
    grade:      int = Query(..., ge=3, le=9),
    curriculum: str = Query(default="CBSE"),
    subject:    str | None = Query(default=None),
):
    """Autocomplete/search concepts for the search bar."""
    with get_sqlite_db() as db:
        sql = """
            SELECT slug, name, concept_type, subject, grade_min, grade_max
            FROM concepts
            WHERE (lower(name) LIKE ? OR keywords LIKE ?)
            AND grade_min <= ? AND grade_max >= ?
            AND curriculum = ?
        """
        params: list = [f"%{q.lower()}%", f"%{q.lower()}%", grade, grade, curriculum]
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        sql += " LIMIT 10"
        rows = db.execute(sql, params).fetchall()
    return [ConceptSearchResult(**dict(r)) for r in rows]


@router.get("/related/{slug}")
def get_related_concepts(
    slug:       str,
    grade:      int = Query(..., ge=3, le=9),
    curriculum: str = Query(default="CBSE"),
):
    """Return related concepts for the sidebar / knowledge graph."""
    with get_sqlite_db() as db:
        rows = db.execute(
            """SELECT c2.slug, c2.name, c2.concept_type, cr.relationship_type, cr.strength
               FROM concept_relationships cr
               JOIN concepts c1 ON c1.id = cr.source_concept_id
               JOIN concepts c2 ON c2.id = cr.target_concept_id
               WHERE c1.slug = ? AND c2.grade_min <= ? AND c2.grade_max >= ?
               ORDER BY cr.strength DESC
               LIMIT 8""",
            (slug, grade, grade)
        ).fetchall()
    return [dict(r) for r in rows]
