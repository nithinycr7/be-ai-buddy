"""
Audio-upload orchestration: parse metadata → blob upload + queue → stash capture
meta sidecar. router → AudioIngestService → (audio_upload_service + capture_meta).
"""
from __future__ import annotations

import json
import logging

from fastapi import Depends

from ..core.exceptions import BadRequestError
from ..db.mongo import get_db
from ..services.audio_upload import audio_upload_service
from ..services.capture_meta import save_capture_meta, coerce_class_no

logger = logging.getLogger(__name__)


class AudioIngestService:
    def __init__(self, db):
        self.db = db

    async def upload(self, *, content: bytes, metadata_str: str, tenant: str) -> dict:
        try:
            meta = json.loads(metadata_str)
        except json.JSONDecodeError:
            raise BadRequestError("Invalid metadata format. Expected JSON string.")
        meta["tenant"] = tenant

        result = await audio_upload_service.upload_audio(content, meta)

        # Stash the teacher's canonical chapter/topic ids so summary generation can
        # scope NCERT grounding to the exact taught section. Never fail upload over it.
        try:
            await save_capture_meta(
                self.db, tenant=tenant,
                class_no=coerce_class_no(meta.get("selectedClass")),
                section=(meta.get("selectedSection") or "A"),
                subject=(meta.get("selectedSubject") or ""),
                chapter_key=meta.get("selectedChapterId"),
                topic_ids=meta.get("selectedTopicIds"),
                topics=meta.get("selectedTopics") or ([meta.get("selectedTopic")] if meta.get("selectedTopic") else []))
        except Exception as e:
            logger.warning("[audio/upload] capture_meta save failed: %s", e)

        return result


def get_audio_ingest_service(db=Depends(get_db)) -> AudioIngestService:
    return AudioIngestService(db)
