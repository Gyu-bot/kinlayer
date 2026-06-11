from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.graph import EgoGraph
from kinlayer_backend.services.graph import GraphService

router = APIRouter(tags=["graph"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/graph/ego/{entity_id}", response_model=EgoGraph)
def get_ego_graph(
    entity_id: str,
    session: SessionDep,
    depth: int = Query(default=1),
    relation_type: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
):
    return GraphService(session).ego_graph(
        entity_id,
        depth=depth,
        relation_type=relation_type,
        status=status,
        sensitivity=sensitivity,
    )
