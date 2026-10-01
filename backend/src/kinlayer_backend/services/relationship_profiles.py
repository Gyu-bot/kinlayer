"""Source-backed, self-perspective relationship assessments, one revision per axis."""

from datetime import UTC, datetime

from sqlalchemy import or_, select

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import Entity, Observation
from kinlayer_backend.services.entity_guards import lock_active_entities

PROFILE_VERSION = "relationship-profile-v1"
ASSESSMENT_TYPE = "relationship_assessment"
PROFILE_FIELDS = ("perspective_entity_id", "relationship_axis", "relationship_value")
AXES = {
    "closeness": {
        "label": "친밀도",
        "description": "내가 느끼는 상대와의 가까움. 상대의 감정이나 상호 인식을 뜻하지 않는다.",
        "values": [
            {
                "value": "recognize",
                "label": "얼굴·이름만 앎",
                "description": "누구인지 알아보는 정도",
            },
            {
                "value": "acquainted",
                "label": "알고 지냄",
                "description": "알고 지내지만 편안하거나 가깝다고 평가하지 않음",
            },
            {
                "value": "comfortable",
                "label": "편하게 지냄",
                "description": "편하게 대할 수 있는 사이",
            },
            {"value": "close", "label": "가까움", "description": "가까운 사이라고 느낌"},
            {
                "value": "very_close",
                "label": "매우 가까움",
                "description": "매우 가까운 사이라고 느낌",
            },
        ],
    },
    "importance": {
        "label": "중요도",
        "description": "내 삶에서 이 관계의 중요성. 사람의 객관적 가치나 AI 사용 허가가 아니다.",
        "values": [
            {
                "value": "normal",
                "label": "보통",
                "description": "특별히 높은 중요도를 두지 않는 관계",
            },
            {"value": "important", "label": "중요함", "description": "나에게 중요한 관계"},
            {
                "value": "very_important",
                "label": "매우 중요함",
                "description": "나에게 특히 중요한 관계",
            },
        ],
    },
    "interaction_frequency": {
        "label": "교류 빈도",
        "description": "사용자가 표현한 대략적인 연락·교류 빈도. 통화·일정 수집이나 기간별 계산을 하지 않는다.",
        "values": [
            {"value": "frequent", "label": "자주", "description": "자주 교류한다고 표현함"},
            {"value": "occasional", "label": "가끔", "description": "가끔 교류한다고 표현함"},
            {"value": "rare", "label": "드물게", "description": "드물게 교류한다고 표현함"},
            {
                "value": "none",
                "label": "교류 없음",
                "description": "교류가 없다고 명시함. 미입력이나 단절을 뜻하지 않는다.",
            },
        ],
    },
    "connection_state": {
        "label": "연결 상태",
        "description": "내 관점의 관계 유지 상태. 연락 빈도·친밀도·관계 유형과 별개다.",
        "values": [
            {"value": "maintained", "label": "유지 중", "description": "관계가 이어지고 있음"},
            {"value": "distant", "label": "뜸해짐", "description": "관계가 뜸해졌다고 표현함"},
            {
                "value": "disconnected",
                "label": "단절",
                "description": "관계가 끊겼다고 명시함. 연락이 없다는 이유만으로 설정하지 않는다.",
            },
        ],
    },
}


def profile_definition():
    return {"version": PROFILE_VERSION, "axes": AXES}


def is_assessment(payload):
    return payload.get("observation_type") == ASSESSMENT_TYPE


def validate_profile_shape(payload):
    """Pure validation shared by schemas and the canonical writer."""
    if not is_assessment(payload):
        if any(payload.get(field) is not None for field in PROFILE_FIELDS):
            raise ValueError("Relationship profile fields require relationship_assessment.")
        return
    if payload.get("claim_basis") != "reported":
        raise ValueError(
            "Current relationship assessments require the user reported basis; store interpretations as ordinary observations."
        )
    axis = payload.get("relationship_axis")
    if not payload.get("perspective_entity_id") or axis not in AXES:
        raise ValueError("Relationship assessment requires a perspective and a valid axis.")
    if payload.get("relationship_value") not in {item["value"] for item in AXES[axis]["values"]}:
        raise ValueError(
            "Relationship assessment value must belong to its axis; unknown means no record."
        )
    if payload.get("related_entities"):
        raise ValueError(
            "Relationship assessment has exactly one self perspective and one subject."
        )


def reject_compatibility_assessment(payload, previous=None):
    if (
        is_assessment(payload)
        or (previous is not None and previous.observation_type == ASSESSMENT_TYPE)
        or any(payload.get(field) is not None for field in PROFILE_FIELDS)
    ):
        raise api_error(
            422,
            "memory_write_required",
            "Use source-backed /api/memories for relationship assessments.",
        )


def active_self(session):
    return session.scalar(
        select(Entity).where(
            Entity.system_role == "self", Entity.status == "active", Entity.entity_type == "person"
        )
    )


def axis_conflict(row):
    raise api_error(
        409,
        "relationship_axis_conflict",
        "This relationship axis already has a current assertion; correct or retract its exact record.",
        {
            "current_record_ref": f"observations:{row.id}",
            "relationship_axis": row.relationship_axis,
        },
    )


def validate_assessment_change(old, record_type, payload):
    if not isinstance(old, Observation) or old.observation_type != ASSESSMENT_TYPE:
        return
    if record_type != "observations" or not is_assessment(payload):
        raise api_error(
            422,
            "validation_error",
            "Retract an assessment before storing a different kind of observation.",
        )
    if any(payload.get(field) != getattr(old, field) for field in PROFILE_FIELDS[:2]):
        raise api_error(
            422, "validation_error", "An assessment correction preserves its perspective and axis."
        )


def validate_assessment_write(session, payload, *, exclude_record_id=None, check_conflict=True):
    from kinlayer_backend.services.memories import utc

    try:
        validate_profile_shape(payload)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    if not is_assessment(payload):
        return
    entities = lock_active_entities(
        session, [payload["subject_entity_id"], payload["perspective_entity_id"]]
    )
    perspective = entities[payload["perspective_entity_id"]]
    subject = entities[payload["subject_entity_id"]]
    if perspective.system_role != "self" or perspective.entity_type != "person":
        raise api_error(
            422, "validation_error", "Assessment perspective must be the active protected self."
        )
    if (
        subject.entity_type != "person"
        or subject.id == perspective.id
        or subject.system_role == "self"
    ):
        raise api_error(
            422, "validation_error", "Assessment subject must be a different active person."
        )
    now = datetime.now(UTC)
    if payload.get("valid_to") is not None or any(
        payload.get(field) is not None and utc(payload[field]) > now
        for field in ("valid_from", "occurred_at")
    ):
        raise api_error(
            422,
            "validation_error",
            "Relationship assessments describe the current state: no future timestamps or valid_to; use correction or retraction.",
        )
    if not check_conflict:
        return
    row = session.scalar(
        select(Observation).where(
            Observation.id != exclude_record_id if exclude_record_id is not None else True,
            Observation.perspective_entity_id == perspective.id,
            Observation.subject_entity_id == subject.id,
            Observation.relationship_axis == payload["relationship_axis"],
            Observation.status.in_(("active", "disputed")),
        )
    )
    if row is not None:
        axis_conflict(row)


def current_assessments(session, entity_ids=None):
    from kinlayer_backend.services.memory_reads import current_condition

    perspective = active_self(session)
    if perspective is None:
        return []
    statement = (
        select(Observation)
        .join(Entity, Entity.id == Observation.subject_entity_id)
        .where(
            Observation.observation_type == ASSESSMENT_TYPE,
            Observation.perspective_entity_id == perspective.id,
            Entity.entity_type == "person",
            Entity.status == "active",
            Entity.id != perspective.id,
            current_condition(Observation, datetime.now(UTC)),
            Observation.valid_to.is_(None),
            or_(Observation.occurred_at.is_(None), Observation.occurred_at <= datetime.now(UTC)),
        )
    )
    if entity_ids is not None:
        statement = statement.where(Observation.subject_entity_id.in_(entity_ids))
    return list(session.scalars(statement))


def summary_profiles(session, entity_ids):
    result = {identifier: dict.fromkeys(AXES) for identifier in entity_ids}
    for row in current_assessments(session, entity_ids):
        result[row.subject_entity_id][row.relationship_axis] = row.relationship_value
    return result


class RelationshipProfileService:
    def __init__(self, session):
        self.session = session

    def get(self, entity_id):
        from kinlayer_backend.services.memory_reads import canonical_entity_scope

        entity = self.session.get(Entity, entity_id)
        if entity is None:
            raise api_error(404, "not_found", "Entity not found.")
        if entity.status == "merged":
            ids = canonical_entity_scope(self.session, entity_id)
            entity = self.session.scalar(
                select(Entity).where(Entity.id.in_(ids), Entity.status == "active")
            )
        if entity is None or entity.status != "active" or entity.entity_type != "person":
            raise api_error(404, "not_found", "Active person not found.")
        return self.for_entities([entity.id])[entity.id]

    def for_entities(self, entity_ids):
        from kinlayer_backend.services.memory_reads import MemoryReadService

        perspective = active_self(self.session)
        result = {
            identifier: {
                "version": PROFILE_VERSION,
                "entity_id": identifier,
                "perspective_entity_id": perspective.id if perspective else None,
                "axes": {axis: {"value": None, "label": None, "record": None} for axis in AXES},
            }
            for identifier in entity_ids
        }
        rows = current_assessments(self.session, entity_ids)
        memories = MemoryReadService(self.session)._hydrate(
            [("observations", row.id) for row in rows], datetime.now(UTC)
        )
        for row, memory in zip(rows, memories):
            definition = next(
                item
                for item in AXES[row.relationship_axis]["values"]
                if item["value"] == row.relationship_value
            )
            result[row.subject_entity_id]["axes"][row.relationship_axis] = {
                "value": row.relationship_value,
                "label": definition["label"],
                "record": memory,
            }
        return result


def validate_profile_merge(session, source_id, target_id, fields_to_merge):
    rows = list(
        session.scalars(
            select(Observation).where(
                Observation.subject_entity_id.in_((source_id, target_id)),
                Observation.observation_type == ASSESSMENT_TYPE,
                Observation.status.in_(("active", "disputed")),
            )
        )
    )
    source_rows = [row for row in rows if row.subject_entity_id == source_id]
    if source_rows and "observations" not in fields_to_merge:
        raise api_error(
            409,
            "relationship_profile_merge_required",
            "Include observations when merging a person with relationship assessments.",
        )
    target_axes = {row.relationship_axis: row for row in rows if row.subject_entity_id == target_id}
    for row in source_rows:
        if row.relationship_axis in target_axes:
            raise api_error(
                409,
                "relationship_profile_merge_conflict",
                "Resolve the two current assessment records before merging people.",
                {
                    "relationship_axis": row.relationship_axis,
                    "source_record_ref": f"observations:{row.id}",
                    "target_record_ref": f"observations:{target_axes[row.relationship_axis].id}",
                },
            )
