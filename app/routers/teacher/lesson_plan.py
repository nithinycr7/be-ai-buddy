# routes/lesson_plan.py
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from ...db.mongo import get_db
from ...core.security import get_tenant
from app.services.teacher.lesson_plan import LessonPlanService
from pydantic import BaseModel

router = APIRouter(prefix="/lesson-plans", tags=["Lesson Plans"])
# Force reload

class GenerateRequest(BaseModel):
    class_no: int
    subject: str
    chapter: str
    teacher_id: str

class EditRequest(BaseModel):
    draft_id: str
    sections: List[str]
    instruction: str

class SaveRequest(BaseModel):
    draft_id: str

class UpdateLastAccessedRequest(BaseModel):
    plan_id: str
    plan_type: str  # "draft" or "saved"

@router.post("/generate")
async def generate_plan(req: GenerateRequest, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    return await service.generate_plan(
        class_no=req.class_no,
        subject=req.subject,
        chapter=req.chapter,
        teacher_id=req.teacher_id,
        tenant=tenant
    )

@router.post("/edit")
async def edit_plan(req: EditRequest, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    return await service.edit_plan(
        draft_id=req.draft_id,
        sections=req.sections,
        instruction=req.instruction,
        tenant=tenant
    )

@router.post("/save")
async def save_plan(req: SaveRequest, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    return await service.save_plan(draft_id=req.draft_id, tenant=tenant)

@router.get("/draft/{plan_id}")
async def get_plan(plan_id: str, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    # Try draft first
    plan = await service.get_draft(plan_id, tenant=tenant)
    if not plan:
        # Try saved
        plan = await service.get_saved_plan(plan_id, tenant=tenant)

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan

@router.get("/")
async def get_saved_plans(teacher_id: str, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    return {
        "success": True,
        "plans": await service.get_saved_plans(teacher_id, tenant=tenant)
    }

@router.get("/recent")
async def get_recent_plans(teacher_id: str, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    return await service.get_recent_plans(teacher_id, tenant=tenant)

@router.patch("/last-accessed")
async def update_last_accessed(req: UpdateLastAccessedRequest, db: AsyncIOMotorDatabase = Depends(get_db), tenant: str = Depends(get_tenant)):
    service = LessonPlanService(db)
    await service.update_last_accessed(req.plan_id, req.plan_type, tenant=tenant)
    return {"success": True}