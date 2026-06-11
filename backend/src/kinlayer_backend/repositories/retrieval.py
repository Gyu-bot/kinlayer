from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Entity, EntityAlias, EntityEdge, Observation


class RetrievalRepository:
    def __init__(self, session: Session):
        self.session = session

    def entities(self) -> list[Entity]:
        statement = select(Entity).where(Entity.status != "deleted").order_by(Entity.display_name)
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
        statement = select(EntityEdge).where(
            EntityEdge.status == "active",
            or_(
                EntityEdge.from_entity_id.in_(entity_ids),
                EntityEdge.to_entity_id.in_(entity_ids),
            ),
        )
        return self.session.execute(statement).scalars().all()
