from collections.abc import Iterable

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Entity, EntityAlias, EntityFact
from kinlayer_backend.services.ontology import normalize_name


def _page(session: Session, statement: Select, limit: int, offset: int):
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.execute(statement.limit(limit).offset(offset)).scalars().unique().all()
    return items, total


class EntityRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_entity(self, payload: dict) -> Entity:
        entity = Entity(**payload)
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.session.get(Entity, entity_id)

    def find_self(self) -> Entity | None:
        statement = select(Entity).where(Entity.system_role == "self")
        return self.session.execute(statement).scalar_one_or_none()

    def list_entities(
        self,
        q: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        sensitivity: str | None = None,
        system_role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Entity], int]:
        id_statement = select(Entity.id).outerjoin(EntityAlias)
        filters = []
        if q:
            term = f"%{normalize_name(q)}%"
            filters.append(
                or_(
                    func.lower(Entity.display_name).like(term),
                    func.lower(Entity.canonical_name).like(term),
                    func.lower(EntityAlias.normalized_alias).like(term),
                )
            )
        if entity_type:
            filters.append(Entity.entity_type == entity_type)
        if status:
            filters.append(Entity.status == status)
        else:
            filters.append(Entity.status == "active")
        if sensitivity:
            filters.append(Entity.sensitivity == sensitivity)
        if system_role:
            filters.append(Entity.system_role == system_role)
        if filters:
            id_statement = id_statement.where(*filters)
        id_statement = id_statement.distinct()
        total = self.session.scalar(
            select(func.count()).select_from(id_statement.subquery())
        ) or 0
        paged_ids = (
            select(Entity.id, Entity.display_name)
            .outerjoin(EntityAlias)
            .where(*filters)
            .distinct()
            .order_by(Entity.display_name)
            .limit(limit)
            .offset(offset)
            .subquery()
        )
        statement = select(Entity).where(Entity.id.in_(select(paged_ids.c.id))).order_by(
            Entity.display_name
        )
        items = self.session.execute(statement).scalars().all()
        return items, total

    def add_alias(self, entity_id: str, payload: dict) -> EntityAlias:
        alias = EntityAlias(
            entity_id=entity_id,
            normalized_alias=normalize_name(payload["alias"]),
            **payload,
        )
        self.session.add(alias)
        self.session.commit()
        self.session.refresh(alias)
        return alias

    def get_alias(self, alias_id: str) -> EntityAlias | None:
        return self.session.get(EntityAlias, alias_id)

    def list_aliases(self, entity_id: str) -> tuple[list[EntityAlias], int]:
        statement = (
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity_id)
            .order_by(EntityAlias.created_at)
        )
        return _page(self.session, statement, 200, 0)

    def add_fact(self, payload: dict) -> EntityFact:
        fact = EntityFact(**payload)
        self.session.add(fact)
        self.session.commit()
        self.session.refresh(fact)
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
