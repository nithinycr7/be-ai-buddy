# app/routers/audio_upload.py
"""
Audio Upload Router

Provides REST API endpoint for uploading audio files to Azure Blob Storage.
"""

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from ..core.security import api_key_guard, get_tenant
from ..services.audio_upload import audio_upload_service
import json

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
            - selectedTopic (optional): Topic/chapter name
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
        
        return result
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid metadata format. Expected JSON string."
        )
    except Exception as e:
        # Let service exceptions bubble up (they're already HTTPExceptions)
        raise e
