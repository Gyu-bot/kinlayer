from typing import Annotated
import hashlib

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.reconciliation import (
    ReconciliationActionCreate,
    ReconciliationActionRead,
    ReconciliationEntitySnapshotList,
    ReconciliationCandidateEvidenceSnapshotList,
)
from kinlayer_backend.models import Candidate, CandidateEvidence
from kinlayer_backend.services.candidate_snapshots import candidate_snapshot
from kinlayer_backend.schemas.enrichment import (
    EnrichmentAnswerCreate,
    EnrichmentAnswerRead,
    EnrichmentAuthorizationCreate,
    EnrichmentAuthorizationRead,
)
from kinlayer_backend.services.enrichment import EnrichmentService
from kinlayer_backend.services.reconciliation import ReconciliationService
from kinlayer_backend.services.reconciliation import effective_context_policy

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])
SessionDep = Annotated[Session, Depends(get_session)]
EnrichmentCapabilityHeader = Annotated[
    str | None,
    Header(alias="X-Kinlayer-Enrichment-Capability"),
]


def require_enrichment_capability(
    capability: EnrichmentCapabilityHeader = None,
) -> str:
    if not capability:
        raise api_error(404, "not_found", "Enrichment resource not found.")
    return capability


@router.get("/entity-snapshots", response_model=ReconciliationEntitySnapshotList)
def list_reconciliation_entity_snapshots(
    request: Request,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return ReconciliationService(session, request.app.state.session_factory).list_entity_snapshots(
        limit, offset
    )


@router.get(
    "/candidate-evidence-snapshots",
    response_model=ReconciliationCandidateEvidenceSnapshotList,
)
def get_reconciliation_candidate_evidence_snapshots(
    session: SessionDep,
    candidate_id: list[str] = Query(min_length=1, max_length=50),
):
    if len(candidate_id) != len(set(candidate_id)):
        raise api_error(422, "validation_error", "Candidate IDs must be unique.")
    candidates = list(session.scalars(
        select(Candidate)
        .where(Candidate.id.in_(candidate_id))
        .options(selectinload(Candidate.evidence).selectinload(CandidateEvidence.episode))
        .order_by(Candidate.id)
    ).all())
    if {item.id for item in candidates} != set(candidate_id):
        raise api_error(404, "not_found", "Candidate evidence snapshot not found.")
    items = []
    for candidate in candidates:
        if len(candidate.evidence) > 20:
            raise api_error(
                409,
                "candidate_evidence_limit_exceeded",
                "Candidate has more than 20 evidence rows.",
            )
        snapshot = candidate_snapshot(session, candidate)
        evidence = []
        for row in sorted(candidate.evidence, key=lambda item: item.id):
            episode = row.episode
            if (
                not episode or episode.actor != "user"
                or episode.source_type != "agent_conversation"
                or not episode.source_ref or not row.excerpt or len(row.excerpt) > 500
                or episode.body_hash
                != "sha256:" + hashlib.sha256(episode.body_excerpt.encode()).hexdigest()
                or row.excerpt not in episode.body_excerpt
            ):
                continue
            evidence.append({
                "id": row.id, "episode_id": row.episode_id, "excerpt": row.excerpt,
                "source_type": episode.source_type, "actor": episode.actor,
                "body_hash": episode.body_hash,
                **effective_context_policy(candidate, episode),
            })
        items.append({**snapshot, "evidence": evidence})
    return {"items": items}


@router.post("/actions", response_model=ReconciliationActionRead)
def create_reconciliation_action(
    body: ReconciliationActionCreate,
    request: Request,
    session: SessionDep,
):
    return ReconciliationService(
        session,
        request.app.state.session_factory,
        request.app.state.settings.reconciliation_commitment_key,
    ).apply(body)


@router.get("/actions/{action_id}", response_model=ReconciliationActionRead)
def get_reconciliation_action(
    action_id: str,
    request: Request,
    session: SessionDep,
):
    return ReconciliationService(
        session,
        request.app.state.session_factory,
        request.app.state.settings.reconciliation_commitment_key,
    ).get(action_id)


@router.post("/enrichment-authorizations", response_model=EnrichmentAuthorizationRead)
def create_enrichment_authorization(
    body: EnrichmentAuthorizationCreate,
    request: Request,
    session: SessionDep,
):
    return EnrichmentService(
        session,
        request.app.state.session_factory,
        request.app.state.settings,
    ).stage(body)


@router.post("/enrichment-answers", response_model=EnrichmentAnswerRead)
def create_enrichment_answer(
    body: EnrichmentAnswerCreate,
    request: Request,
    answer_capability: Annotated[str, Depends(require_enrichment_capability)],
    session: SessionDep,
):
    return EnrichmentService(
        session,
        request.app.state.session_factory,
        request.app.state.settings,
    ).answer(body, answer_capability)


@router.get("/enrichment-answers/{action_id}", response_model=EnrichmentAnswerRead)
def get_enrichment_answer(
    action_id: str,
    request: Request,
    answer_capability: Annotated[str, Depends(require_enrichment_capability)],
    session: SessionDep,
):
    return EnrichmentService(
        session,
        request.app.state.session_factory,
        request.app.state.settings,
    ).get(action_id, answer_capability)
