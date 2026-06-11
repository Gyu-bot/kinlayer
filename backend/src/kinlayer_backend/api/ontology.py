from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.repositories.ontology import OntologyRepository
from kinlayer_backend.schemas.ontology import (
    EdgeTypeList,
    ObservationTypeList,
    OntologyRead,
    PoliciesRead,
    RegistryList,
)
from kinlayer_backend.services.ontology import OntologyReadService

router = APIRouter(tags=["ontology"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/ontology", response_model=OntologyRead)
def get_ontology(session: SessionDep):
    return OntologyReadService(session).all_ontology()


@router.get("/api/ontology/edge-types", response_model=EdgeTypeList)
def get_edge_types(session: SessionDep):
    return {"items": OntologyRepository(session).edge_types()}


@router.get("/api/ontology/observation-types", response_model=ObservationTypeList)
def get_observation_types(session: SessionDep):
    return {"items": OntologyRepository(session).observation_types()}


@router.get("/api/ontology/entity-fact-types", response_model=RegistryList)
def get_entity_fact_types(session: SessionDep):
    return {"items": OntologyRepository(session).registry_values("fact_type")}


@router.get("/api/ontology/policies", response_model=PoliciesRead)
def get_policies(session: SessionDep):
    return OntologyReadService(session).policies()
