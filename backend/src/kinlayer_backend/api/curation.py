from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.curation import (
    CurationMode,
    CurationRunList,
    CurationRunRead,
    CurationRunStatus,
)
from kinlayer_backend.services.curation import CurationService

router = APIRouter(tags=["curation"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/curation/runs", response_model=CurationRunList)
def list_curation_runs(
    session: SessionDep,
    mode: CurationMode | None = None,
    status: CurationRunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = CurationService(session).list_runs(
        mode=mode.value if mode else None,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/curation/runs/{run_id}", response_model=CurationRunRead)
def get_curation_run(run_id: str, session: SessionDep):
    run = CurationService(session).get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Curation run not found.")
    return run
