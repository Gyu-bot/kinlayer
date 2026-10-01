from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.memories import (
    MemoryChangeList,
    MemoryChangeRead,
    MemoryWriteRequest,
    MemoryWriteResponse,
    ClaimBasis,
    MemoryList,
    MemoryRead,
    MemoryReadStatus,
    MemoryRecordType,
)
from kinlayer_backend.services.memories import MemoryService
from kinlayer_backend.services.memory_reads import MemoryReadService

router = APIRouter(tags=["memories"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/memories", response_model=MemoryWriteResponse)
def write_memory(payload: MemoryWriteRequest, session: SessionDep):
    return MemoryService(session).write(payload)


@router.get("/api/memories", response_model=MemoryList)
def list_memories(
    session: SessionDep,
    entity_id: str | None = None,
    record_type: MemoryRecordType | None = None,
    claim_basis: ClaimBasis | None = None,
    status: MemoryReadStatus = "active",
    q: Annotated[str | None, Query(max_length=500)] = None,
    source_episode_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return MemoryReadService(session).list(
        entity_id=entity_id, record_type=record_type, claim_basis=claim_basis, status=status,
        q=q, source_episode_id=source_episode_id, limit=limit, offset=offset,
    )


@router.get("/api/memories/{record_type}/{record_id}", response_model=MemoryRead)
def get_memory(record_type: MemoryRecordType, record_id: str, session: SessionDep):
    return MemoryReadService(session).get(record_type, record_id)


@router.get("/api/memory-changes", response_model=MemoryChangeList)
def list_memory_changes(
    session: SessionDep,
    record_ref: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    entity_id: str | None = None,
):
    return MemoryService(session).list_changes(record_ref, limit, offset, entity_id=entity_id)


@router.get("/api/memory-changes/{change_id}", response_model=MemoryChangeRead)
def get_memory_change(change_id: str, session: SessionDep):
    return MemoryService(session).get_change(change_id)
