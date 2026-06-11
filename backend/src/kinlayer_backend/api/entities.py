from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.database import get_session
from kinlayer_backend.repositories.entities import EntityRepository
from kinlayer_backend.schemas.entities import (
    AliasCreate,
    AliasList,
    AliasPatch,
    AliasRead,
    EntityCreate,
    EntityFactCreate,
    EntityFactList,
    EntityFactPatch,
    EntityFactRead,
    EntityList,
    EntityPatch,
    EntityRead,
)
from kinlayer_backend.services.entities import EntityService

router = APIRouter(tags=["entities"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/entities", response_model=EntityRead, status_code=201)
def create_entity(payload: EntityCreate, session: SessionDep):
    return EntityService(session).create_entity(payload.model_dump())


@router.get("/api/entities", response_model=EntityList)
def list_entities(
    session: SessionDep,
    q: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
    system_role: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = EntityRepository(session).list_entities(
        q=q,
        entity_type=entity_type,
        status=status,
        sensitivity=sensitivity,
        system_role=system_role,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/entities/{entity_id}", response_model=EntityRead)
def get_entity(entity_id: str, session: SessionDep):
    entity = EntityRepository(session).get_entity(entity_id)
    if not entity:
        raise api_error(404, "not_found", "Entity not found.")
    return entity


@router.patch("/api/entities/{entity_id}", response_model=EntityRead)
def patch_entity(entity_id: str, payload: EntityPatch, session: SessionDep):
    entity = EntityRepository(session).get_entity(entity_id)
    if not entity:
        raise api_error(404, "not_found", "Entity not found.")
    return EntityService(session).patch_entity(entity, payload.model_dump(exclude_unset=True))


@router.delete("/api/entities/{entity_id}", response_model=EntityRead)
def delete_entity(entity_id: str, session: SessionDep):
    entity = EntityRepository(session).get_entity(entity_id)
    if not entity:
        raise api_error(404, "not_found", "Entity not found.")
    return EntityService(session).delete_entity(entity)


@router.post("/api/entities/{entity_id}/aliases", response_model=AliasRead, status_code=201)
def create_alias(entity_id: str, payload: AliasCreate, session: SessionDep):
    entity = EntityRepository(session).get_entity(entity_id)
    if not entity:
        raise api_error(404, "not_found", "Entity not found.")
    return EntityService(session).create_alias(entity, payload.model_dump())


@router.get("/api/entities/{entity_id}/aliases", response_model=AliasList)
def list_aliases(entity_id: str, session: SessionDep):
    if not EntityRepository(session).get_entity(entity_id):
        raise api_error(404, "not_found", "Entity not found.")
    items, total = EntityRepository(session).list_aliases(entity_id)
    return {"items": items, "limit": 200, "offset": 0, "total": total}


@router.patch("/api/aliases/{alias_id}", response_model=AliasRead)
def patch_alias(alias_id: str, payload: AliasPatch, session: SessionDep):
    alias = EntityRepository(session).get_alias(alias_id)
    if not alias:
        raise api_error(404, "not_found", "Alias not found.")
    return EntityService(session).patch_alias(alias, payload.model_dump(exclude_unset=True))


@router.delete("/api/aliases/{alias_id}", response_model=AliasRead)
def delete_alias(alias_id: str, session: SessionDep):
    alias = EntityRepository(session).get_alias(alias_id)
    if not alias:
        raise api_error(404, "not_found", "Alias not found.")
    return EntityService(session).delete_alias(alias)


@router.post("/api/entity-facts", response_model=EntityFactRead, status_code=201)
def create_fact(payload: EntityFactCreate, session: SessionDep):
    return EntityService(session).create_fact(payload.model_dump())


@router.get("/api/entity-facts", response_model=EntityFactList)
def list_facts(
    session: SessionDep,
    entity_id: str | None = None,
    fact_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = EntityRepository(session).list_facts(
        entity_id=entity_id,
        fact_type=fact_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/api/entity-facts/{fact_id}", response_model=EntityFactRead)
def get_fact(fact_id: str, session: SessionDep):
    fact = EntityRepository(session).get_fact(fact_id)
    if not fact:
        raise api_error(404, "not_found", "Entity fact not found.")
    return fact


@router.patch("/api/entity-facts/{fact_id}", response_model=EntityFactRead)
def patch_fact(fact_id: str, payload: EntityFactPatch, session: SessionDep):
    fact = EntityRepository(session).get_fact(fact_id)
    if not fact:
        raise api_error(404, "not_found", "Entity fact not found.")
    return EntityService(session).patch_fact(fact, payload.model_dump(exclude_unset=True))


@router.delete("/api/entity-facts/{fact_id}", response_model=EntityFactRead)
def delete_fact(fact_id: str, session: SessionDep):
    fact = EntityRepository(session).get_fact(fact_id)
    if not fact:
        raise api_error(404, "not_found", "Entity fact not found.")
    return EntityService(session).delete_fact(fact)
