from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.agent_operations import AgentWriteOperationList
from kinlayer_backend.services.agent_operation_exports import AgentOperationService

router = APIRouter(tags=["agent-operations"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/agent-operations", response_model=AgentWriteOperationList)
def list_agent_operations(
    session: SessionDep,
    actor: str | None = None,
    source_path: str | None = None,
    operation_type: str | None = None,
    result_status: str | None = None,
    has_error: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = AgentOperationService(session).list_operations(
        actor=actor,
        source_path=source_path,
        operation_type=operation_type,
        result_status=result_status,
        has_error=has_error,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/agent-operations/export")
def export_agent_operations(
    session: SessionDep,
    format: str = "jsonl",
    actor: str | None = None,
    source_path: str | None = None,
    operation_type: str | None = None,
    result_status: str | None = None,
    has_error: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if format not in {"jsonl", "ndjson"}:
        format = "jsonl"
    body = AgentOperationService(session).export_jsonl(
        actor=actor,
        source_path=source_path,
        operation_type=operation_type,
        result_status=result_status,
        has_error=has_error,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    headers = {
        "Content-Disposition": 'attachment; filename="kinlayer-agent-write-operations.jsonl"',
    }
    return Response(content=body, media_type="application/x-ndjson", headers=headers)
