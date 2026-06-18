from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import EntityEdge, Episode, Observation, ObservationEntity


def page(session: Session, statement: Select, limit: int, offset: int):
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.execute(statement.limit(limit).offset(offset)).scalars().unique().all()
    return items, total


class RelationshipRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_edge(self, payload: dict, commit: bool = True) -> EntityEdge:
        edge = EntityEdge(**payload)
        self.session.add(edge)
        if commit:
            self.session.commit()
            self.session.refresh(edge)
        else:
            self.session.flush()
        return edge

    def get_edge(self, edge_id: str) -> EntityEdge | None:
        return self.session.get(EntityEdge, edge_id)

    def list_edges(
        self,
        entity_id: str | None = None,
        from_entity_id: str | None = None,
        to_entity_id: str | None = None,
        relation_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        statement = select(EntityEdge)
        filters = []
        if entity_id:
            filters.append(
                or_(EntityEdge.from_entity_id == entity_id, EntityEdge.to_entity_id == entity_id)
            )
        if from_entity_id:
            filters.append(EntityEdge.from_entity_id == from_entity_id)
        if to_entity_id:
            filters.append(EntityEdge.to_entity_id == to_entity_id)
        if relation_type:
            filters.append(EntityEdge.relation_type == relation_type)
        filters.append(EntityEdge.status == (status or "active"))
        return page(self.session, statement.where(*filters).order_by(EntityEdge.created_at.desc()), limit, offset)

    def add_observation(
        self,
        payload: dict,
        related_entities: list[dict],
        commit: bool = True,
    ) -> Observation:
        observation = Observation(**payload)
        self.session.add(observation)
        self.session.flush()
        for related in related_entities:
            self.session.add(ObservationEntity(observation_id=observation.id, **related))
        if commit:
            self.session.commit()
            self.session.refresh(observation)
        else:
            self.session.flush()
        return observation

    def get_observation(self, observation_id: str) -> Observation | None:
        return self.session.get(Observation, observation_id)

    def list_observation_entities(self, observation_id: str) -> list[ObservationEntity]:
        statement = select(ObservationEntity).where(
            ObservationEntity.observation_id == observation_id
        )
        return self.session.execute(statement).scalars().all()

    def list_observations(
        self,
        subject_entity_id: str | None = None,
        related_entity_id: str | None = None,
        observation_type: str | None = None,
        status: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        statement = select(Observation)
        if related_entity_id:
            statement = statement.join(
                ObservationEntity, ObservationEntity.observation_id == Observation.id
            )
        filters = []
        if subject_entity_id:
            filters.append(Observation.subject_entity_id == subject_entity_id)
        if related_entity_id:
            filters.append(ObservationEntity.entity_id == related_entity_id)
        if observation_type:
            filters.append(Observation.observation_type == observation_type)
        if claim_type:
            filters.append(Observation.claim_type == claim_type)
        filters.append(Observation.status == (status or "active"))
        return page(self.session, statement.where(*filters).distinct().order_by(Observation.created_at.desc()), limit, offset)

    def add_episode(self, payload: dict, commit: bool = True) -> Episode:
        episode = Episode(**payload)
        self.session.add(episode)
        if commit:
            self.session.commit()
            self.session.refresh(episode)
        else:
            self.session.flush()
        return episode

    def get_episode(self, episode_id: str) -> Episode | None:
        return self.session.get(Episode, episode_id)

    def list_episodes(
        self,
        source_type: str | None = None,
        actor: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        statement = select(Episode)
        filters = []
        if source_type:
            filters.append(Episode.source_type == source_type)
        if actor:
            filters.append(Episode.actor == actor)
        if filters:
            statement = statement.where(*filters)
        return page(self.session, statement.order_by(Episode.created_at.desc()), limit, offset)

    def commit_refresh(self, row: object) -> None:
        self.session.commit()
        self.session.refresh(row)
