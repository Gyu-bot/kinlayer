from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Entity, EntityEdge


class GraphRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.session.get(Entity, entity_id)

    def ego_edges(
        self,
        entity_id: str,
        relation_type: str | None = None,
        status: str | None = None,
        sensitivity: str | None = None,
    ) -> list[EntityEdge]:
        filters = [
            or_(EntityEdge.from_entity_id == entity_id, EntityEdge.to_entity_id == entity_id),
            EntityEdge.status == (status or "active"),
        ]
        if relation_type:
            filters.append(EntityEdge.relation_type == relation_type)
        if sensitivity:
            filters.append(EntityEdge.sensitivity == sensitivity)
        statement = select(EntityEdge).where(*filters).order_by(EntityEdge.created_at.desc())
        return self.session.execute(statement).scalars().all()

    def entities_by_id(self, entity_ids: set[str]) -> list[Entity]:
        if not entity_ids:
            return []
        statement = select(Entity).where(Entity.id.in_(entity_ids))
        return self.session.execute(statement).scalars().all()
