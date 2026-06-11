from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.repositories.candidates import CandidateRepository
from kinlayer_backend.schemas.candidates import (
    CandidateActionRequest,
    CandidateCreate,
    CandidateEditAcceptRequest,
    CandidateList,
    CandidatePatch,
    CandidateRead,
)
from kinlayer_backend.services.candidates import CandidateService

router = APIRouter(tags=["candidates"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/candidates", response_model=CandidateRead, status_code=201)
def create_candidate(payload: CandidateCreate, session: SessionDep):
    return CandidateService(session).create_candidate(payload.model_dump())


@router.get("/api/candidates", response_model=CandidateList)
def list_candidates(
    session: SessionDep,
    status: str | None = None,
    candidate_type: str | None = None,
    target_entity_id: str | None = None,
    sensitivity: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = CandidateRepository(session).list_candidates(
        status=status,
        candidate_type=candidate_type,
        target_entity_id=target_entity_id,
        sensitivity=sensitivity,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


def _candidate_or_404(session: Session, candidate_id: str):
    candidate = CandidateRepository(session).get_candidate(candidate_id)
    if not candidate:
        raise api_error(404, "not_found", "Candidate not found.")
    return candidate


@router.get("/api/candidates/{candidate_id}", response_model=CandidateRead)
def get_candidate(candidate_id: str, session: SessionDep):
    return _candidate_or_404(session, candidate_id)


@router.patch("/api/candidates/{candidate_id}", response_model=CandidateRead)
def patch_candidate(candidate_id: str, payload: CandidatePatch, session: SessionDep):
    candidate = _candidate_or_404(session, candidate_id)
    return CandidateService(session).patch_candidate(
        candidate,
        payload.model_dump(exclude_unset=True),
    )


@router.delete("/api/candidates/{candidate_id}", response_model=CandidateRead)
def delete_candidate(candidate_id: str, session: SessionDep):
    candidate = _candidate_or_404(session, candidate_id)
    return CandidateService(session).archive_candidate(candidate)


@router.post("/api/candidates/{candidate_id}/accept", response_model=CandidateRead)
def accept_candidate(candidate_id: str, session: SessionDep):
    candidate = _candidate_or_404(session, candidate_id)
    return CandidateService(session).accept_candidate(candidate)


@router.post("/api/candidates/{candidate_id}/edit-accept", response_model=CandidateRead)
def edit_accept_candidate(
    candidate_id: str,
    payload: CandidateEditAcceptRequest,
    session: SessionDep,
):
    candidate = _candidate_or_404(session, candidate_id)
    return CandidateService(session).edit_accept_candidate(
        candidate,
        payload.payload,
        resolution_note=payload.resolution_note,
        resolved_by=payload.resolved_by,
    )


@router.post("/api/candidates/{candidate_id}/reject", response_model=CandidateRead)
def reject_candidate(
    candidate_id: str,
    session: SessionDep,
    payload: CandidateActionRequest | None = None,
):
    candidate = _candidate_or_404(session, candidate_id)
    payload = payload or CandidateActionRequest()
    return CandidateService(session).reject_candidate(
        candidate,
        resolution_note=payload.resolution_note,
        resolved_by=payload.resolved_by,
    )


@router.post("/api/candidates/{candidate_id}/archive", response_model=CandidateRead)
def archive_candidate(
    candidate_id: str,
    session: SessionDep,
    payload: CandidateActionRequest | None = None,
):
    candidate = _candidate_or_404(session, candidate_id)
    payload = payload or CandidateActionRequest()
    return CandidateService(session).archive_candidate(
        candidate,
        resolution_note=payload.resolution_note,
        resolved_by=payload.resolved_by,
    )


@router.post("/api/candidates/{candidate_id}/needs-clarification", response_model=CandidateRead)
def needs_clarification_candidate(
    candidate_id: str,
    session: SessionDep,
    payload: CandidateActionRequest | None = None,
):
    candidate = _candidate_or_404(session, candidate_id)
    payload = payload or CandidateActionRequest()
    return CandidateService(session).needs_clarification(
        candidate,
        resolution_note=payload.resolution_note,
        resolved_by=payload.resolved_by,
    )


@router.post("/api/candidates/{candidate_id}/supersede", response_model=CandidateRead)
def supersede_candidate(
    candidate_id: str,
    payload: CandidateActionRequest,
    session: SessionDep,
):
    if not payload.supersedes_candidate_id:
        raise api_error(422, "validation_error", "supersedes_candidate_id is required.")
    candidate = _candidate_or_404(session, candidate_id)
    return CandidateService(session).supersede_candidate(
        candidate,
        payload.supersedes_candidate_id,
        resolution_note=payload.resolution_note,
        resolved_by=payload.resolved_by,
    )
