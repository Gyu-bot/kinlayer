from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import Entity


def lock_active_entities(session: Session, entity_ids: Iterable[str]) -> dict[str, Entity]:
    ordered_ids = sorted(set(entity_ids))
    if not ordered_ids:
        return {}
    entities = list(
        session.scalars(
            select(Entity)
            .where(Entity.id.in_(ordered_ids))
            .order_by(Entity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    by_id = {entity.id: entity for entity in entities}
    if set(by_id) != set(ordered_ids):
        raise api_error(404, "not_found", "Entity not found.")
    if any(entity.status != "active" for entity in entities):
        raise api_error(409, "conflict", "Entity is not active.")
    return by_id
