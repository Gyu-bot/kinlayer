from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi import HTTPException
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.repositories.relationships import RelationshipRepository
from kinlayer_backend.schemas.relationships import (
    EdgeCreate,
    EdgeList,
    EdgePatch,
    EdgeRead,
    EpisodeCreate,
    EpisodeList,
    EpisodeRead,
    ObservationCreate,
    ObservationList,
    ObservationPatch,
    ObservationRead,
)
from kinlayer_backend.services.relationships import RelationshipService
from kinlayer_backend.services.agent_operation_exports import AgentOperationService

router = APIRouter(tags=["relationships"])
SessionDep = Annotated[Session, Depends(get_session)]


def observation_payload(session: Session, observation):
    payload = ObservationRead.model_validate(observation).model_dump()
    related = RelationshipRepository(session).list_observation_entities(observation.id)
    payload["related_entities"] = related
    return payload


@router.post("/api/edges", response_model=EdgeRead, status_code=201)
def create_edge(payload: EdgeCreate, session: SessionDep):
    body = payload.model_dump()
    try:
        edge = RelationshipService(session).create_edge(body)
    except HTTPException as exc:
        AgentOperationService(session).record_edge_failure(
            body,
            operation_type="edge_create",
            source_path="/api/edges",
            exc=exc,
        )
        raise
    AgentOperationService(session).record_edge_success(
        body,
        edge_id=edge.id,
        operation_type="edge_create",
        source_path="/api/edges",
    )
    return edge


@router.get("/api/edges", response_model=EdgeList)
def list_edges(
    session: SessionDep,
    entity_id: str | None = None,
    from_entity_id: str | None = None,
    to_entity_id: str | None = None,
    relation_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = RelationshipRepository(session).list_edges(
        entity_id=entity_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relation_type=relation_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/edges/{edge_id}", response_model=EdgeRead)
def get_edge(edge_id: str, session: SessionDep):
    edge = RelationshipRepository(session).get_edge(edge_id)
    if not edge:
        raise api_error(404, "not_found", "Edge not found.")
    return edge


@router.patch("/api/edges/{edge_id}", response_model=EdgeRead)
def patch_edge(edge_id: str, payload: EdgePatch, session: SessionDep):
    edge = RelationshipRepository(session).get_edge(edge_id)
    if not edge:
        raise api_error(404, "not_found", "Edge not found.")
    body = {
        "from_entity_id": edge.from_entity_id,
        "to_entity_id": edge.to_entity_id,
        "created_by": "api_user",
        **payload.model_dump(exclude_unset=True),
    }
    try:
        edge = RelationshipService(session).patch_edge(edge, payload.model_dump(exclude_unset=True))
    except HTTPException as exc:
        AgentOperationService(session).record_edge_failure(
            body,
            operation_type="edge_update",
            source_path=f"/api/edges/{edge_id}",
            exc=exc,
            edge_id=edge_id,
        )
        raise
    AgentOperationService(session).record_edge_success(
        {
            "from_entity_id": edge.from_entity_id,
            "to_entity_id": edge.to_entity_id,
            "created_by": "api_user",
            **payload.model_dump(exclude_unset=True),
        },
        edge_id=edge.id,
        operation_type="edge_update",
        source_path=f"/api/edges/{edge_id}",
    )
    return edge


@router.delete("/api/edges/{edge_id}", response_model=EdgeRead)
def delete_edge(edge_id: str, session: SessionDep):
    edge = RelationshipRepository(session).get_edge(edge_id)
    if not edge:
        raise api_error(404, "not_found", "Edge not found.")
    return RelationshipService(session).delete_edge(edge)


@router.post("/api/observations", response_model=ObservationRead, status_code=201)
def create_observation(request: Request, payload: ObservationCreate, session: SessionDep):
    observation = RelationshipService(session, request.app.state.settings).create_observation(
        payload.model_dump()
    )
    return observation_payload(session, observation)


@router.get("/api/observations", response_model=ObservationList)
def list_observations(
    session: SessionDep,
    subject_entity_id: str | None = None,
    related_entity_id: str | None = None,
    observation_type: str | None = None,
    status: str | None = None,
    claim_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = RelationshipRepository(session).list_observations(
        subject_entity_id=subject_entity_id,
        related_entity_id=related_entity_id,
        observation_type=observation_type,
        status=status,
        claim_type=claim_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [observation_payload(session, item) for item in items],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.get("/api/observations/{observation_id}", response_model=ObservationRead)
def get_observation(observation_id: str, session: SessionDep):
    observation = RelationshipRepository(session).get_observation(observation_id)
    if not observation:
        raise api_error(404, "not_found", "Observation not found.")
    return observation_payload(session, observation)


@router.patch("/api/observations/{observation_id}", response_model=ObservationRead)
def patch_observation(
    request: Request,
    observation_id: str,
    payload: ObservationPatch,
    session: SessionDep,
):
    observation = RelationshipRepository(session).get_observation(observation_id)
    if not observation:
        raise api_error(404, "not_found", "Observation not found.")
    updated = RelationshipService(session, request.app.state.settings).patch_observation(
        observation,
        payload.model_dump(exclude_unset=True),
    )
    return observation_payload(session, updated)


@router.delete("/api/observations/{observation_id}", response_model=ObservationRead)
def delete_observation(observation_id: str, session: SessionDep):
    observation = RelationshipRepository(session).get_observation(observation_id)
    if not observation:
        raise api_error(404, "not_found", "Observation not found.")
    deleted = RelationshipService(session).delete_observation(observation)
    return observation_payload(session, deleted)


@router.post("/api/episodes", response_model=EpisodeRead, status_code=201)
def create_episode(payload: EpisodeCreate, session: SessionDep):
    return RelationshipService(session).create_episode(payload.model_dump())


@router.get("/api/episodes", response_model=EpisodeList)
def list_episodes(
    session: SessionDep,
    source_type: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = RelationshipRepository(session).list_episodes(
        source_type=source_type,
        actor=actor,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/episodes/{episode_id}", response_model=EpisodeRead)
def get_episode(episode_id: str, session: SessionDep):
    episode = RelationshipRepository(session).get_episode(episode_id)
    if not episode:
        raise api_error(404, "not_found", "Episode not found.")
    return episode
