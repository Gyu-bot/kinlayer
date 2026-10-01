"""Paginated directory summaries, with aggregation over the complete matching set."""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, literal, or_, select, union

from kinlayer_backend.models import EntityAlias, EntityEdge, EntityFact, Observation, ObservationEntity
from kinlayer_backend.repositories.entities import EntityRepository
from kinlayer_backend.schemas.entities import EntityRead
from kinlayer_backend.services.memory_reads import current_condition


class PeopleReadService:
    def __init__(self, session):
        self.session = session
        self.repository = EntityRepository(session)

    def list(self, *, q=None, relation_type=None, sort="name", exclude_self=True,
             limit=50, offset=0):
        people, total = self.repository.list_entities(
            q=q, entity_type="person", status="active", relation_type=relation_type,
            sort=sort, exclude_self=exclude_self, limit=limit, offset=offset,
        )
        ids = [person.id for person in people]
        if not ids:
            return {"items": [], "total": total, "limit": limit, "offset": offset}
        now = datetime.now(UTC)
        aliases, facts, relations = defaultdict(list), defaultdict(list), defaultdict(list)
        for alias in self.session.scalars(select(EntityAlias).where(
            EntityAlias.entity_id.in_(ids), EntityAlias.status == "active",
        ).order_by(EntityAlias.alias, EntityAlias.id)):
            aliases[alias.entity_id].append(alias.alias)
        for fact in self.session.scalars(select(EntityFact).where(
            EntityFact.entity_id.in_(ids), current_condition(EntityFact, now),
        ).order_by(EntityFact.fact_type, EntityFact.created_at.desc(), EntityFact.id)):
            facts[fact.entity_id].append(fact)
        self_entity = self.repository.find_self()
        if self_entity is not None:
            for edge in self.session.scalars(select(EntityEdge).where(
                current_condition(EntityEdge, now), or_(
                    (EntityEdge.from_entity_id == self_entity.id) & EntityEdge.to_entity_id.in_(ids),
                    (EntityEdge.to_entity_id == self_entity.id) & EntityEdge.from_entity_id.in_(ids),
                ),
            ).order_by(EntityEdge.relation_type, EntityEdge.id)):
                other = edge.to_entity_id if edge.from_entity_id == self_entity.id else edge.from_entity_id
                relations[other].append({
                    "relation_type": edge.relation_type, "directed": edge.directed,
                    "from_entity_id": edge.from_entity_id, "to_entity_id": edge.to_entity_id,
                })
        # UNION (not UNION ALL) counts a claim once per person, even when a person has
        # multiple observation roles or is both the subject and a related participant.
        memberships = union(
            select(EntityFact.entity_id.label("entity_id"),
                   (literal("entity_facts:") + EntityFact.id).label("record_ref")).where(
                EntityFact.entity_id.in_(ids), current_condition(EntityFact, now)),
            select(EntityEdge.from_entity_id.label("entity_id"),
                   (literal("entity_edges:") + EntityEdge.id).label("record_ref")).where(
                EntityEdge.from_entity_id.in_(ids), current_condition(EntityEdge, now)),
            select(EntityEdge.to_entity_id.label("entity_id"),
                   (literal("entity_edges:") + EntityEdge.id).label("record_ref")).where(
                EntityEdge.to_entity_id.in_(ids), current_condition(EntityEdge, now)),
            select(Observation.subject_entity_id.label("entity_id"),
                   (literal("observations:") + Observation.id).label("record_ref")).where(
                Observation.subject_entity_id.in_(ids), current_condition(Observation, now)),
            select(ObservationEntity.entity_id.label("entity_id"),
                   (literal("observations:") + Observation.id).label("record_ref")).join(
                Observation, Observation.id == ObservationEntity.observation_id).where(
                ObservationEntity.entity_id.in_(ids), current_condition(Observation, now)),
        ).subquery()
        counts = dict(self.session.execute(select(
            memberships.c.entity_id, func.count(),
        ).group_by(memberships.c.entity_id)).all())
        items = []
        for person in people:
            item = EntityRead.model_validate(person).model_dump()
            item.update(aliases=aliases[person.id], profile_facts=facts[person.id],
                        relations=relations[person.id], memory_count=counts.get(person.id, 0))
            items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}
