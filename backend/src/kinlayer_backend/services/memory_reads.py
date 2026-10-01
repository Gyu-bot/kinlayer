"""Read projections for current and historical memories; no writes or inference."""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import and_, func, literal, not_, or_, select, union_all

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    EdgeEvidence,
    Entity,
    EntityFactEvidence,
    Episode,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.services.memories import RECORD_MODELS, utc


EVIDENCE_MODELS = {
    "entity_facts": (EntityFactEvidence, EntityFactEvidence.entity_fact_id),
    "entity_edges": (EdgeEvidence, EdgeEvidence.edge_id),
    "observations": (ObservationEvidence, ObservationEvidence.observation_id),
}


def current_condition(model, now):
    """Current means an active/disputed revision whose validity interval contains now."""
    return and_(
        model.status.in_(("active", "disputed")),
        or_(model.valid_from.is_(None), model.valid_from <= now),
        or_(model.valid_to.is_(None), model.valid_to > now),
    )


def literal_search(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def canonical_entity_scope(session, entity_id):
    """Resolve a merged ID and include former IDs when inspecting retained history."""
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise api_error(404, "not_found", "Entity not found.")
    visited = set()
    while entity.status == "merged":
        if entity.id in visited or len(visited) >= 32:
            raise api_error(409, "conflict", "Invalid merged entity lineage.")
        visited.add(entity.id)
        reference = (entity.properties or {}).get("merged_entity_ref", "")
        if not reference.startswith("entities:"):
            break
        replacement = session.get(Entity, reference.split(":", 1)[1])
        if replacement is None:
            break
        entity = replacement
    lineage = select(Entity.id).where(Entity.id == entity.id).cte(recursive=True)
    lineage = lineage.union(
        select(Entity.id).join(
            lineage,
            Entity.properties["merged_entity_ref"].as_string() == literal("entities:") + lineage.c.id,
        ).where(Entity.status == "merged")
    )
    return select(lineage.c.id)


def entity_condition(record_type, model, entity_ids):
    if record_type == "entity_facts":
        return model.entity_id.in_(entity_ids)
    if record_type == "entity_edges":
        return or_(model.from_entity_id.in_(entity_ids), model.to_entity_id.in_(entity_ids))
    return or_(
        model.subject_entity_id.in_(entity_ids),
        select(ObservationEntity.id).where(
            ObservationEntity.observation_id == model.id,
            ObservationEntity.entity_id.in_(entity_ids),
        ).exists(),
    )


def memory_index(*, now, entity_ids=None, record_type=None, claim_basis=None,
                 status="active", q=None, source_episode_id=None):
    """Filter and page one SQL union before hydrating any content, links or evidence."""
    selections = []
    for kind, model in RECORD_MODELS.items():
        if record_type is not None and kind != record_type:
            continue
        content = model.claim_text if kind == "entity_edges" else model.content
        statement = select(
            literal(kind).label("record_type"), model.id.label("id"),
            (literal(kind + ":") + model.id).label("record_ref"),
            model.created_at.label("created_at"),
        )
        if entity_ids is not None:
            statement = statement.where(entity_condition(kind, model, entity_ids))
        if claim_basis:
            statement = statement.where(model.claim_basis == claim_basis)
        if status != "all":
            current = current_condition(model, now)
            statement = statement.where(current if status == "active" else not_(current))
        if q and q.strip():
            statement = statement.where(content.ilike(literal_search(q.strip()), escape="\\"))
        if source_episode_id:
            evidence, record_id = EVIDENCE_MODELS[kind]
            statement = statement.where(select(evidence.id).where(
                record_id == model.id, evidence.episode_id == source_episode_id,
            ).exists())
        selections.append(statement)
    return union_all(*selections).subquery()


class MemoryReadService:
    def __init__(self, session):
        self.session = session

    def list(self, *, entity_id=None, record_type=None, claim_basis=None, status="active",
             q=None, source_episode_id=None, limit=50, offset=0):
        now = datetime.now(UTC)
        scope = canonical_entity_scope(self.session, entity_id) if entity_id else None
        index = memory_index(now=now, entity_ids=scope, record_type=record_type,
                             claim_basis=claim_basis, status=status, q=q,
                             source_episode_id=source_episode_id)
        total = self.session.scalar(select(func.count()).select_from(index))
        page = self.session.execute(select(index).order_by(
            index.c.created_at.desc(), index.c.record_type, index.c.id,
        ).limit(limit).offset(offset)).all()
        return {"items": self._hydrate(page, now), "total": total,
                "limit": limit, "offset": offset}

    def get(self, record_type, record_id):
        model = RECORD_MODELS[record_type]
        row = self.session.get(model, record_id)
        if row is None:
            raise api_error(404, "not_found", "Memory record not found.")
        # The projection deliberately includes evidence belonging to historical revisions.
        return self._hydrate([(record_type, record_id)], datetime.now(UTC))[0]

    def _hydrate(self, page, now):
        ids = defaultdict(list)
        for item in page:
            ids[item[0]].append(item[1])
        rows, evidence_by_ref, links = {}, defaultdict(list), defaultdict(list)
        entity_ids = set()
        if ids["observations"]:
            for link in self.session.scalars(select(ObservationEntity).where(
                ObservationEntity.observation_id.in_(ids["observations"]),
            ).order_by(ObservationEntity.entity_id, ObservationEntity.role, ObservationEntity.id)):
                links[link.observation_id].append(link)
                entity_ids.add(link.entity_id)
        for kind, record_ids in ids.items():
            if not record_ids:
                continue
            model = RECORD_MODELS[kind]
            for row in self.session.scalars(select(model).where(model.id.in_(record_ids))):
                rows[(kind, row.id)] = row
                if kind == "entity_facts":
                    entity_ids.add(row.entity_id)
                elif kind == "entity_edges":
                    entity_ids.update((row.from_entity_id, row.to_entity_id))
                else:
                    entity_ids.add(row.subject_entity_id)
            evidence, record_id = EVIDENCE_MODELS[kind]
            for link, episode in self.session.execute(select(evidence, Episode).outerjoin(
                Episode, Episode.id == evidence.episode_id,
            ).where(record_id.in_(record_ids)).order_by(evidence.created_at, evidence.id)):
                record_key = getattr(link, record_id.key)
                evidence_by_ref[(kind, record_key)].append({
                    "episode_id": link.episode_id,
                    "source_type": episode.source_type if episode else None,
                    "source_ref": episode.source_ref if episode else None,
                    "actor": episode.actor if episode else None,
                    "excerpt": link.excerpt if link.excerpt is not None
                    else episode.body_excerpt if episode else None,
                    "occurred_at": utc(episode.occurred_at)
                    if episode and episode.occurred_at else None,
                    "missing": episode is None,
                })
        names = dict(self.session.execute(select(Entity.id, Entity.display_name).where(
            Entity.id.in_(entity_ids),
        )).all()) if entity_ids else {}
        result = []
        for item in page:
            kind, record_id = item[0], item[1]
            row = rows[(kind, record_id)]
            payload = {"claim_basis": row.claim_basis, "confidence": float(row.confidence),
                       "valid_from": utc(row.valid_from) if row.valid_from else None,
                       "valid_to": utc(row.valid_to) if row.valid_to else None}
            if kind == "entity_facts":
                payload.update(entity_id=row.entity_id, fact_type=row.fact_type,
                               content=row.content, value=row.value)
                participants = [(row.entity_id, "about")]
            elif kind == "entity_edges":
                payload.update(from_entity_id=row.from_entity_id, to_entity_id=row.to_entity_id,
                               relation_type=row.relation_type, directed=row.directed,
                               claim_text=row.claim_text, properties=row.properties)
                participants = [(row.from_entity_id, "from"), (row.to_entity_id, "to")]
            else:
                payload.update(subject_entity_id=row.subject_entity_id,
                               observation_type=row.observation_type, content=row.content,
                               occurred_at=utc(row.occurred_at) if row.occurred_at else None,
                               related_entities=[{
                                   "entity_id": link.entity_id, "role": link.role,
                                   "confidence": float(link.confidence)
                                   if link.confidence is not None else None,
                               } for link in links[row.id]])
                participants = [(row.subject_entity_id, "subject")]
                participants += [(link.entity_id, link.role) for link in links[row.id]]
            result.append({
                "record_ref": f"{kind}:{row.id}", "record_type": kind, "id": row.id,
                "content": row.claim_text if kind == "entity_edges" else row.content,
                "claim_basis": row.claim_basis, "confidence": float(row.confidence),
                "status": row.status,
                "is_current": row.status in {"active", "disputed"}
                and (row.valid_from is None or utc(row.valid_from) <= now)
                and (row.valid_to is None or utc(row.valid_to) > now),
                "created_at": utc(row.created_at), "updated_at": utc(row.updated_at),
                "valid_from": payload["valid_from"], "valid_to": payload["valid_to"],
                "payload": payload,
                "entities": [{"id": entity_id, "display_name": names.get(entity_id, entity_id),
                              "role": role} for entity_id, role in dict.fromkeys(participants)],
                "sources": evidence_by_ref[(kind, row.id)] or [{"missing": True}],
            })
        return result
