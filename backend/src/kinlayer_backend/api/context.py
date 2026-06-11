from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.context import (
    ContextCardResponse,
    ContextPackRequest,
    ContextPackResponse,
    ContextRetrieveRequest,
    ContextRetrieveResponse,
)
from kinlayer_backend.services.context import ContextService

router = APIRouter(tags=["context"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/context/retrieve", response_model=ContextRetrieveResponse)
def retrieve_context(payload: ContextRetrieveRequest, session: SessionDep):
    return ContextService(session).retrieve(payload.model_dump())


@router.post("/api/context/pack", response_model=ContextPackResponse)
def pack_context(payload: ContextPackRequest, session: SessionDep):
    return ContextService(session).pack(payload.model_dump())


@router.get("/api/entities/{entity_id}/context-card", response_model=ContextCardResponse)
def context_card(entity_id: str, session: SessionDep):
    return ContextService(session).context_card(entity_id)
