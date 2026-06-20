"""
Azure Blob storage for NCERT figure images.

Figures are PNG bytes stored at a deterministic key and served via a short-lived
SAS URL — never base64 inside Mongo. Modeled on the audio upload service
(`app/services/audio_upload.py`), reusing AZURE_STORAGE_CONNECTION_STRING.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)

_container_client = None
_account_name: str | None = None
_account_key: str | None = None


def is_configured() -> bool:
    return bool(settings.AZURE_STORAGE_CONNECTION_STRING)


def _client():
    """Lazily build (and cache) the container client. Returns None if unconfigured."""
    global _container_client, _account_name, _account_key
    if _container_client is not None:
        return _container_client
    if not is_configured():
        return None
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient.from_connection_string(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        connection_timeout=120,
        read_timeout=600,
        retry_total=5,
        retry_backoff_factor=2,
    )
    _account_name = svc.account_name
    # account_key is needed to mint SAS tokens; present for connection-string auth.
    try:
        _account_key = svc.credential.account_key
    except AttributeError:
        _account_key = None

    container = svc.get_container_client(settings.NCERT_BLOB_CONTAINER)
    try:
        if not container.exists():
            container.create_container()
            logger.info("[NCERT][blob] created container %s", settings.NCERT_BLOB_CONTAINER)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[NCERT][blob] container check failed: %s", e)
    _container_client = container
    return _container_client


def figure_blob_key(*, class_no: int, subject: str, chapter_key: str, figure_id: str) -> str:
    """Deterministic, idempotent path: ncert/{class}/{subject}/{chapter}/{figId}.png"""
    safe_subject = (subject or "GEN").replace(" ", "_")
    return f"{class_no}/{safe_subject}/{chapter_key}/{figure_id}.png"


def upload_figure_png(blob_key: str, png_bytes: bytes) -> str:
    """Upload (overwrite) a figure PNG. Returns the blob_key. Raises if unconfigured."""
    container = _client()
    if container is None:
        raise RuntimeError("NCERT blob storage not configured (AZURE_STORAGE_CONNECTION_STRING)")
    from azure.storage.blob import ContentSettings

    container.get_blob_client(blob_key).upload_blob(
        png_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="image/png"),
    )
    return blob_key


def figure_url(blob_key: str) -> str | None:
    """A read-only SAS URL for a figure, valid for NCERT_FIGURE_SAS_TTL_MIN minutes.
    Falls back to the plain blob URL if the account key isn't available."""
    container = _client()
    if container is None or not blob_key:
        return None
    blob = container.get_blob_client(blob_key)
    if not _account_key:
        return blob.url
    from azure.storage.blob import BlobSasPermissions, generate_blob_sas

    sas = generate_blob_sas(
        account_name=_account_name,
        container_name=settings.NCERT_BLOB_CONTAINER,
        blob_name=blob_key,
        account_key=_account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=settings.NCERT_FIGURE_SAS_TTL_MIN),
    )
    return f"{blob.url}?{sas}"
