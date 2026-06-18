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

STRONG_RESOLVE_THRESHOLD = 0.85
LOW_CONFIDENCE_THRESHOLD = 0.55
CLOSE_MATCH_DELTA = 0.08


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

    def create_entity(self, payload: dict[str, Any], commit: bool = True) -> Entity:
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
            return self.repository.add_entity(payload, commit=commit)
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

    def create_alias(
        self,
        entity: Entity,
        payload: dict[str, Any],
        commit: bool = True,
    ) -> EntityAlias:
        validate_common(payload, self.session)
        return self.repository.add_alias(entity.id, payload, commit=commit)

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

    def create_fact(self, payload: dict[str, Any], commit: bool = True) -> EntityFact:
        validate_common(payload, self.session, fact_type=True)
        if not self.repository.get_entity(payload["entity_id"]):
            raise api_error(404, "not_found", "Entity not found.")
        return self.repository.add_fact(payload, commit=commit)

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

    def resolve_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        surface = payload["surface"].strip()
        aliases = [alias.strip() for alias in payload.get("aliases", []) if alias.strip()]
        source = payload.get("source") or {}
        include_self = source.get("system_role") == "self" or source.get("include_self") is True
        queries = [surface, *aliases]
        matches = []
        for entity in self.repository.resolvable_entities(payload.get("entity_type")):
            if entity.system_role == "self" and not include_self:
                continue
            score, reasons = self._resolve_score(entity, queries)
            if score <= 0:
                continue
            matches.append(
                {
                    "entity_id": entity.id,
                    "display_name": entity.display_name,
                    "entity_type": entity.entity_type,
                    "score": score,
                    "match_reasons": sorted(reasons),
                }
            )
        matches.sort(key=lambda item: (-item["score"], item["display_name"]))
        limit = payload.get("limit", 5)
        return {
            "surface": surface,
            "ambiguity": self._resolve_ambiguity(matches),
            "matches": matches[:limit],
        }

    def _resolve_score(self, entity: Entity, queries: list[str]) -> tuple[float, set[str]]:
        reasons: set[str] = set()
        best_score = 0.0
        entity_names = [
            ("display_name", entity.display_name),
            ("canonical_name", entity.canonical_name or ""),
        ]
        alias_names = [
            ("alias", alias.alias)
            for alias in entity.aliases
            if alias.status == "active"
        ]
        for query in queries:
            normalized_query = normalize_name(query)
            query_tokens = set(normalized_query.split())
            for field, raw_name in [*entity_names, *alias_names]:
                normalized_name = normalize_name(raw_name)
                if not normalized_name:
                    continue
                score = self._name_match_score(normalized_query, query_tokens, normalized_name)
                if score <= 0:
                    continue
                best_score = max(best_score, score)
                if field == "display_name" and normalized_query == normalized_name:
                    reasons.add("exact_display_name")
                elif field == "canonical_name" and normalized_query == normalized_name:
                    reasons.add("exact_canonical_name")
                elif field == "alias" and normalized_query == normalized_name:
                    reasons.add("exact_alias")
                elif field == "alias":
                    reasons.add("normalized_alias")
                elif field == "canonical_name":
                    reasons.add("normalized_canonical_name")
                else:
                    reasons.add("normalized_display_name")
                if 0 < score < 0.85:
                    reasons.add("pg_trgm_name_alias")
        if entity.confirmation_status == "confirmed" and best_score > 0:
            best_score = min(1.0, best_score + 0.05)
            reasons.add("confirmation_policy")
        return round(best_score, 3), reasons

    def _name_match_score(
        self,
        normalized_query: str,
        query_tokens: set[str],
        normalized_name: str,
    ) -> float:
        if normalized_query == normalized_name:
            return 1.0
        if normalized_name in query_tokens:
            return 0.92
        name_tokens = set(normalized_name.split())
        if normalized_name in normalized_query or normalized_query in normalized_name:
            return 0.78
        if name_tokens & query_tokens:
            return 0.65
        return self._trigram_similarity(normalized_query, normalized_name) * 0.75

    def _trigram_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right or left in right or right in left:
            return 1.0
        left_trigrams = self._trigrams(left)
        right_trigrams = self._trigrams(right)
        if not left_trigrams or not right_trigrams:
            return 0.0
        return len(left_trigrams & right_trigrams) / len(left_trigrams | right_trigrams)

    def _trigrams(self, value: str) -> set[str]:
        padded = f"  {value} "
        return {padded[index : index + 3] for index in range(len(padded) - 2)}

    def _resolve_ambiguity(self, matches: list[dict[str, Any]]) -> str:
        if not matches:
            return "no_match"
        if matches[0]["score"] < LOW_CONFIDENCE_THRESHOLD:
            return "low_confidence_match"
        if len(matches) > 1 and matches[0]["score"] - matches[1]["score"] <= CLOSE_MATCH_DELTA:
            return "multiple_close_matches"
        if matches[0]["score"] >= STRONG_RESOLVE_THRESHOLD:
            return "single_strong_match"
        return "low_confidence_match"
