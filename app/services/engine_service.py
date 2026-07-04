"""
Engine-config business logic (AI-generated world configs, cached in Mongo via
engine_config_cache). router → EngineService → cache/generator services.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

from ..core.exceptions import AppError, BadRequestError
from ..services.engine_config_cache import get_cache_meta, get_cached_config, save_config
from ..services.engine_config_generator import generate_engine_config

logger = logging.getLogger(__name__)

# Curated metadata for showcase demo topics (canonical grade ranges + subjects).
TOPIC_REGISTRY: dict[str, dict] = {
    "photosynthesis": {"topic": "Photosynthesis", "subject": "Science", "grades": [3, 7], "board": "CBSE"},
    "solar-system": {"topic": "Solar System", "subject": "Science", "grades": [3, 7], "board": "CBSE"},
    "water-cycle": {"topic": "Water Cycle", "subject": "Geography", "grades": [4, 6], "board": "CBSE"},
}


def _slug_to_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


class ConfigRequest(BaseModel):
    topic_slug: str
    grade: int
    force: bool = False
    topic: Optional[str] = None
    subject: Optional[str] = None
    grades: Optional[list[int]] = None
    board: Optional[str] = None


class ConfigResponse(BaseModel):
    config: dict
    topic_slug: str
    grade: int
    from_cache: bool
    generated_at: Optional[str] = None
    generation_ms: Optional[int] = None


class EngineService:
    async def get_config(self, req: ConfigRequest) -> ConfigResponse:
        if req.topic_slug in TOPIC_REGISTRY:
            meta = dict(TOPIC_REGISTRY[req.topic_slug])
            if req.grade not in meta["grades"]:
                raise BadRequestError(
                    f"Grade {req.grade} not supported for '{req.topic_slug}'. "
                    f"Supported grades: {meta['grades']}")
        else:
            fe_grades = sorted({req.grade, *(req.grades or [])})
            meta = {
                "topic": (req.topic or _slug_to_title(req.topic_slug)).strip(),
                "subject": (req.subject or "General").strip(),
                "grades": fe_grades,
                "board": (req.board or "CBSE").strip(),
            }
            if not meta["topic"]:
                raise BadRequestError("topic_slug resolved to an empty title; pass 'topic' explicitly.")

        if not req.force:
            cached = await get_cached_config(req.topic_slug, req.grade)
            if cached:
                cache_meta = await get_cache_meta(req.topic_slug, req.grade) or {}
                return ConfigResponse(
                    config=cached, topic_slug=req.topic_slug, grade=req.grade, from_cache=True,
                    generated_at=cache_meta.get("generated_at"),
                    generation_ms=cache_meta.get("generation_ms"))

        try:
            config, gen_ms, model_name = await generate_engine_config(
                topic=meta["topic"], subject=meta["subject"],
                grades=meta["grades"], board=meta["board"])
        except ValueError as e:
            raise AppError(str(e), status_code=500)
        except RuntimeError as e:
            raise AppError(str(e), status_code=502)
        except Exception as e:
            logger.exception("[ENGINE-CONFIG] Unexpected error")
            raise AppError(f"Internal error: {e}", status_code=500)

        generated_at = await save_config(
            topic_slug=req.topic_slug, grade=req.grade, config=config,
            generation_ms=gen_ms, gemini_model=model_name, force=req.force)
        return ConfigResponse(
            config=config, topic_slug=req.topic_slug, grade=req.grade, from_cache=False,
            generated_at=generated_at.isoformat(), generation_ms=gen_ms)

    async def cache_status(self, *, topic_slug: str, grade: int) -> dict:
        meta = await get_cache_meta(topic_slug, grade)
        return {"topic_slug": topic_slug, "grade": grade, "cached": meta is not None, "meta": meta}


def get_engine_service() -> EngineService:
    return EngineService()
