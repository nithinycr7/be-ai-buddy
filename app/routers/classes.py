# app/routers/classes.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from datetime import date as dt_date
from bson import ObjectId
import os, tempfile, urllib.request
from app.core.config import settings
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import DailyClass, Transcript, Summary
from ..services.transcribe import transcribe_wav
from ..services.ai import summarize as ai_summarize

# Azure Blob (private download)
from azure.storage.blob import BlobClient
from urllib.parse import urlsplit, unquote

router = APIRouter(prefix="/classes", tags=["classes"], dependencies=[Depends(api_key_guard)])

# ---------- helpers ----------
def _today_iso() -> str:
    return dt_date.today().isoformat()

async def _get_or_create_daily(db, *, tenant: str, class_no: int, section: str, subject: str, date_str: str | None = None) -> str:
    d = date_str or _today_iso()
    existing = await db.classes_daily.find_one({
        "tenant": tenant, "date": d, "class_no": class_no, "section": section, "subject": subject
    })
    if existing:
        return str(existing["_id"])
    res = await db.classes_daily.insert_one({
        "tenant": tenant,
        "date": d,
        "class_no": class_no,
        "section": section,
        "subject": subject,
        "topics": [],
        "summary": None
    })
    return str(res.inserted_id)

# ---------- existing endpoints (fixed) ----------
@router.post("/daily", response_model=DailyClass, status_code=201)
async def create_daily(payload: DailyClass, tenant: str = Depends(get_tenant)):
    db = await get_db()
    # Ensure tenant from header overrides or is set if missing in payload (though payload has it mandatory now)
    # Actually, DailyClass has tenant mandatory. The client should send it in body OR we override it.
    # Better pattern: The API client sends X-Tenant-ID. We set it on the model.
    data = payload.model_dump(by_alias=True, exclude_none=True)
    data['tenant'] = tenant
    res = await db.classes_daily.insert_one(data)
    payload.id = str(res.inserted_id)
    payload.tenant = tenant
    return payload

@router.post("/daily/{daily_id}/transcribe", response_model=Transcript)
async def upload_and_transcribe(daily_id: str, audio: UploadFile = File(...)):
    db = await get_db()
    if not ObjectId.is_valid(daily_id) or not await db.classes_daily.find_one({"_id": ObjectId(daily_id)}):
        raise HTTPException(status_code=404, detail="Daily class not found")

    suffix = os.path.splitext(audio.filename or "")[1] or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        text = await transcribe_wav(tmp_path)
    finally:
        try: os.remove(tmp_path)
        except OSError: pass

    res = await db.transcripts.insert_one({"daily_id": daily_id, "text": text})
    return Transcript(id=str(res.inserted_id), daily_id=daily_id, text=text)

@router.post("/daily/{daily_id}/summarize", response_model=Summary)
async def summarize_daily(daily_id: str):
    db = await get_db()
    if not ObjectId.is_valid(daily_id) or not await db.classes_daily.find_one({"_id": ObjectId(daily_id)}):
        raise HTTPException(status_code=404, detail="Daily class not found")

    t = await db.transcripts.find_one({"daily_id": daily_id})
    base = t["text"] if t else ""
    d = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if d and d.get("summary"):
        base = d["summary"] + "\n" + base
    text = await ai_summarize(base) if base else ""
    res = await db.summaries.insert_one({"daily_id": daily_id, "text": text})
    return Summary(id=str(res.inserted_id), daily_id=daily_id, text=text)

# ---------- NEW: private blob download + auto-create daily ----------
@router.post("/transcribe-blob-or-create")
async def transcribe_blob_or_create(payload: dict = Body(...), tenant: str = Depends(get_tenant)):
    """
    JSON:
    {
      "blob_url": "https://<account>.blob.core.windows.net/<container>/<name>.mp3",
      "class_no": 7,
      "section": "A",
      "subject": "Science",
      "date": "YYYY-MM-DD"   # optional, defaults to today
    }
    """
    blob_url = payload.get("blob_url")
    # tenant comes from dependency now
    class_no = payload.get("class_no")
    section  = payload.get("section")
    subject  = payload.get("subject")
    date_str = payload.get("date")

    if not all([blob_url, class_no, section, subject]):
        raise HTTPException(400, "blob_url, class_no, section, subject are required")

    db = await get_db()
    daily_id = await _get_or_create_daily(
        db, tenant=str(tenant), class_no=int(class_no), section=str(section), subject=str(subject), date_str=date_str
    )

    # Parse container/blob from URL for private download
    parts = urlsplit(blob_url)
    if parts.netloc.endswith(".blob.core.windows.net") is False:
        raise HTTPException(400, "blob_url must be an Azure Blob URL")
    try:
        container_name, blob_name = unquote(parts.path.lstrip("/")).split("/", 1)
    except ValueError:
        raise HTTPException(400, "blob_url path must be /<container>/<blob>")

    suffix = os.path.splitext(blob_name)[1] or ".mp3"

    # Prefer private SDK download (works without public read/SAS)
    conn_str = settings.AZURE_BLOB_CONN_STR
   
    print("conn_str", conn_str)
    if not conn_str and "sig=" not in blob_url:
        raise HTTPException(400, "Private blob: set AZURE_BLOB_CONN_STR in environment or provide a SAS URL")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        if conn_str:
            bc = BlobClient.from_connection_string(conn_str, container_name=container_name, blob_name=blob_name)
            data = bc.download_blob()
            tmp.write(data.readall())
        else:
            # has SAS in the URL; public download is OK
            with urllib.request.urlopen(blob_url) as resp:
                tmp.write(resp.read())
        tmp_path = tmp.name

    try:
        text = await transcribe_wav(tmp_path)
        if not text:
            raise HTTPException(
                status_code=502,
                detail="Speech recognition returned empty. Key/region OK; audio parsed. Try clearer audio or verify ffmpeg/pydub installed."
            )
    finally:
        try: os.remove(tmp_path)
        except OSError: pass

    res = await db.transcripts.insert_one({
        "daily_id": daily_id,
        "text": text,
        "source": "blob",
        "blob_url": blob_url
    })

    return {
        "daily_id": daily_id,
        "transcript_id": str(res.inserted_id),
        "text_len": len(text or "")
    }

@router.get("/daily", response_model=list[DailyClass])
async def list_daily_classes(class_no: int, section: str, date: str | None = None, tenant: str = Depends(get_tenant)):
    db = await get_db()
    query = {"tenant": tenant, "class_no": class_no, "section": section}
    if date:
        query["date"] = date
    
    cursor = db.classes_daily.find(query).sort("date", -1).limit(50)
    results = []
    async for doc in cursor:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        results.append(DailyClass(**doc))
    return results
