"""Engine config API — HTTP layer only. Logic lives in EngineService."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query

from app.services.engine_service import (
    EngineService, ConfigRequest, ConfigResponse, get_engine_service,
)

router = APIRouter(prefix="/engine", tags=["engine"])


@router.post("/config", response_model=ConfigResponse)
async def get_engine_config(req: ConfigRequest, service: EngineService = Depends(get_engine_service)):
    return await service.get_config(req)


@router.get("/cache-status")
async def cache_status(
    topic_slug: str = Query(...),
    grade: int = Query(...),
    service: EngineService = Depends(get_engine_service),
):
    return await service.cache_status(topic_slug=topic_slug, grade=grade)
