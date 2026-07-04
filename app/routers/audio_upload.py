# app/routers/audio_upload.py — HTTP layer only. Logic lives in AudioIngestService.
"""Audio Upload Router — upload audio to Azure Blob + queue for transcription (worker)."""
from fastapi import APIRouter, Depends, UploadFile, File, Form

from ..core.security import api_key_guard, get_tenant
from ..services.audio_ingest_service import AudioIngestService, get_audio_ingest_service

router = APIRouter(prefix="/audio", tags=["audio"], dependencies=[Depends(api_key_guard)])


@router.post("/upload")
async def upload_audio(
    audio: UploadFile = File(...),
    metadata: str = Form(...),
    tenant: str = Depends(get_tenant),
    service: AudioIngestService = Depends(get_audio_ingest_service),
):
    """Upload an audio file to Blob Storage and queue it for transcription.

    `metadata` is a JSON string: selectedClass/Section/Subject (+ optional topics,
    chapter/topic ids, schoolId). Returns {success, url, filename}.
    """
    content = await audio.read()
    return await service.upload(content=content, metadata_str=metadata, tenant=tenant)
