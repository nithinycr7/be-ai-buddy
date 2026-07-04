# routes/lesson_plan.py — HTTP layer only. Logic lives in LessonPlanService.
from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel

from ...core.security import get_tenant, require_role
from ...core.exceptions import NotFoundError
from app.services.teacher.lesson_plan import LessonPlanService, get_lesson_plan_service

router = APIRouter(prefix="/lesson-plans", tags=["Lesson Plans"], dependencies=[Depends(require_role("teacher", "admin"))])


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
async def generate_plan(req: GenerateRequest, tenant: str = Depends(get_tenant),
                        service: LessonPlanService = Depends(get_lesson_plan_service)):
    return await service.generate_plan(
        class_no=req.class_no, subject=req.subject, chapter=req.chapter,
        teacher_id=req.teacher_id, tenant=tenant)


@router.post("/edit")
async def edit_plan(req: EditRequest, tenant: str = Depends(get_tenant),
                    service: LessonPlanService = Depends(get_lesson_plan_service)):
    return await service.edit_plan(
        draft_id=req.draft_id, sections=req.sections, instruction=req.instruction, tenant=tenant)


@router.post("/save")
async def save_plan(req: SaveRequest, tenant: str = Depends(get_tenant),
                    service: LessonPlanService = Depends(get_lesson_plan_service)):
    return await service.save_plan(draft_id=req.draft_id, tenant=tenant)


@router.get("/draft/{plan_id}")
async def get_plan(plan_id: str, tenant: str = Depends(get_tenant),
                   service: LessonPlanService = Depends(get_lesson_plan_service)):
    plan = await service.get_draft(plan_id, tenant=tenant) or await service.get_saved_plan(plan_id, tenant=tenant)
    if not plan:
        raise NotFoundError("Plan not found")
    return plan


@router.get("/")
async def get_saved_plans(teacher_id: str, tenant: str = Depends(get_tenant),
                          service: LessonPlanService = Depends(get_lesson_plan_service)):
    return {"success": True, "plans": await service.get_saved_plans(teacher_id, tenant=tenant)}


@router.get("/recent")
async def get_recent_plans(teacher_id: str, tenant: str = Depends(get_tenant),
                           service: LessonPlanService = Depends(get_lesson_plan_service)):
    return await service.get_recent_plans(teacher_id, tenant=tenant)


@router.patch("/last-accessed")
async def update_last_accessed(req: UpdateLastAccessedRequest, tenant: str = Depends(get_tenant),
                               service: LessonPlanService = Depends(get_lesson_plan_service)):
    await service.update_last_accessed(req.plan_id, req.plan_type, tenant=tenant)
    return {"success": True}
