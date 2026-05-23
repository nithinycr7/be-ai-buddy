"""
Engine config API — serves AI-generated world configs to the frontend.

All caching happens here at the API level (MongoDB). The frontend never
caches engine configs.

Routes (all under settings.API_PREFIX, e.g. /api):
  POST /engine/config         → returns config (from cache or freshly generated)
  GET  /engine/cache-status   → lightweight cache metadata for a topic+grade
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.engine_config_cache import (
    get_cache_meta,
    get_cached_config,
    save_config,
)
from app.services.engine_config_generator import generate_engine_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engine", tags=["engine"])


# ── Topic registry ────────────────────────────────────────────────────────
# Curated metadata for the showcase demo topics. The endpoint is NOT
# gated on this — any topic_slug the FE sends is accepted, and the FE
# provides topic/subject/grades for slugs that aren't in this dict.
# This registry exists only so the demo topics get canonical, hand-picked
# grade ranges and subject labels regardless of what the FE sends.
TOPIC_REGISTRY: dict[str, dict] = {
    "photosynthesis": {
        "topic":   "Photosynthesis",
        "subject": "Science",
        "grades":  [3, 7],
        "board":   "CBSE",
    },
    "solar-system": {
        "topic":   "Solar System",
        "subject": "Science",
        "grades":  [3, 7],
        "board":   "CBSE",
    },
    "water-cycle": {
        "topic":   "Water Cycle",
        "subject": "Geography",
        "grades":  [4, 6],
        "board":   "CBSE",
    },
}


def _slug_to_title(slug: str) -> str:
    """Fallback display name when the FE didn't send `topic` for a new slug."""
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


# ── Schemas ───────────────────────────────────────────────────────────────
class ConfigRequest(BaseModel):
    topic_slug: str
    grade:      int
    force:      bool = False  # bypass cache, regenerate, overwrite DB
    # Optional metadata — used for topics not present in TOPIC_REGISTRY.
    # The registry always wins for curated slugs so demo grade ranges stay
    # canonical regardless of what the FE sends.
    topic:   Optional[str]       = None
    subject: Optional[str]       = None
    grades:  Optional[list[int]] = None
    board:   Optional[str]       = None


class ConfigResponse(BaseModel):
    config:        dict
    topic_slug:    str
    grade:         int
    from_cache:    bool
    generated_at:  Optional[str] = None
    generation_ms: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────────────
@router.post("/config", response_model=ConfigResponse)
async def get_engine_config(req: ConfigRequest):
    # Curated registry wins for demo topics; for any other slug we accept
    # whatever the FE sends and let Gemini generate from there.
    if req.topic_slug in TOPIC_REGISTRY:
        meta = dict(TOPIC_REGISTRY[req.topic_slug])
        if req.grade not in meta["grades"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Grade {req.grade} not supported for '{req.topic_slug}'. "
                    f"Supported grades: {meta['grades']}"
                ),
            )
    else:
        fe_grades = sorted({req.grade, *(req.grades or [])})
        meta = {
            "topic":   (req.topic or _slug_to_title(req.topic_slug)).strip(),
            "subject": (req.subject or "General").strip(),
            "grades":  fe_grades,
            "board":   (req.board or "CBSE").strip(),
        }
        if not meta["topic"]:
            raise HTTPException(
                status_code=400,
                detail="topic_slug resolved to an empty title; pass 'topic' explicitly.",
            )

    # Cache hit path
    if not req.force:
        cached = await get_cached_config(req.topic_slug, req.grade)
        if cached:
            cache_meta = await get_cache_meta(req.topic_slug, req.grade) or {}
            return ConfigResponse(
                config=cached,
                topic_slug=req.topic_slug,
                grade=req.grade,
                from_cache=True,
                generated_at=cache_meta.get("generated_at"),
                generation_ms=cache_meta.get("generation_ms"),
            )

    # Cache miss or force-regenerate: call Gemini
    try:
        config, gen_ms, model_name = await generate_engine_config(
            topic=meta["topic"],
            subject=meta["subject"],
            grades=meta["grades"],
            board=meta["board"],
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("[ENGINE-CONFIG] Unexpected error")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")

    generated_at = await save_config(
        topic_slug=req.topic_slug,
        grade=req.grade,
        config=config,
        generation_ms=gen_ms,
        gemini_model=model_name,
        force=req.force,
    )

    return ConfigResponse(
        config=config,
        topic_slug=req.topic_slug,
        grade=req.grade,
        from_cache=False,
        generated_at=generated_at.isoformat(),
        generation_ms=gen_ms,
    )


@router.get("/cache-status")
async def cache_status(
    topic_slug: str = Query(...),
    grade:      int = Query(...),
):
    meta = await get_cache_meta(topic_slug, grade)
    return {
        "topic_slug": topic_slug,
        "grade":      grade,
        "cached":     meta is not None,
        "meta":       meta,
    }
