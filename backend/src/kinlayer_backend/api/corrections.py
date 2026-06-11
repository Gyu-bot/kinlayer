from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.corrections import CorrectionApplyRequest, CorrectionApplyResponse
from kinlayer_backend.services.corrections import CorrectionService

router = APIRouter(tags=["corrections"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/corrections/apply", response_model=CorrectionApplyResponse)
def apply_correction(payload: CorrectionApplyRequest, session: SessionDep):
    return CorrectionService(session).apply_correction(payload.model_dump())
