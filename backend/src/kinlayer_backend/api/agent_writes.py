from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.agent_writes import (
    AgentWriteValidateRequest,
    AgentWriteValidationResponse,
)
from kinlayer_backend.services.agent_write_filter import AgentWriteFilter

router = APIRouter(tags=["agent-writes"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/agent-writes/validate", response_model=AgentWriteValidationResponse)
def validate_agent_write(payload: AgentWriteValidateRequest, session: SessionDep):
    return AgentWriteFilter(session).validate(payload.write_type, payload.payload)
