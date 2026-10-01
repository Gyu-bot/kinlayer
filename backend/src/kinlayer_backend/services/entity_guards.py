from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import Entity, MemoryChange


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


def require_memory_change_for_tracked_record(session: Session, record) -> None:
    """Compatibility CRUD must not overwrite an immutable memory revision."""
    # Serialize with /memories corrections before checking their committed receipt.
    # Hold this lock through the caller's mutation commit, including initially
    # untracked rows which a concurrent correction could otherwise supersede.
    model = type(record)
    session.execute(select(model).where(model.id == record.id).with_for_update()
                    .execution_options(populate_existing=True)).scalar_one()
    ref = f"{record.__tablename__}:{record.id}"
    if session.scalar(select(MemoryChange.id).where(or_(
        MemoryChange.old_record_ref == ref, MemoryChange.new_record_ref == ref,
    )).limit(1)) is not None:
        raise api_error(409, "memory_change_required",
                        "Use /api/memories to correct or retract this tracked memory.")
