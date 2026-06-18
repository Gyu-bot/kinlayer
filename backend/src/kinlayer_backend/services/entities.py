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
DUPLICATE_MATCH_THRESHOLD = 0.68
DEFAULT_MERGE_FIELDS = ["aliases", "profile_facts", "edges", "observations"]


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

    def duplicate_candidates(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = self.repository.get_entity(payload["source_entity_id"])
        if not source:
            raise api_error(404, "not_found", "Source entity not found.")
        if source.system_role == "self":
            raise api_error(403, "forbidden", "Protected self cannot be used for person merge.")
        matches = []
        for target in self.repository.resolvable_entities(source.entity_type):
            if target.id == source.id or target.system_role == "self":
                continue
            score, reasons = self._duplicate_score(source, target)
            if score < DUPLICATE_MATCH_THRESHOLD:
                continue
            action = "create_merge_candidate" if score >= 0.75 else "needs_clarification"
            reason = self._duplicate_reason(source, target, reasons)
            matches.append(
                {
                    "source_entity_id": source.id,
                    "target_entity_id": target.id,
                    "display_name": target.display_name,
                    "score": score,
                    "match_reasons": sorted(reasons),
                    "recommended_action": action,
                    "reason": reason,
                    "fields_to_merge": DEFAULT_MERGE_FIELDS,
                    "risk_notes": self._duplicate_risk_notes(score, reasons),
                }
            )
        matches.sort(key=lambda item: (-item["score"], item["display_name"]))
        limit = payload.get("limit", 5)
        ranked = matches[:limit]
        recommended_action = self._duplicate_action(ranked)
        created_candidate = None
        if payload.get("create_candidate"):
            if recommended_action != "create_merge_candidate" or not ranked:
                raise api_error(
                    409,
                    "conflict",
                    "Duplicate result is not strong enough to create a merge candidate.",
                )
            if not payload.get("evidence"):
                raise api_error(
                    422,
                    "validation_error",
                    "Merge candidate creation requires evidence.",
                )
            top = ranked[0]
            from kinlayer_backend.services.candidates import CandidateService

            created_candidate = CandidateService(self.session).create_candidate(
                {
                    "candidate_type": "merge",
                    "target_entity_id": top["target_entity_id"],
                    "payload": {
                        "source_entity_id": source.id,
                        "target_entity_id": top["target_entity_id"],
                        "reason": top["reason"],
                        "fields_to_merge": top["fields_to_merge"],
                        "merge_plan": {
                            "aliases": "copy_non_conflicting",
                            "profile_facts": "copy_non_conflicting",
                            "edges": "repoint_without_self_or_duplicate_edges",
                            "observations": "repoint_related_entities",
                        },
                        "field_conflict_policy": {
                            "display_name": "keep_target",
                            "canonical_name": "keep_target",
                            "sensitivity": "use_more_restrictive",
                            "ai_use_policy": "use_more_restrictive",
                        },
                        "risk_notes": top["risk_notes"],
                        "merged_entity_ref": f"entities:{top['target_entity_id']}",
                    },
                    "evidence": payload["evidence"],
                    "confidence": top["score"],
                    "sensitivity": source.sensitivity or "medium",
                    "suggested_action": "review",
                    "created_by": payload.get("created_by") or "ai_agent",
                }
            )
        return {
            "source_entity_id": source.id,
            "recommended_action": recommended_action,
            "candidates": ranked,
            "created_candidate": created_candidate,
        }

    def _duplicate_score(self, source: Entity, target: Entity) -> tuple[float, set[str]]:
        reasons: set[str] = set()
        score = 0.0
        source_aliases = self._active_alias_names(source)
        target_aliases = self._active_alias_names(target)
        source_names = self._identity_names(source)
        target_names = self._identity_names(target)
        source_normalized = {normalize_name(name) for name in source_names if name}
        target_normalized = {normalize_name(name) for name in target_names if name}
        source_alias_normalized = {normalize_name(name) for name in source_aliases if name}
        target_alias_normalized = {normalize_name(name) for name in target_aliases if name}

        if source_alias_normalized & target_alias_normalized:
            reasons.add("exact_alias_overlap")
            score = max(score, 1.0)
        if source_normalized & target_normalized:
            reasons.add("exact_name_overlap")
            score = max(score, 0.95)

        for left in source_normalized:
            left_tokens = set(left.split())
            for right in target_normalized:
                if not left or not right:
                    continue
                right_tokens = set(right.split())
                if left_tokens & right_tokens:
                    reasons.add("normalized_name_overlap")
                    score = max(score, 0.72)
                similarity = self._trigram_similarity(left, right)
                if similarity >= 0.35:
                    reasons.add("fuzzy_name_similarity")
                    score = max(score, round(0.68 + min(similarity, 1.0) * 0.2, 3))
        return round(score, 3), reasons

    def _identity_names(self, entity: Entity) -> list[str]:
        return [
            entity.display_name,
            entity.canonical_name or "",
            *self._active_alias_names(entity),
        ]

    def _active_alias_names(self, entity: Entity) -> list[str]:
        return [alias.alias for alias in entity.aliases if alias.status == "active"]

    def _duplicate_action(self, matches: list[dict[str, Any]]) -> str:
        if not matches:
            return "no_match"
        if len(matches) > 1 and matches[0]["score"] - matches[1]["score"] <= CLOSE_MATCH_DELTA:
            return "needs_clarification"
        if matches[0]["score"] >= 0.75:
            return "create_merge_candidate"
        return "needs_clarification"

    def _duplicate_reason(self, source: Entity, target: Entity, reasons: set[str]) -> str:
        reason_list = ", ".join(sorted(reasons)) or "weak duplicate signal"
        return f"{source.display_name} and {target.display_name} share duplicate signals: {reason_list}."

    def _duplicate_risk_notes(self, score: float, reasons: set[str]) -> list[str]:
        notes = ["Review before merging; Kinlayer never auto-merges duplicate people."]
        if "exact_alias_overlap" not in reasons and score < 0.9:
            notes.append("Name similarity is not enough for direct canonical write.")
        return notes

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
