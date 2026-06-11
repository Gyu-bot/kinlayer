from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.embeddings import EmbeddingBackfillResult, EmbeddingStatus
from kinlayer_backend.services.embeddings import EmbeddingService

router = APIRouter(tags=["embeddings"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/embeddings/status", response_model=EmbeddingStatus)
def embedding_status(request: Request, session: SessionDep):
    return EmbeddingService(session, request.app.state.settings).status()


@router.post("/api/embeddings/backfill", response_model=EmbeddingBackfillResult)
def embedding_backfill(
    request: Request,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
):
    return EmbeddingService(session, request.app.state.settings).backfill(limit=limit)
