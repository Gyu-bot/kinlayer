from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from kinlayer_backend.models import (
    AllowedEdgeType, Entity, EntityAlias, EntityEdge, Observation, ObservationEntity,
)
from kinlayer_backend.services.memory_reads import current_condition


class RetrievalRepository:
    def __init__(self, session: Session):
        self.session = session

    def entities(self) -> list[Entity]:
        statement = select(Entity).where(Entity.status == "active").order_by(Entity.display_name)
        return self.session.execute(statement).scalars().all()

    def aliases(self) -> list[EntityAlias]:
        statement = select(EntityAlias).where(EntityAlias.status == "active")
        return self.session.execute(statement).scalars().all()

    def observations(self) -> list[Observation]:
        statement = select(Observation).where(current_condition(Observation, datetime.now(UTC)))
        return self.session.execute(statement).scalars().all()

    def observation_entities(self, observation_ids: set[str]) -> list[ObservationEntity]:
        if not observation_ids:
            return []
        statement = select(ObservationEntity).where(
            ObservationEntity.observation_id.in_(observation_ids)
        ).order_by(ObservationEntity.created_at, ObservationEntity.id)
        return self.session.execute(statement).scalars().all()

    def active_edges_for(self, entity_ids: set[str]) -> list[EntityEdge]:
        if not entity_ids:
            return []
        from_entity = aliased(Entity)
        to_entity = aliased(Entity)
        statement = (
            select(EntityEdge)
            .join(AllowedEdgeType, AllowedEdgeType.relation_type == EntityEdge.relation_type)
            .join(from_entity, from_entity.id == EntityEdge.from_entity_id)
            .join(to_entity, to_entity.id == EntityEdge.to_entity_id)
            .where(
                current_condition(EntityEdge, datetime.now(UTC)),
                from_entity.status == "active",
                to_entity.status == "active",
                AllowedEdgeType.active.is_(True),
                from_entity.entity_type == AllowedEdgeType.from_entity_type,
                to_entity.entity_type == AllowedEdgeType.to_entity_type,
                or_(
                    EntityEdge.from_entity_id.in_(entity_ids),
                    EntityEdge.to_entity_id.in_(entity_ids),
                ),
            )
        )
        return self.session.execute(statement).scalars().all()
