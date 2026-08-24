from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.curation import (
    CurationMode,
    CurationRunList,
    CurationRunCreate,
    CurationRunRead,
    CurationRunStatus,
    CurationSourcePackRead,
    CurationSourcePackRequest,
)
from kinlayer_backend.services.curation import CurationService

router = APIRouter(tags=["curation"])
SessionDep = Annotated[Session, Depends(get_session)]


def _configured_mode(request: Request) -> str:
    return request.app.state.settings.curation_mode


def _require_enabled(request: Request) -> str:
    mode = _configured_mode(request)
    if mode == "disabled":
        raise api_error(409, "curation_disabled", "Curation is disabled.")
    return mode


def _require_policy_version(request: Request, policy_version: str) -> None:
    if policy_version != request.app.state.settings.curation_policy_version:
        raise api_error(
            409,
            "curation_policy_mismatch",
            "Run policy_version must match the configured curation policy.",
        )


@router.post("/api/curation/source-packs", response_model=CurationSourcePackRead)
def create_curation_source_pack(
    payload: CurationSourcePackRequest,
    session: SessionDep,
    request: Request,
):
    _require_enabled(request)
    return CurationService(session).build_source_pack(payload)


@router.post("/api/curation/runs", response_model=CurationRunRead, status_code=201)
def create_curation_run(
    payload: CurationRunCreate,
    session: SessionDep,
    request: Request,
):
    configured_mode = _require_enabled(request)
    if payload.mode.value != configured_mode:
        raise api_error(
            409,
            "curation_mode_mismatch",
            "Run mode must match the configured curation mode.",
        )
    _require_policy_version(request, payload.policy_version)
    service = CurationService(session)
    return service.evaluate_run(service.create_run(payload))


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


@router.post("/api/curation/runs/{run_id}/execute", response_model=CurationRunRead)
def execute_curation_run(run_id: str, session: SessionDep, request: Request):
    if _require_enabled(request) != "apply":
        raise api_error(409, "shadow_mode", "Only apply mode can execute curation runs.")
    service = CurationService(session)
    run = service.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Curation run not found.")
    _require_policy_version(request, run.policy_version)
    return service.execute_run(run)


@router.post("/api/curation/runs/{run_id}/resume", response_model=CurationRunRead)
def resume_curation_run(run_id: str, session: SessionDep, request: Request):
    if _require_enabled(request) != "apply":
        raise api_error(409, "shadow_mode", "Only apply mode can resume curation runs.")
    service = CurationService(session)
    run = service.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Curation run not found.")
    _require_policy_version(request, run.policy_version)
    return service.resume_run(run)
