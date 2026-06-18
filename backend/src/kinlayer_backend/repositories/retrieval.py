from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from kinlayer_backend.models import AllowedEdgeType, Entity, EntityAlias, EntityEdge, Observation


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
        statement = select(Observation).where(Observation.status != "deleted")
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
                EntityEdge.status == "active",
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
