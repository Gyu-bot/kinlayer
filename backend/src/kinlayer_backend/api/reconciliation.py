from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.reconciliation import (
    ReconciliationActionCreate,
    ReconciliationActionRead,
    ReconciliationEntitySnapshotList,
)
from kinlayer_backend.services.reconciliation import ReconciliationService

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.get("/entity-snapshots", response_model=ReconciliationEntitySnapshotList)
def list_reconciliation_entity_snapshots(
    request: Request,
    session: Session = Depends(get_session),
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return ReconciliationService(session, request.app.state.session_factory).list_entity_snapshots(
        limit, offset
    )


@router.post("/actions", response_model=ReconciliationActionRead)
def create_reconciliation_action(
    body: ReconciliationActionCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    return ReconciliationService(session, request.app.state.session_factory).apply(body)


@router.get("/actions/{action_id}", response_model=ReconciliationActionRead)
def get_reconciliation_action(
    action_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    return ReconciliationService(session, request.app.state.session_factory).get(action_id)
