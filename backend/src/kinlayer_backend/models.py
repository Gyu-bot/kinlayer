from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

JSON_TYPE = JSON().with_variant(postgresql.JSONB, "postgresql")


class VectorType(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw) -> str:
        return "vector"


VECTOR_TYPE = VectorType().with_variant(Text, "sqlite")


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
    )


class OntologyRegistryValue(Base, TimestampMixin):
    __tablename__ = "ontology_registry_values"
    __table_args__ = (UniqueConstraint("category", "value", name="uq_registry_category_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    support_level: Mapped[str] = mapped_column(String(40), default="supported")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class AllowedEdgeType(Base, TimestampMixin):
    __tablename__ = "allowed_edge_types"
    __table_args__ = (UniqueConstraint("relation_type", name="uq_allowed_edge_types_relation_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    relation_type: Mapped[str] = mapped_column(String(120), nullable=False)
    from_entity_type: Mapped[str] = mapped_column(String(80), default="person")
    to_entity_type: Mapped[str] = mapped_column(String(80), default="person")
    directed_default: Mapped[bool] = mapped_column(Boolean, default=True)
    inverse_relation_type: Mapped[str | None] = mapped_column(String(120))
    allowed_properties_schema: Mapped[dict | None] = mapped_column(JSON_TYPE)
    description: Mapped[str | None] = mapped_column(Text)
    examples: Mapped[list | None] = mapped_column(JSON_TYPE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AllowedObservationType(Base, TimestampMixin):
    __tablename__ = "allowed_observation_types"
    __table_args__ = (
        UniqueConstraint("observation_type", name="uq_allowed_observation_types_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_type: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    examples: Mapped[list | None] = mapped_column(JSON_TYPE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Entity(Base, TimestampMixin):
    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_entity_type", "entity_type"),
        Index("ix_entities_canonical_name", "canonical_name"),
        Index("ix_entities_confirmation_status", "confirmation_status"),
        Index(
            "ux_entities_system_role_self",
            "system_role",
            unique=True,
            sqlite_where=text("system_role = 'self'"),
            postgresql_where=text("system_role = 'self'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(String(240))
    properties: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    confirmation_status: Mapped[str] = mapped_column(String(40), default="confirmed")
    status: Mapped[str] = mapped_column(String(40), default="active")
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    ai_use_policy: Mapped[str] = mapped_column(String(60), default="cautious_use")
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)
    system_role: Mapped[str | None] = mapped_column(String(60))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_referenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    aliases: Mapped[list[EntityAlias]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
    )
    facts: Mapped[list[EntityFact]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
    )


class EntityAlias(Base, TimestampMixin):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        Index("ix_entity_aliases_entity_id", "entity_id"),
        Index("ix_entity_aliases_normalized_alias", "normalized_alias"),
        Index(
            "ux_entity_aliases_source_candidate_id",
            "source_candidate_id",
            unique=True,
            sqlite_where=text("source_candidate_id is not null"),
            postgresql_where=text("source_candidate_id is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), default="active")
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    source_candidate_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)

    entity: Mapped[Entity] = relationship(back_populates="aliases")


class EntityFact(Base, TimestampMixin):
    __tablename__ = "entity_facts"
    __table_args__ = (
        Index("ix_entity_facts_entity_id", "entity_id"),
        Index("ix_entity_facts_fact_type", "fact_type"),
        Index("ix_entity_facts_status", "status"),
        Index(
            "ux_entity_facts_source_candidate_id",
            "source_candidate_id",
            unique=True,
            sqlite_where=text("source_candidate_id is not null"),
            postgresql_where=text("source_candidate_id is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict | None] = mapped_column(JSON_TYPE)
    claim_type: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    ai_use_policy: Mapped[str] = mapped_column(String(60), default="cautious_use")
    status: Mapped[str] = mapped_column(String(40), default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_candidate_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)

    entity: Mapped[Entity] = relationship(back_populates="facts")


class MaterialImport(Base, TimestampMixin):
    __tablename__ = "material_imports"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(71), unique=True, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    candidate_links: Mapped[dict] = mapped_column(JSON_TYPE, default=dict, nullable=False)


class Episode(Base, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (
        Index("ix_episodes_source_type", "source_type"),
        Index("ix_episodes_actor", "actor"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(500))
    source_description: Mapped[str | None] = mapped_column(Text)
    material_import_id: Mapped[str | None] = mapped_column(ForeignKey("material_imports.id"))
    body_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    retention_policy: Mapped[str] = mapped_column(String(60), default="excerpt_only")


class EntityEdge(Base, TimestampMixin):
    __tablename__ = "entity_edges"
    __table_args__ = (
        Index("ix_entity_edges_from_entity_id", "from_entity_id"),
        Index("ix_entity_edges_to_entity_id", "to_entity_id"),
        Index("ix_entity_edges_relation_type", "relation_type"),
        Index("ix_entity_edges_status", "status"),
        Index(
            "ux_entity_edges_source_candidate_id",
            "source_candidate_id",
            unique=True,
            sqlite_where=text("source_candidate_id is not null"),
            postgresql_where=text("source_candidate_id is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    from_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    to_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(120), nullable=False)
    directed: Mapped[bool] = mapped_column(Boolean, default=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(60), nullable=False)
    properties: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    ai_use_policy: Mapped[str] = mapped_column(String(60), default="cautious_use")
    status: Mapped[str] = mapped_column(String(40), default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_by_edge_id: Mapped[str | None] = mapped_column(ForeignKey("entity_edges.id"))
    source_candidate_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Observation(Base, TimestampMixin):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_subject_entity_id", "subject_entity_id"),
        Index("ix_observations_observation_type", "observation_type"),
        Index("ix_observations_status", "status"),
        Index("ix_observations_claim_type", "claim_type"),
        Index(
            "ux_observations_source_candidate_id",
            "source_candidate_id",
            unique=True,
            sqlite_where=text("source_candidate_id is not null"),
            postgresql_where=text("source_candidate_id is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    ai_use_policy: Mapped[str] = mapped_column(String(60), default="cautious_use")
    status: Mapped[str] = mapped_column(String(40), default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recency_weight: Mapped[float | None] = mapped_column(Numeric(4, 3))
    embedding: Mapped[str | None] = mapped_column(VECTOR_TYPE)
    embedding_status: Mapped[str] = mapped_column(String(40), default="pending")
    embedding_error: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(240))
    embedding_dim: Mapped[int | None] = mapped_column()
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_candidate_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)


class ObservationEntity(Base):
    __tablename__ = "observation_entities"
    __table_args__ = (
        Index("ix_observation_entities_observation_id", "observation_id"),
        Index("ix_observation_entities_entity_id", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EntityFactEvidence(Base):
    __tablename__ = "entity_fact_evidence"
    __table_args__ = (
        Index("ix_entity_fact_evidence_fact_id", "entity_fact_id"),
        Index("ix_entity_fact_evidence_episode_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_fact_id: Mapped[str] = mapped_column(ForeignKey("entity_facts.id"), nullable=False)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EdgeEvidence(Base):
    __tablename__ = "edge_evidence"
    __table_args__ = (
        Index("ix_edge_evidence_edge_id", "edge_id"),
        Index("ix_edge_evidence_episode_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    edge_id: Mapped[str] = mapped_column(ForeignKey("entity_edges.id"), nullable=False)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ObservationEvidence(Base):
    __tablename__ = "observation_evidence"
    __table_args__ = (
        Index("ix_observation_evidence_observation_id", "observation_id"),
        Index("ix_observation_evidence_episode_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), nullable=False)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_candidate_type", "candidate_type"),
        Index("ix_candidates_status", "status"),
        Index("ix_candidates_target_entity_id", "target_entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    payload: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # Retired metadata: retained for historical storage and immutable digests only.
    sensitivity: Mapped[str] = mapped_column(String(40), default="medium")
    suggested_action: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    created_by: Mapped[str] = mapped_column(String(60), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(60))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    canonical_record_ref: Mapped[str | None] = mapped_column(String(120))
    supersedes_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id"))
    supersedes_record_ref: Mapped[str | None] = mapped_column(String(120))

    evidence: Mapped[list["CandidateEvidence"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )


class CandidateEvidence(Base):
    __tablename__ = "candidate_evidence"
    __table_args__ = (
        Index("ix_candidate_evidence_candidate_id", "candidate_id"),
        Index("ix_candidate_evidence_episode_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    candidate: Mapped[Candidate] = relationship(back_populates="evidence")
    episode: Mapped[Episode] = relationship()

    @property
    def source_type(self) -> str | None:
        return self.episode.source_type if self.episode else None

    @property
    def source_ref(self) -> str | None:
        return self.episode.source_ref if self.episode else None

    @property
    def source_description(self) -> str | None:
        return self.episode.source_description if self.episode else None

    @property
    def body_hash(self) -> str | None:
        return self.episode.body_hash if self.episode else None

    @property
    def actor(self) -> str | None:
        return self.episode.actor if self.episode else None

    @property
    def material_import_id(self) -> str | None:
        return self.episode.material_import_id if self.episode else None


class ReconciliationAction(Base, TimestampMixin):
    __tablename__ = "reconciliation_actions"
    __table_args__ = (
        UniqueConstraint("resolution_id", name="uq_reconciliation_actions_resolution_id"),
        CheckConstraint(
            "status in ('pending', 'committed_unverified', 'verified', 'verification_failed')",
            name="ck_reconciliation_actions_status",
        ),
        Index("ix_reconciliation_actions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resolution_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    candidate_ids: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    expected_candidates: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    expected_entities: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    source_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    target_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    primary_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    derived_candidate_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    confirmation_episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    outcome_canonical_refs: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    readback_summary: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(80))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrichmentAuthorization(Base, TimestampMixin):
    __tablename__ = "enrichment_authorizations"
    __table_args__ = (
        UniqueConstraint("authorization_ref", name="uq_enrichment_authorizations_ref"),
        UniqueConstraint("stage_idempotency_key", name="uq_enrichment_authorizations_stage_key"),
        CheckConstraint(
            "status in ('open', 'partially_answered', 'completed', 'expired', 'cancelled')",
            name="ck_enrichment_authorizations_status",
        ),
        Index("ix_enrichment_authorizations_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    authorization_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    stage_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    stage_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    entity_snapshots: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    slots: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    slot_states: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrichmentAnswerAction(Base, TimestampMixin):
    __tablename__ = "enrichment_answer_actions"
    __table_args__ = (
        UniqueConstraint("resolution_id", name="uq_enrichment_answer_actions_resolution_id"),
        CheckConstraint(
            "status in ('pending', 'committed_unverified', 'verified', 'verification_failed')",
            name="ck_enrichment_answer_actions_status",
        ),
        Index("ix_enrichment_answer_actions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resolution_id: Mapped[str] = mapped_column(String(120), nullable=False)
    authorization_id: Mapped[str] = mapped_column(
        ForeignKey("enrichment_authorizations.id"), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    slot_outcomes: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    derived_candidate_ids: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    canonical_refs: Mapped[list] = mapped_column(JSON_TYPE, nullable=False)
    source_snapshot: Mapped[dict | None] = mapped_column(JSON_TYPE)
    readback_summary: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(80))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurationRun(Base, TimestampMixin):
    __tablename__ = "curation_runs"
    __table_args__ = (
        CheckConstraint(
            "mode in ('disabled', 'shadow', 'apply')",
            name="ck_curation_runs_mode",
        ),
        CheckConstraint(
            "status in ('pending', 'planning', 'ready', 'executing', "
            "'completed', 'partial', 'failed')",
            name="ck_curation_runs_status",
        ),
        CheckConstraint(
            "(cursor_started_at is null) = (cursor_started_id is null)",
            name="ck_curation_runs_started_cursor_pair",
        ),
        CheckConstraint(
            "(cursor_completed_at is null) = (cursor_completed_id is null)",
            name="ck_curation_runs_completed_cursor_pair",
        ),
        CheckConstraint(
            "cursor_completed_at is null or cursor_started_at is not null",
            name="ck_curation_runs_completed_cursor_requires_started",
        ),
        CheckConstraint(
            "cursor_completed_at is null or cursor_completed_at > cursor_started_at or "
            "(cursor_completed_at = cursor_started_at and cursor_completed_id >= cursor_started_id)",
            name="ck_curation_runs_cursor_order",
        ),
        CheckConstraint(
            "input_candidate_count >= 0 and planned_decision_count >= 0 and "
            "executed_decision_count >= 0 and blocked_decision_count >= 0",
            name="ck_curation_runs_nonnegative_counts",
        ),
        Index("ix_curation_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    cursor_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_started_id: Mapped[str | None] = mapped_column(String(36))
    cursor_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_completed_id: Mapped[str | None] = mapped_column(String(36))
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    planner_name: Mapped[str | None] = mapped_column(String(160))
    planner_model: Mapped[str | None] = mapped_column(String(240))
    planner_version: Mapped[str | None] = mapped_column(String(120))
    input_candidate_count: Mapped[int] = mapped_column(default=0)
    planned_decision_count: Mapped[int] = mapped_column(default=0)
    executed_decision_count: Mapped[int] = mapped_column(default=0)
    blocked_decision_count: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    diagnostics: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    decisions: Mapped[list["CurationDecision"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class CurationDecision(Base, TimestampMixin):
    __tablename__ = "curation_decisions"
    __table_args__ = (
        CheckConstraint(
            "action in ('accept_existing', 'edit_accept_existing', 'consolidate_accept', "
            "'archive_exact_duplicate', 'mark_needs_clarification', 'defer', "
            "'recommend_merge_review', 'recommend_conflict_review')",
            name="ck_curation_decisions_action",
        ),
        CheckConstraint(
            "status in ('proposed', 'allowed', 'blocked', 'executing', 'executed', 'failed')",
            name="ck_curation_decisions_status",
        ),
        CheckConstraint(
            "risk_level in ('low', 'medium', 'high')",
            name="ck_curation_decisions_risk_level",
        ),
        UniqueConstraint("idempotency_key", name="uq_curation_decisions_idempotency_key"),
        Index("ix_curation_decisions_run_id", "run_id"),
        Index("ix_curation_decisions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("curation_runs.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="proposed")
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    expected_candidates: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    target_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    proposed_payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    evidence_episode_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    reason_codes: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    canonical_record_ref: Mapped[str | None] = mapped_column(String(120))
    readback_status: Mapped[str | None] = mapped_column(String(60))
    readback_summary: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    api_error_code: Mapped[str | None] = mapped_column(String(80))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[CurationRun] = relationship(back_populates="decisions")


class EntityMerge(Base, TimestampMixin):
    __tablename__ = "entity_merges"
    __table_args__ = (
        Index("ix_entity_merges_source_entity_id", "source_entity_id"),
        Index("ix_entity_merges_target_entity_id", "target_entity_id"),
        Index("ix_entity_merges_candidate_id", "candidate_id"),
        Index(
            "ux_entity_merges_candidate_id",
            "candidate_id",
            unique=True,
            sqlite_where=text("candidate_id is not null"),
            postgresql_where=text("candidate_id is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id"))
    merge_plan: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    conflict_decisions: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_record_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_refs: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class AgentWriteOperationAudit(Base, TimestampMixin):
    __tablename__ = "agent_write_operation_audits"
    __table_args__ = (
        Index("ix_agent_write_operation_actor", "actor"),
        Index("ix_agent_write_operation_operation_type", "operation_type"),
        Index("ix_agent_write_operation_result_status", "result_status"),
        Index("ix_agent_write_operation_candidate_id", "candidate_id"),
        Index("ix_agent_write_operation_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_path: Mapped[str] = mapped_column(String(240), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    result_status: Mapped[str] = mapped_column(String(40), nullable=False)
    api_error_code: Mapped[str | None] = mapped_column(String(80))
    request_summary: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    diagnostics: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    related_refs: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    candidate_id: Mapped[str | None] = mapped_column(String(36))
    correction_id: Mapped[str | None] = mapped_column(String(36))
    episode_id: Mapped[str | None] = mapped_column(String(36))
    canonical_record_ref: Mapped[str | None] = mapped_column(String(120))
    bounded_excerpt: Mapped[str | None] = mapped_column(Text)

    @property
    def audit_id(self) -> str:
        return self.id
