from __future__ import annotations
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..core.security import require_role
from ..services.ai_service import AiService, TTSRequest, get_ai_service

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])


@router.post("/tts")
async def text_to_speech(req: TTSRequest, service: AiService = Depends(get_ai_service)):
    """Convert text to natural MP3 audio (Azure AI Speech), streamed as audio/mpeg."""
    audio_bytes = await service.synthesize_speech(req)

    async def _stream():
        chunk = 4096
        for i in range(0, len(audio_bytes), chunk):
            yield audio_bytes[i:i + chunk]

    return StreamingResponse(_stream(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.get("/simulation")
async def get_simulation_cache(daily_id: str, service: AiService = Depends(get_ai_service)):
    """Return the most recent cached simulation for a class, or 404 if none exists."""
    return await service.get_cached_simulation(daily_id)


@router.post("/simulation")
async def simulation_for_student(
    daily_id: str,
    student_id: str,
    force: bool = False,
    service: AiService = Depends(get_ai_service),
):
    """Generate (or return cached) an interactive HTML simulation for a daily class."""
    return await service.generate_simulation(daily_id=daily_id, student_id=student_id, force=force)
