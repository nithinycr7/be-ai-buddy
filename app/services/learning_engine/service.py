"""
Learning-engine business logic: query → concept → mode → explanation (cached),
plus concept search/related. router → LearningEngineService → (LLM helpers + SQLite repo).
Synchronous (matches the sqlite driver + sync endpoints).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.learning_engine_schemas import LearnRequest, LearnResponse, ConceptSearchResult
from app.services.learning_engine.concept_detector import detect_concept
from app.services.learning_engine.mode_selector import select_mode, get_all_modes
from app.services.learning_engine.explainer import (
    classify_concept, generate_explanation, get_cached_response, cache_response,
)
from app.services.learning_engine import repository as repo

logger = logging.getLogger(__name__)


class LearningEngineService:
    def explain(self, req: LearnRequest, *, tenant: str) -> LearnResponse:
        concept_info = detect_concept(req.query, req.grade, req.curriculum)
        slug = concept_info["slug"]
        concept_name = concept_info["name"]
        subject = concept_info["subject"]

        if concept_info.get("concept_type"):
            concept_type = concept_info["concept_type"]
            llm_mode = select_mode(concept_type, req.grade, req.preferred_mode)
        else:
            try:
                concept_type, llm_mode = classify_concept(concept_name, subject, req.grade)
            except Exception as e:
                logger.warning(f"Classification failed, defaulting to concept/diagram: {e}")
                concept_type, llm_mode = "concept", "diagram"

        learning_mode = req.preferred_mode if req.preferred_mode else llm_mode

        if not req.force_refresh:
            cached = get_cached_response(slug, req.grade, req.curriculum, learning_mode)
            if cached:
                cached["available_modes"] = get_all_modes(concept_type, req.grade)
                cached["cached"] = True
                return LearnResponse(**cached)

        try:
            data = generate_explanation(
                concept_name=concept_name, concept_type=concept_type, subject=subject,
                grade=req.grade, curriculum=req.curriculum, learning_mode=learning_mode)
        except Exception as e:
            logger.error(f"Explanation generation failed: {e}")
            raise AppError(f"Failed to generate explanation: {e}", status_code=500)

        try:
            cache_response(slug, req.grade, req.curriculum, learning_mode,
                           data, settings.AZURE_OPENAI_CHAT_DEPLOYMENT)
        except Exception as e:
            logger.warning(f"Cache write failed (non-fatal): {e}")

        if req.student_id:
            try:
                repo.track_session(student_id=req.student_id, tenant=tenant, slug=slug,
                                   learning_mode=learning_mode, grade=req.grade)
            except Exception as e:
                logger.warning(f"Session tracking failed (non-fatal): {e}")

        data["available_modes"] = get_all_modes(concept_type, req.grade)
        data["cached"] = False
        return LearnResponse(**data)

    def search(self, *, q: str, grade: int, curriculum: str, subject: Optional[str]) -> List[ConceptSearchResult]:
        rows = repo.search_concepts(q=q, grade=grade, curriculum=curriculum, subject=subject)
        return [ConceptSearchResult(**r) for r in rows]

    def related(self, *, slug: str, grade: int) -> List[dict]:
        return repo.related_concepts(slug=slug, grade=grade)


def get_learning_engine_service() -> LearningEngineService:
    return LearningEngineService()
