from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.corrections import CorrectionApplyRequest, CorrectionApplyResponse
from kinlayer_backend.services.agent_operation_exports import AgentOperationService
from kinlayer_backend.services.corrections import CorrectionService

router = APIRouter(tags=["corrections"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/corrections/apply", response_model=CorrectionApplyResponse)
def apply_correction(payload: CorrectionApplyRequest, session: SessionDep):
    body = payload.model_dump()
    try:
        result = CorrectionService(session).apply_correction(body)
    except HTTPException as exc:
        AgentOperationService(session).record_correction_failure(
            body,
            "/api/corrections/apply",
            exc,
        )
        raise
    AgentOperationService(session).record_correction_success(
        body,
        result,
        "/api/corrections/apply",
    )
    return result
