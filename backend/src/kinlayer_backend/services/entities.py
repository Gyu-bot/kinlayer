from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import Entity, EntityAlias, EntityFact
from kinlayer_backend.repositories.entities import EntityRepository
from kinlayer_backend.services.ontology import (
    CONFIRMATION_STATUSES,
    CREATED_BY_VALUES,
    ENTITY_STATUSES,
    RECORD_STATUSES,
    allowed_values,
    is_allowed_registry_value,
    normalize_name,
)


def validate_common(payload: dict[str, Any], session: Session, fact_type: bool = False) -> None:
    checks = {
        "sensitivity": allowed_values("sensitivity"),
        "ai_use_policy": allowed_values("ai_use_policy"),
        "claim_type": allowed_values("claim_type"),
        "created_by": CREATED_BY_VALUES,
        "confirmation_status": CONFIRMATION_STATUSES,
        "status": RECORD_STATUSES | ENTITY_STATUSES | {"confirmed"},
    }
    if "entity_type" in payload and not is_allowed_registry_value(
        session, "entity_type", payload["entity_type"]
    ):
        raise api_error(422, "validation_error", "Invalid entity_type.")
    if fact_type and "fact_type" in payload and not is_allowed_registry_value(
        session, "fact_type", payload["fact_type"]
    ):
        raise api_error(422, "validation_error", "Invalid fact_type.")
    for key, values in checks.items():
        if key in payload and payload[key] is not None and payload[key] not in values:
            raise api_error(422, "validation_error", f"Invalid {key}.")


class EntityService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = EntityRepository(session)

    def create_entity(self, payload: dict[str, Any]) -> Entity:
        validate_common(payload, self.session)
        if payload.get("system_role") == "self":
            payload["entity_type"] = "person"
            payload["is_system"] = True
            if self.repository.find_self():
                raise api_error(409, "conflict", "Protected self entity already exists.")
        payload["display_name"] = payload["display_name"].strip()
        payload["canonical_name"] = normalize_name(
            payload.get("canonical_name") or payload["display_name"]
        )
        try:
            return self.repository.add_entity(payload)
        except IntegrityError as exc:
            self.session.rollback()
            raise api_error(409, "conflict", "Entity conflicts with an existing record.") from exc

    def patch_entity(self, entity: Entity, payload: dict[str, Any]) -> Entity:
        validate_common(payload, self.session)
        if entity.system_role == "self":
            if payload.get("system_role") != "self" and "system_role" in payload:
                raise api_error(403, "forbidden", "Protected self cannot lose system role.")
            if payload.get("status") == "deleted":
                raise api_error(403, "forbidden", "Protected self cannot be deleted.")
        if "display_name" in payload and payload["display_name"]:
            payload["display_name"] = payload["display_name"].strip()
        if "canonical_name" in payload and payload["canonical_name"] is not None:
            payload["canonical_name"] = normalize_name(payload["canonical_name"])
        elif "display_name" in payload and payload["display_name"]:
            payload["canonical_name"] = normalize_name(payload["display_name"])
        for key, value in payload.items():
            setattr(entity, key, value)
        self.repository.commit_refresh([entity])
        return entity

    def delete_entity(self, entity: Entity) -> Entity:
        if entity.system_role == "self":
            raise api_error(403, "forbidden", "Protected self cannot be deleted.")
        entity.status = "deleted"
        entity.confirmation_status = "deprecated"
        self.repository.commit_refresh([entity])
        return entity

    def create_alias(self, entity: Entity, payload: dict[str, Any]) -> EntityAlias:
        validate_common(payload, self.session)
        return self.repository.add_alias(entity.id, payload)

    def patch_alias(self, alias: EntityAlias, payload: dict[str, Any]) -> EntityAlias:
        validate_common(payload, self.session)
        if "alias" in payload and payload["alias"]:
            payload["normalized_alias"] = normalize_name(payload["alias"])
        for key, value in payload.items():
            setattr(alias, key, value)
        self.repository.commit_refresh([alias])
        return alias

    def delete_alias(self, alias: EntityAlias) -> EntityAlias:
        alias.status = "deleted"
        self.repository.commit_refresh([alias])
        return alias

    def create_fact(self, payload: dict[str, Any]) -> EntityFact:
        validate_common(payload, self.session, fact_type=True)
        if not self.repository.get_entity(payload["entity_id"]):
            raise api_error(404, "not_found", "Entity not found.")
        return self.repository.add_fact(payload)

    def patch_fact(self, fact: EntityFact, payload: dict[str, Any]) -> EntityFact:
        validate_common(payload, self.session, fact_type="fact_type" in payload)
        for key, value in payload.items():
            setattr(fact, key, value)
        self.repository.commit_refresh([fact])
        return fact

    def delete_fact(self, fact: EntityFact) -> EntityFact:
        fact.status = "deleted"
        self.repository.commit_refresh([fact])
        return fact
