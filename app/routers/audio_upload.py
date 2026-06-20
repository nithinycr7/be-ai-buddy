# app/routers/audio_upload.py
"""
Audio Upload Router

Provides REST API endpoint for uploading audio files to Azure Blob Storage.
"""

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from ..core.security import api_key_guard, get_tenant
from ..services.audio_upload import audio_upload_service
from ..services.capture_meta import save_capture_meta, coerce_class_no
from ..db.mongo import get_db
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audio",
    tags=["audio"],
    dependencies=[Depends(api_key_guard)]
)


@router.post("/upload")
async def upload_audio(
    audio: UploadFile = File(...),
    metadata: str = Form(...),
    tenant: str = Depends(get_tenant)
):
    """
    Upload audio file to Azure Blob Storage and queue for transcription
    
    Args:
        audio: Audio file (multipart/form-data)
        metadata: JSON string containing upload metadata:
            - schoolId (optional): School identifier (default: "SCH-123")
            - selectedClass (required): Class number
            - selectedSection (required): Section identifier
            - selectedSubject (required): Subject name
            - selectedTopics (optional): List of Topic/chapter names
        tenant: Tenant ID from header (X-Tenant-ID)
    
    Returns:
        dict: Upload result containing:
            - success: Boolean indicating upload success
            - url: Blob storage URL of uploaded file
            - filename: Path to file in blob storage
    
    Example request:
        curl -X POST http://localhost:8000/api/audio/upload \\
          -H "x-api-key: dev-local-key" \\
          -H "X-Tenant-ID: demo-school" \\
          -F "audio=@recording.webm" \\
          -F 'metadata={"selectedClass":"10","selectedSection":"A","selectedSubject":"Math"}'
    
    Example response:
        {
            "success": true,
            "url": "https://audiofileuploads.blob.core.windows.net/schools/SCH-123/10A_Math_Topic_123.webm",
            "filename": "SCH-123/10A_Math_Topic_123.webm"
        }
    """
    try:
        # Parse metadata
        meta = json.loads(metadata)
        
        # Add tenant to metadata if needed
        meta['tenant'] = tenant
        
        # Read audio file content
        content = await audio.read()
        
        # Upload to Azure Blob Storage and queue
        result = await audio_upload_service.upload_audio(content, meta)

        # Stash the teacher's CANONICAL chapter/topic ids so summary generation can
        # scope NCERT grounding to the exact taught section (the blob filename only
        # carries a title). Keyed by class identity the summary flow resolves on.
        try:
            await save_capture_meta(
                await get_db(),
                tenant=tenant,
                class_no=coerce_class_no(meta.get("selectedClass")),
                section=(meta.get("selectedSection") or "A"),
                subject=(meta.get("selectedSubject") or ""),
                chapter_key=meta.get("selectedChapterId"),
                topic_ids=meta.get("selectedTopicIds"),
                topics=meta.get("selectedTopics") or ([meta.get("selectedTopic")] if meta.get("selectedTopic") else []),
            )
        except Exception as e:  # never fail the upload over the sidecar
            logger.warning("[audio/upload] capture_meta save failed: %s", e)

        return result
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid metadata format. Expected JSON string."
        )
    except Exception as e:
        # Let service exceptions bubble up (they're already HTTPExceptions)
        raise e
