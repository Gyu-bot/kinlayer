from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Candidate, Entity, ReconciliationAction


class ReconciliationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, action_id: str) -> ReconciliationAction | None:
        return self.session.get(ReconciliationAction, action_id)

    def get_by_resolution_id(self, resolution_id: str) -> ReconciliationAction | None:
        return self.session.scalar(
            select(ReconciliationAction).where(
                ReconciliationAction.resolution_id == resolution_id
            )
        )

    def lock_resolution(self, resolution_id: str) -> ReconciliationAction | None:
        return self.session.scalar(
            select(ReconciliationAction)
            .where(ReconciliationAction.resolution_id == resolution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_candidates(self, candidate_ids: list[str]) -> list[Candidate]:
        return list(
            self.session.scalars(
                select(Candidate)
                .where(Candidate.id.in_(candidate_ids))
                .order_by(Candidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )

    def lock_entities(self, entity_ids: list[str]) -> list[Entity]:
        return list(
            self.session.scalars(
                select(Entity)
                .where(Entity.id.in_(entity_ids))
                .order_by(Entity.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
