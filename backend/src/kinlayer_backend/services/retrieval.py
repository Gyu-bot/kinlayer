from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from sqlalchemy.orm import Session

from kinlayer_backend.models import Entity, EntityAlias, Observation
from kinlayer_backend.repositories.retrieval import RetrievalRepository
from kinlayer_backend.services.ontology import normalize_name

SCORE_WEIGHTS = {
    "entity_hint": 0.25,
    "alias_name": 0.20,
    "semantic_observation": 0.20,
    "recency": 0.15,
    "graph_proximity": 0.10,
    "confirmation_policy": 0.10,
}
CONFIDENCE_HIGH_THRESHOLD = 0.75
CONFIDENCE_MEDIUM_THRESHOLD = 0.45
AMBIGUOUS_HIGH_CONFIDENCE_CAP = 0.74


@dataclass
class RetrievedObservation:
    observation_id: str
    content: str
    score: float
    match_reasons: list[str]
    sensitivity: str
    ai_use_policy: str
    status: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_at: datetime | None = None
    created_at: datetime | None = None
    surface_eligible: bool = True


@dataclass
class RetrievalMatch:
    entity_id: str
    display_name: str
    entity_type: str
    score: float
    confidence_band: str
    match_reasons: list[str]
    score_breakdown: dict[str, float]
    penalties: dict[str, float]
    surface_bucket: str
    sensitivity: str
    ai_use_policy: str
    confirmation_status: str
    observations: list[RetrievedObservation] = field(default_factory=list)


@dataclass
class RetrievalResult:
    matches: list[RetrievalMatch]
    surface_buckets: dict[str, list[RetrievalMatch]]
    ambiguity_detected: bool
    debug: dict[str, Any]


class RetrievalService:
    def __init__(self, session: Session):
        self.repository = RetrievalRepository(session)

    def retrieve(
        self,
        query: str,
        entity_hints: list[str] | None = None,
        focal_entity_id: str | None = None,
        query_embedding: list[float] | None = None,
        limit: int = 10,
    ) -> RetrievalResult:
        normalized_query = normalize_name(query)
        query_tokens = set(normalized_query.split())
        hints = set(entity_hints or [])
        entities = self.repository.entities()
        aliases = self.repository.aliases()
        observations = self.repository.observations()
        aliases_by_entity = self._aliases_by_entity(aliases)
        observations_by_entity = self._observations_by_entity(observations)
        graph_neighbors = self._graph_neighbors({entity.id for entity in entities}, focal_entity_id)

        scored = [
            self._score_entity(
                entity=entity,
                aliases=aliases_by_entity.get(entity.id, []),
                observations=observations_by_entity.get(entity.id, []),
                normalized_query=normalized_query,
                query_tokens=query_tokens,
                hints=hints,
                graph_neighbors=graph_neighbors,
                query_embedding=query_embedding,
            )
            for entity in entities
        ]
        matches = [match for match in scored if match.score > 0 or match.observations]
        ambiguity_detected = self._is_ambiguous(matches, hints)
        if ambiguity_detected:
            for match in matches:
                if match.score >= CONFIDENCE_HIGH_THRESHOLD:
                    match.penalties["ambiguity"] = round(
                        match.penalties.get("ambiguity", 0) + match.score - AMBIGUOUS_HIGH_CONFIDENCE_CAP,
                        3,
                    )
                    match.score = AMBIGUOUS_HIGH_CONFIDENCE_CAP
                match.confidence_band = self._confidence_band(match.score)
                if match.surface_bucket == "direct_surface":
                    match.surface_bucket = "conditional_surface"

        matches.sort(key=lambda item: (-item.score, item.display_name))
        matches = matches[:limit]
        return RetrievalResult(
            matches=matches,
            surface_buckets=self._surface_buckets(matches),
            ambiguity_detected=ambiguity_detected,
            debug={
                "score_weights": SCORE_WEIGHTS,
                "confidence_thresholds": {
                    "high": CONFIDENCE_HIGH_THRESHOLD,
                    "medium": CONFIDENCE_MEDIUM_THRESHOLD,
                },
                "query": query,
            },
        )

    def _score_entity(
        self,
        entity: Entity,
        aliases: list[EntityAlias],
        observations: list[Observation],
        normalized_query: str,
        query_tokens: set[str],
        hints: set[str],
        graph_neighbors: set[str],
        query_embedding: list[float] | None,
    ) -> RetrievalMatch:
        score_breakdown = {key: 0.0 for key in SCORE_WEIGHTS}
        penalties: dict[str, float] = {}
        reasons: list[str] = []
        names = [entity.display_name, entity.canonical_name or "", *(alias.alias for alias in aliases)]
        normalized_names = [normalize_name(name) for name in names if name]

        if entity.id in hints:
            score_breakdown["entity_hint"] = SCORE_WEIGHTS["entity_hint"]
            reasons.append("entity_hint")

        if self._matches_name_or_alias(normalized_query, query_tokens, normalized_names):
            score_breakdown["alias_name"] = SCORE_WEIGHTS["alias_name"]
            reasons.extend(self._name_reasons(normalized_query, query_tokens, normalized_names))

        retrieved_observations = self._score_observations(
            observations,
            normalized_query,
            query_tokens,
            query_embedding,
        )
        if retrieved_observations:
            best_observation = max(retrieved_observations, key=lambda item: item.score)
            if best_observation.score >= 0.70:
                score_breakdown["semantic_observation"] = SCORE_WEIGHTS["semantic_observation"]
                reasons.append("pgvector_observation")
            if any("recent" in item.match_reasons for item in retrieved_observations):
                score_breakdown["recency"] = SCORE_WEIGHTS["recency"]
                reasons.append("recency")

        if entity.id in graph_neighbors:
            score_breakdown["graph_proximity"] = SCORE_WEIGHTS["graph_proximity"]
            reasons.append("graph_proximity")

        if entity.confirmation_status == "confirmed" and entity.ai_use_policy != "never_surface":
            score_breakdown["confirmation_policy"] = SCORE_WEIGHTS["confirmation_policy"]
            reasons.append("confirmation_policy")

        score = round(sum(score_breakdown.values()), 3)
        score = self._apply_penalties(entity, observations, score, penalties)
        bucket = self._surface_bucket(entity, observations, score)
        return RetrievalMatch(
            entity_id=entity.id,
            display_name=entity.display_name,
            entity_type=entity.entity_type,
            score=score,
            confidence_band=self._confidence_band(score),
            match_reasons=sorted(set(reasons)),
            score_breakdown=score_breakdown,
            penalties=penalties,
            surface_bucket=bucket,
            sensitivity=entity.sensitivity,
            ai_use_policy=entity.ai_use_policy,
            confirmation_status=entity.confirmation_status,
            observations=retrieved_observations,
        )

    def _score_observations(
        self,
        observations: list[Observation],
        normalized_query: str,
        query_tokens: set[str],
        query_embedding: list[float] | None,
    ) -> list[RetrievedObservation]:
        results: list[RetrievedObservation] = []
        now = datetime.now(UTC)
        for observation in observations:
            reasons = []
            semantic_score = 0.0
            vector = self._parse_vector(observation.embedding)
            if query_embedding and vector:
                semantic_score = self._cosine_similarity(query_embedding, vector)
                if semantic_score >= 0.70:
                    reasons.append("pgvector_observation")
            lexical_score = self._token_overlap(normalized_query, normalize_name(observation.content))
            if lexical_score >= 0.20:
                reasons.append("content_overlap")
            has_content_match = semantic_score >= 0.70 or lexical_score >= 0.20
            recency_score = self._recency_score(observation, now) if has_content_match else 0.0
            if recency_score > 0:
                reasons.append("recent")
            score = round(max(semantic_score, lexical_score) + recency_score * 0.1, 3)
            if score > 0 or observation.status != "active":
                results.append(
                    RetrievedObservation(
                        observation_id=observation.id,
                        content=observation.content,
                        score=score,
                        match_reasons=sorted(set(reasons)),
                        sensitivity=observation.sensitivity,
                        ai_use_policy=observation.ai_use_policy,
                        status=observation.status,
                        valid_from=observation.valid_from,
                        valid_to=observation.valid_to,
                        occurred_at=observation.occurred_at,
                        created_at=observation.created_at,
                        surface_eligible=observation.ai_use_policy != "never_surface",
                    )
                )
        results.sort(key=lambda item: -item.score)
        return results

    def _apply_penalties(
        self,
        entity: Entity,
        observations: list[Observation],
        score: float,
        penalties: dict[str, float],
    ) -> float:
        if entity.confirmation_status in {"deprecated", "rejected", "merged", "disputed"}:
            penalties["stale_status"] = 0.20
        if any(observation.status in {"deprecated", "superseded", "disputed"} for observation in observations):
            penalties["stale_status"] = max(penalties.get("stale_status", 0), 0.20)
        if entity.sensitivity == "high" or any(observation.sensitivity == "high" for observation in observations):
            penalties["sensitivity"] = 0.10
        if entity.ai_use_policy == "never_surface" or any(
            observation.ai_use_policy == "never_surface" for observation in observations
        ):
            penalties["policy_block"] = 0.30
        elif entity.ai_use_policy == "ask_before_use" or any(
            observation.ai_use_policy == "ask_before_use" for observation in observations
        ):
            penalties["surface_constraint"] = 0.10
        return round(max(0.0, score - sum(penalties.values())), 3)

    def _surface_bucket(self, entity: Entity, observations: list[Observation], score: float) -> str:
        policies = {entity.ai_use_policy, *(observation.ai_use_policy for observation in observations)}
        sensitivities = {entity.sensitivity, *(observation.sensitivity for observation in observations)}
        statuses = {entity.confirmation_status, *(observation.status for observation in observations)}
        if "never_surface" in policies:
            return "blocked"
        if statuses & {"deprecated", "superseded", "disputed", "rejected", "merged"}:
            return "internal_only"
        if "high" in sensitivities or "ask_before_use" in policies:
            return "conditional_surface"
        return "direct_surface"

    def _graph_neighbors(self, entity_ids: set[str], focal_entity_id: str | None) -> set[str]:
        if not focal_entity_id:
            return set()
        neighbors = set()
        for edge in self.repository.active_edges_for(entity_ids):
            if edge.from_entity_id == focal_entity_id:
                neighbors.add(edge.to_entity_id)
            if edge.to_entity_id == focal_entity_id:
                neighbors.add(edge.from_entity_id)
        return neighbors

    def _is_ambiguous(self, matches: list[RetrievalMatch], hints: set[str]) -> bool:
        if hints or len(matches) < 2:
            return False
        top = sorted(matches, key=lambda item: -item.score)[:2]
        if len(top) < 2:
            return False
        shared_name_match = {"exact_alias", "normalized_alias"} & set(top[0].match_reasons)
        return bool(shared_name_match) and (top[0].score - top[1].score) <= 0.05

    def _surface_buckets(self, matches: list[RetrievalMatch]) -> dict[str, list[RetrievalMatch]]:
        buckets: dict[str, list[RetrievalMatch]] = {
            "direct_surface": [],
            "conditional_surface": [],
            "internal_only": [],
            "blocked": [],
        }
        for match in matches:
            buckets[match.surface_bucket].append(match)
        return buckets

    def _aliases_by_entity(self, aliases: list[EntityAlias]) -> dict[str, list[EntityAlias]]:
        result: dict[str, list[EntityAlias]] = {}
        for alias in aliases:
            result.setdefault(alias.entity_id, []).append(alias)
        return result

    def _observations_by_entity(self, observations: list[Observation]) -> dict[str, list[Observation]]:
        result: dict[str, list[Observation]] = {}
        for observation in observations:
            result.setdefault(observation.subject_entity_id, []).append(observation)
        return result

    def _matches_name_or_alias(
        self,
        normalized_query: str,
        query_tokens: set[str],
        normalized_names: list[str],
    ) -> bool:
        return bool(self._name_reasons(normalized_query, query_tokens, normalized_names))

    def _name_reasons(
        self,
        normalized_query: str,
        query_tokens: set[str],
        normalized_names: list[str],
    ) -> list[str]:
        reasons = []
        for name in normalized_names:
            if not name:
                continue
            name_tokens = set(name.split())
            if normalized_query == name or name in query_tokens:
                reasons.append("exact_alias")
            if name in normalized_query or name_tokens & query_tokens:
                reasons.append("normalized_alias")
            if self._trigram_similarity(normalized_query, name) >= 0.20 or any(
                self._trigram_similarity(token, name) >= 0.20 for token in query_tokens
            ):
                reasons.append("pg_trgm_name_alias")
        return sorted(set(reasons))

    def _token_overlap(self, left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

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
        return {padded[index : index + 3] for index in range(max(0, len(padded) - 2))}

    def _parse_vector(self, raw: str | None) -> list[float]:
        if not raw:
            return []
        stripped = raw.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return []
        try:
            return [float(part.strip()) for part in stripped.split(",")]
        except ValueError:
            return []

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(left_value * right_value for left_value, right_value in zip(left, right))
        left_norm = sqrt(sum(value * value for value in left))
        right_norm = sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _recency_score(self, observation: Observation, now: datetime) -> float:
        if observation.recency_weight is not None:
            return float(observation.recency_weight)
        reference = observation.occurred_at or observation.created_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        age_days = max(0, (now - reference).days)
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.5
        return 0.0

    def _confidence_band(self, score: float) -> str:
        return self.confidence_band_for_score(score)

    def confidence_band_for_score(self, score: float) -> str:
        if score >= CONFIDENCE_HIGH_THRESHOLD:
            return "high"
        if score >= CONFIDENCE_MEDIUM_THRESHOLD:
            return "medium"
        return "low"
