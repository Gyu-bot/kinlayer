from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.memories import (
    MemoryChangeList,
    MemoryChangeRead,
    MemoryWriteRequest,
    MemoryWriteResponse,
)
from kinlayer_backend.services.memories import MemoryService

router = APIRouter(tags=["memories"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/memories", response_model=MemoryWriteResponse)
def write_memory(payload: MemoryWriteRequest, session: SessionDep):
    return MemoryService(session).write(payload)


@router.get("/api/memory-changes", response_model=MemoryChangeList)
def list_memory_changes(
    session: SessionDep,
    record_ref: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return MemoryService(session).list_changes(record_ref, limit, offset)


@router.get("/api/memory-changes/{change_id}", response_model=MemoryChangeRead)
def get_memory_change(change_id: str, session: SessionDep):
    return MemoryService(session).get_change(change_id)
