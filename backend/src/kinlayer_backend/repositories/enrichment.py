from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.models import EnrichmentAnswerAction, EnrichmentAuthorization, Entity


class EnrichmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def authorization_by_stage_key(self, key: str):
        return self.session.scalar(
            select(EnrichmentAuthorization).where(
                EnrichmentAuthorization.stage_idempotency_key == key
            )
        )

    def action_by_resolution(self, resolution_id: str):
        return self.session.scalar(
            select(EnrichmentAnswerAction).where(
                EnrichmentAnswerAction.resolution_id == resolution_id
            )
        )

    def action_by_id(self, action_id: str):
        return self.session.get(EnrichmentAnswerAction, action_id)

    def lock_authorization(self, authorization_id: str):
        return self.session.scalar(
            select(EnrichmentAuthorization)
            .where(EnrichmentAuthorization.id == authorization_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_entities(self, ids: list[str]):
        return list(
            self.session.scalars(
                select(Entity)
                .where(Entity.id.in_(ids))
                .order_by(Entity.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
