from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Entity, EntityAlias, EntityEdge, EntityFact, Observation
from kinlayer_backend.services.memory_reads import current_condition, literal_search
from kinlayer_backend.services.ontology import normalize_name


def _page(session: Session, statement: Select, limit: int, offset: int):
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.execute(statement.limit(limit).offset(offset)).scalars().unique().all()
    return items, total


class EntityRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_entity(self, payload: dict, commit: bool = True) -> Entity:
        entity = Entity(**payload)
        self.session.add(entity)
        if commit:
            self.session.commit()
            self.session.refresh(entity)
        else:
            self.session.flush()
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.session.get(Entity, entity_id)

    def find_self(self) -> Entity | None:
        statement = select(Entity).where(Entity.system_role == "self")
        return self.session.execute(statement).scalar_one_or_none()

    def resolvable_entities(
        self,
        entity_type: str | None = None,
    ) -> list[Entity]:
        statement = select(Entity).where(Entity.status == "active")
        if entity_type:
            statement = statement.where(Entity.entity_type == entity_type)
        return self.session.execute(statement.order_by(Entity.display_name)).scalars().all()

    def list_entities(
        self,
        q: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        system_role: str | None = None,
        limit: int = 50,
        offset: int = 0,
        relation_type: str | None = None,
        sort: str = "name",
        exclude_self: bool = False,
        profile_filters: dict[str, str] | None = None,
    ) -> tuple[list[Entity], int]:
        filters = []
        if q:
            term = literal_search(normalize_name(q))
            filters.append(
                or_(
                    func.lower(Entity.display_name).like(term, escape="\\"),
                    func.lower(Entity.canonical_name).like(term, escape="\\"),
                    select(EntityAlias.id).where(
                        EntityAlias.entity_id == Entity.id,
                        EntityAlias.status == "active",
                        func.lower(EntityAlias.normalized_alias).like(term, escape="\\"),
                    ).exists(),
                )
            )
        if entity_type:
            filters.append(Entity.entity_type == entity_type)
        if status:
            filters.append(Entity.status == status)
        else:
            filters.append(Entity.status == "active")
        if system_role:
            filters.append(Entity.system_role == system_role)
        if exclude_self:
            filters.append(or_(Entity.system_role.is_(None), Entity.system_role != "self"))
        if relation_type:
            self_id = select(Entity.id).where(Entity.system_role == "self").scalar_subquery()
            filters.append(select(EntityEdge.id).where(
                EntityEdge.relation_type == relation_type,
                current_condition(EntityEdge, datetime.now(UTC)),
                or_(
                    (EntityEdge.from_entity_id == self_id) & (EntityEdge.to_entity_id == Entity.id),
                    (EntityEdge.to_entity_id == self_id) & (EntityEdge.from_entity_id == Entity.id),
                ),
            ).correlate(Entity).exists())
        if profile_filters:
            # Correlated EXISTS filters apply to the full directory before count/paging.
            from kinlayer_backend.models import Entity as SelfEntity
            from sqlalchemy.orm import aliased
            perspective = aliased(SelfEntity)
            self_id = select(perspective.id).where(perspective.system_role == "self", perspective.status == "active").scalar_subquery()
            for axis, value in profile_filters.items():
                if value is None:
                    continue
                match = select(Observation.id).where(
                    Observation.subject_entity_id == Entity.id,
                    Observation.perspective_entity_id == self_id,
                    Observation.observation_type == "relationship_assessment",
                    Observation.relationship_axis == axis,
                    current_condition(Observation, datetime.now(UTC)),
                    Observation.valid_to.is_(None),
                    or_(Observation.occurred_at.is_(None), Observation.occurred_at <= datetime.now(UTC)),
                )
                if value != "unset":
                    match = match.where(Observation.relationship_value == value)
                predicate = match.correlate(Entity).exists()
                filters.append(~predicate if value == "unset" else predicate)
        statement = select(Entity).where(*filters)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        ordering = [Entity.display_name, Entity.id]
        if sort == "recent_reference":
            ordering = [Entity.last_referenced_at.desc().nulls_last(), *ordering]
        items = self.session.scalars(
            statement.order_by(*ordering).limit(limit).offset(offset)
        ).all()
        return items, total

    def add_alias(self, entity_id: str, payload: dict, commit: bool = True) -> EntityAlias:
        alias = EntityAlias(
            entity_id=entity_id,
            normalized_alias=normalize_name(payload["alias"]),
            **payload,
        )
        self.session.add(alias)
        if commit:
            self.session.commit()
            self.session.refresh(alias)
        else:
            self.session.flush()
        return alias

    def get_alias(self, alias_id: str) -> EntityAlias | None:
        return self.session.get(EntityAlias, alias_id)

    def list_aliases(self, entity_id: str) -> tuple[list[EntityAlias], int]:
        statement = (
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity_id, EntityAlias.status == "active")
            .order_by(EntityAlias.created_at)
        )
        return _page(self.session, statement, 200, 0)

    def add_fact(self, payload: dict, commit: bool = True) -> EntityFact:
        fact = EntityFact(**payload)
        self.session.add(fact)
        if commit:
            self.session.commit()
            self.session.refresh(fact)
        else:
            self.session.flush()
        return fact

    def get_fact(self, fact_id: str) -> EntityFact | None:
        return self.session.get(EntityFact, fact_id)

    def list_facts(
        self,
        entity_id: str | None = None,
        fact_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EntityFact], int]:
        statement = select(EntityFact)
        filters = []
        if entity_id:
            filters.append(EntityFact.entity_id == entity_id)
        if fact_type:
            filters.append(EntityFact.fact_type == fact_type)
        if status:
            filters.append(EntityFact.status == status)
        if filters:
            statement = statement.where(*filters)
        statement = statement.order_by(EntityFact.created_at.desc())
        return _page(self.session, statement, limit, offset)

    def commit_refresh(self, rows: Iterable[object]) -> None:
        self.session.commit()
        for row in rows:
            self.session.refresh(row)
