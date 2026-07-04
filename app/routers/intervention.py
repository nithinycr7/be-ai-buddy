"""
Adaptive Intervention API
=========================
Back half of the learning loop:
  Quiz -> Analysis Engine -> Gap Detection -> Micro Intervention -> Verification

HTTP layer only — all logic lives in InterventionService.
"""
from fastapi import APIRouter, Depends

from ..core.security import require_role, get_current_user, CurrentUser
from ..models.schemas import (
    AnalyzeInterventionRequest, InterventionAnalyzeResponse,
    VerifyInterventionRequest, VerifyInterventionResponse,
)
from ..services.intervention_service import InterventionService, get_intervention_service

router = APIRouter(prefix="/intervention", tags=["intervention"],
                   dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])


@router.post("/analyze", response_model=InterventionAnalyzeResponse)
async def analyze(
    request: AnalyzeInterventionRequest,
    service: InterventionService = Depends(get_intervention_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.analyze(request, requester=user)


@router.post("/verify", response_model=VerifyInterventionResponse)
async def verify(
    request: VerifyInterventionRequest,
    service: InterventionService = Depends(get_intervention_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.verify(request, requester=user)
