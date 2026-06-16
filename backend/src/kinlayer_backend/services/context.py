from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    AllowedEdgeType,
    EdgeEvidence,
    Entity,
    EntityAlias,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.services.retrieval import RetrievalMatch, RetrievalResult, RetrievalService

SURFACE_BUCKETS = ["direct_surface", "conditional_surface", "internal_only", "blocked"]


class ContextService:
    def __init__(self, session: Session):
        self.session = session
        self.retrieval = RetrievalService(session)

    def retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._retrieve(payload)
        matches = [self._match_dict(match) for match in result.matches]
        observations = [
            self._observation_dict(observation)
            for match in result.matches
            for observation in match.observations
            if self._should_surface_observation(observation)
        ]
        return {
            "matched_entities": matches,
            "observations": observations,
            "scores": {match.entity_id: match.score for match in result.matches},
            "match_reasons": {match.entity_id: match.match_reasons for match in result.matches},
            "score_breakdown": {
                match.entity_id: match.score_breakdown for match in result.matches
            },
            "ambiguity_detected": result.ambiguity_detected,
            "debug": result.debug if payload.get("include_debug") else {},
        }

    def pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._retrieve(payload)
        confidence = result.matches[0].confidence_band if result.matches else "low"
        response_policy = self._suggested_response_policy(result, confidence)
        buckets = {
            bucket: [self._match_dict(match) for match in result.surface_buckets[bucket]]
            for bucket in SURFACE_BUCKETS
        }
        all_observations = [
            observation
            for match in result.matches
            for observation in match.observations
            if self._should_surface_observation(observation)
        ]
        pack = {
            "confidence": confidence,
            "suggested_response_policy": response_policy,
            "ambiguity_detected": result.ambiguity_detected,
            "matched_entities": [self._match_dict(match) for match in result.matches],
            "buckets": buckets,
            "recent_context": [
                self._observation_dict(item)
                for item in all_observations
                if "recent" in item.match_reasons
            ],
            "stable_context": [
                self._observation_dict(item)
                for item in all_observations
                if item.status == "active" and "recent" not in item.match_reasons
            ],
            "cautions": [
                self._observation_dict(item)
                for item in all_observations
                if item.sensitivity == "high" or item.ai_use_policy == "ask_before_use"
            ],
            "provenance": self._provenance_for_matches(result.matches),
        }
        return {
            "context_pack": pack,
            "debug": result.debug if payload.get("include_debug") else {},
        }

    def context_card(self, entity_id: str) -> dict[str, Any]:
        entity = self.session.get(Entity, entity_id)
        if not entity:
            raise api_error(404, "not_found", "Entity not found.")
        aliases = self._aliases(entity_id)
        facts = self._facts(entity_id)
        edges = self._edges(entity_id)
        observations = self._observations(entity_id)
        stable = [
            item for item in observations
            if item.observation_type not in {"recent_interaction", "communication_preference", "caution"}
        ]
        recent = [item for item in observations if item.observation_type == "recent_interaction"]
        communication = [
            item for item in observations if item.observation_type == "communication_preference"
        ]
        cautions = [
            item
            for item in observations
            if item.observation_type == "caution"
            or item.sensitivity == "high"
            or item.ai_use_policy in {"ask_before_use", "never_surface"}
        ]
        evidence = self._provenance_for_records(facts, edges, observations)
        return {
            "entity": entity,
            "aliases": aliases,
            "profile_facts": facts,
            "relationship_edges": edges,
            "stable_context": stable,
            "recent_context": recent,
            "communication_context": communication,
            "cautions": cautions,
            "provenance_summary": {
                "fact_count": len(facts),
                "edge_count": len(edges),
                "observation_count": len(observations),
                "evidence_count": len(evidence),
                "evidence": evidence,
            },
            "retrieval_hints": {
                "entity_id": entity.id,
                "canonical_name": entity.canonical_name,
                "aliases": [alias.alias for alias in aliases],
                "entity_type": entity.entity_type,
            },
        }

    def _retrieve(self, payload: dict[str, Any]) -> RetrievalResult:
        return self.retrieval.retrieve(
            query=payload["query"],
            entity_hints=payload.get("entity_hints") or [],
            focal_entity_id=payload.get("focal_entity_id"),
            query_embedding=payload.get("query_embedding"),
            limit=payload.get("limit") or 10,
        )

    def _suggested_response_policy(self, result: RetrievalResult, confidence: str) -> str:
        if not result.matches:
            return "no_relevant_context"
        if result.ambiguity_detected or confidence == "low":
            return "ask_clarifying_question"
        if result.matches and all(match.surface_bucket == "blocked" for match in result.matches):
            return "blocked_by_policy"
        if result.surface_buckets["direct_surface"] and confidence == "high":
            return "natural_use"
        return "conditional_use"

    def _match_dict(self, match: RetrievalMatch) -> dict[str, Any]:
        return {
            **asdict(match),
            "profile_facts": self._facts(match.entity_id),
            "observations": [
                self._observation_dict(observation)
                for observation in match.observations
                if self._should_surface_observation(observation)
            ],
        }

    def _should_surface_observation(self, observation) -> bool:
        return observation.status == "active" and observation.surface_eligible

    def _observation_dict(self, observation) -> dict[str, Any]:
        raw = asdict(observation)
        raw.pop("surface_eligible", None)
        return raw

    def _aliases(self, entity_id: str) -> list[EntityAlias]:
        statement = (
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity_id, EntityAlias.status == "active")
            .order_by(EntityAlias.created_at)
        )
        return self.session.execute(statement).scalars().all()

    def _facts(self, entity_id: str) -> list[EntityFact]:
        statement = (
            select(EntityFact)
            .where(EntityFact.entity_id == entity_id, EntityFact.status == "active")
            .order_by(EntityFact.created_at.desc())
        )
        return self.session.execute(statement).scalars().all()

    def _edges(self, entity_id: str) -> list[EntityEdge]:
        from_entity = aliased(Entity)
        to_entity = aliased(Entity)
        statement = (
            select(EntityEdge)
            .join(AllowedEdgeType, AllowedEdgeType.relation_type == EntityEdge.relation_type)
            .join(from_entity, from_entity.id == EntityEdge.from_entity_id)
            .join(to_entity, to_entity.id == EntityEdge.to_entity_id)
            .where(
                or_(
                    EntityEdge.from_entity_id == entity_id,
                    EntityEdge.to_entity_id == entity_id,
                ),
                EntityEdge.status == "active",
                AllowedEdgeType.active.is_(True),
                from_entity.entity_type == AllowedEdgeType.from_entity_type,
                to_entity.entity_type == AllowedEdgeType.to_entity_type,
            )
            .order_by(EntityEdge.created_at.desc())
        )
        return self.session.execute(statement).scalars().all()

    def _observations(self, entity_id: str) -> list[Observation]:
        statement = (
            select(Observation)
            .outerjoin(ObservationEntity, ObservationEntity.observation_id == Observation.id)
            .where(
                or_(
                    Observation.subject_entity_id == entity_id,
                    ObservationEntity.entity_id == entity_id,
                ),
                Observation.status == "active",
            )
            .distinct()
            .order_by(Observation.created_at.desc())
        )
        return self.session.execute(statement).scalars().all()

    def _provenance_for_matches(self, matches: list[RetrievalMatch]) -> list[dict[str, Any]]:
        observation_ids = {
            observation.observation_id
            for match in matches
            for observation in match.observations
            if observation.status == "active"
        }
        if not observation_ids:
            return []
        statement = select(ObservationEvidence).where(
            ObservationEvidence.observation_id.in_(observation_ids)
        )
        return [
            self._provenance_item("observation", row.observation_id, row)
            for row in self.session.execute(statement).scalars().all()
        ]

    def _provenance_for_records(
        self,
        facts: list[EntityFact],
        edges: list[EntityEdge],
        observations: list[Observation],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        fact_ids = [item.id for item in facts]
        edge_ids = [item.id for item in edges]
        observation_ids = [item.id for item in observations]
        if fact_ids:
            rows = self.session.execute(
                select(EntityFactEvidence).where(EntityFactEvidence.entity_fact_id.in_(fact_ids))
            ).scalars().all()
            evidence.extend(self._provenance_item("fact", row.entity_fact_id, row) for row in rows)
        if edge_ids:
            rows = self.session.execute(
                select(EdgeEvidence).where(EdgeEvidence.edge_id.in_(edge_ids))
            ).scalars().all()
            evidence.extend(self._provenance_item("edge", row.edge_id, row) for row in rows)
        if observation_ids:
            rows = self.session.execute(
                select(ObservationEvidence).where(
                    ObservationEvidence.observation_id.in_(observation_ids)
                )
            ).scalars().all()
            evidence.extend(
                self._provenance_item("observation", row.observation_id, row) for row in rows
            )
        return evidence

    def _provenance_item(self, record_type: str, record_id: str, row: Any) -> dict[str, Any]:
        return {
            "record_type": record_type,
            "record_id": record_id,
            "episode_id": row.episode_id,
            "excerpt": row.excerpt,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "created_at": row.created_at,
        }
