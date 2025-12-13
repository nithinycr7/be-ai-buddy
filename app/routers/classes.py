# app/routers/classes.py
from fastapi import APIRouter, Depends, HTTPException, Body
from datetime import date as dt_date
from bson import ObjectId
from app.core.config import settings
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import DailyClass, Summary
from ..services.ai import summarize as ai_summarize

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



@router.get("/daily", response_model=list[DailyClass])
async def list_daily_classes(
    class_no: int, 
    section: str, 
    date: str | None = None, 
    student_id: str | None = None,
    tenant: str = Depends(get_tenant)
):
    db = await get_db()
    query = {"tenant": tenant, "class_no": class_no, "section": section}
    if date:
        query["date"] = date
    
    cursor = db.classes_daily.find(query).sort("date", -1).limit(50)
    results = []
    
    # Process classes
    classes = await cursor.to_list(length=50)
    
    # If student_id provided, fetch progress
    progress_map = {}
    if student_id and classes:
        daily_ids = [str(c["_id"]) for c in classes]
        p_cursor = db.student_daily_progress.find({
            "student_id": student_id,
            "daily_id": {"$in": daily_ids}
        })
        async for p in p_cursor:
            progress_map[p["daily_id"]] = p
            
    for doc in classes:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        
        # Instantiate DailyClass
        d_obj = DailyClass(**doc)
        
        # Inject progress
        if d_obj.id in progress_map:
            p = progress_map[d_obj.id]
            d_obj.completed = p.get("is_complete", False)
            d_obj.progress = p.get("total_score", 0.0)
            
        results.append(d_obj)
        
    return results
