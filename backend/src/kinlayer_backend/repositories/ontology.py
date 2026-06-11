from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.models import AllowedEdgeType, AllowedObservationType, OntologyRegistryValue


class OntologyRepository:
    def __init__(self, session: Session):
        self.session = session

    def registry_values(self, category: str | None = None) -> list[OntologyRegistryValue]:
        statement = select(OntologyRegistryValue).where(OntologyRegistryValue.is_active.is_(True))
        if category:
            statement = statement.where(OntologyRegistryValue.category == category)
        return self.session.execute(
            statement.order_by(OntologyRegistryValue.category, OntologyRegistryValue.sort_order)
        ).scalars().all()

    def edge_types(self) -> list[AllowedEdgeType]:
        statement = select(AllowedEdgeType).where(AllowedEdgeType.active.is_(True))
        return self.session.execute(statement.order_by(AllowedEdgeType.relation_type)).scalars().all()

    def observation_types(self) -> list[AllowedObservationType]:
        statement = select(AllowedObservationType).where(AllowedObservationType.active.is_(True))
        return self.session.execute(
            statement.order_by(AllowedObservationType.observation_type)
        ).scalars().all()
