"""Versioned relationship vocabulary and shared write constraints.

Directed labels describe source and target roles respectively. Directed
predicates specify storage orientation explicitly; inverse labels never require
another edge. Legacy definitions remain readable without silently reinterpreting
historical assertions.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import AllowedEdgeType, Entity, EntityEdge

ONTOLOGY_VERSION = "relationship-v1"


@dataclass(frozen=True)
class RelationshipDefinition:
    label: str
    category: str
    description: str
    inverse_label: str | None = None
    support_level: str = "supported"
    replacement_type: str | None = None

    @property
    def directed(self) -> bool:
        return self.inverse_label is not None


# Source -> target; label is the source role and inverse_label the target role.
EDGE_DEFINITIONS = {
    "acquaintance": RelationshipDefinition(
        "지인", "social", "서로 알고 지내는 사이. 친구나 다른 구체적 관계를 뜻하지 않는다."
    ),
    "friend": RelationshipDefinition(
        "친구", "social", "친구로 표현된 관계. 친밀도나 상호 신뢰의 정도를 추론하지 않는다."
    ),
    "family": RelationshipDefinition(
        "가족", "family", "가족이지만 세부 역할이 명확하지 않은 관계."
    ),
    "parent_of": RelationshipDefinition(
        "부모", "family", "from은 부모, to는 자녀. 생물학적 부모 여부를 추론하지 않는다.", "자녀"
    ),
    "sibling": RelationshipDefinition(
        "형제자매", "family", "형제자매 관계. 성별이나 출생 순서는 추론하지 않는다."
    ),
    "spouse": RelationshipDefinition("배우자", "family", "현재 배우자로 명시된 관계."),
    "relative": RelationshipDefinition(
        "친척",
        "family",
        "친척 관계. 구체적인 촌수나 호칭은 relationship_detail에 출처대로 보존한다.",
    ),
    "in_law": RelationshipDefinition(
        "인척",
        "family",
        "혼인으로 연결된 가족 관계. 구체적인 호칭은 relationship_detail에 보존한다.",
    ),
    "former_spouse": RelationshipDefinition(
        "전 배우자",
        "family",
        "과거 배우자였다는 관계. 종료 사유나 현재 연락 여부를 추론하지 않는다.",
    ),
    "coworker": RelationshipDefinition(
        "동료", "work", "같은 조직에서 일하는 관계. 조직명은 context에 기록한다."
    ),
    "former_coworker": RelationshipDefinition(
        "전 동료", "work", "과거 같은 조직에서 일했던 관계. 현재 친분 여부와 별개다."
    ),
    "reports_to": RelationshipDefinition(
        "부하", "work", "from은 부하, to는 보고받는 상사. 단순 직급 차이와 구별한다.", "상사"
    ),
    "collaborated_with": RelationshipDefinition(
        "협업자", "work", "함께 일을 수행하는 관계. 같은 조직 소속을 뜻하지 않는다."
    ),
    "business_partner": RelationshipDefinition(
        "동업자", "work", "사업을 함께 운영하는 관계. 일반 협업과 구별한다."
    ),
    "client_of": RelationshipDefinition(
        "고객",
        "work",
        "from은 고객, to는 서비스를 제공하는 사람. 두 끝점 모두 사람이다.",
        "서비스 제공자",
    ),
    "classmate": RelationshipDefinition(
        "동창", "education", "같은 학교에서 함께 다닌 관계. 학교명은 context에 기록한다."
    ),
    "schoolmate": RelationshipDefinition(
        "동문", "education", "같은 학교 출신. 재학 시기가 겹친다고 추론하지 않는다."
    ),
    "cohort_peer": RelationshipDefinition(
        "동기",
        "education",
        "입학·입사 등 같은 시기에 들어온 관계. 학교·회사 등의 배경은 context에 기록한다.",
    ),
    "senior_of": RelationshipDefinition(
        "선배",
        "education",
        "from은 선배, to는 후배. 학교·직장·모임 배경은 context에 기록한다. 나이나 관리 권한을 추론하지 않는다.",
        "후배",
    ),
    "teacher_of": RelationshipDefinition(
        "스승", "education", "from은 스승, to는 제자. 단순 조언과 구별한다.", "제자"
    ),
    "mentor_of": RelationshipDefinition(
        "멘토",
        "education",
        "from은 멘토, to는 멘티. 공식 직장 상하 관계를 추론하지 않는다.",
        "멘티",
    ),
    "neighbor": RelationshipDefinition("이웃", "community", "주거 지역을 통해 알고 지내는 관계."),
    "housemate": RelationshipDefinition(
        "동거인", "community", "함께 거주하는 관계. 연인이나 가족임을 추론하지 않는다."
    ),
    "community_peer": RelationshipDefinition(
        "같은 모임의 지인",
        "community",
        "같은 모임에서 실제로 알고 지내는 관계. 같은 소속이라는 이유만으로 연결하지 않는다.",
    ),
    "situationship": RelationshipDefinition(
        "썸",
        "romance",
        "썸으로 표현된 관계를 양방향으로 기록한다. 누가 그렇게 표현했는지 출처를 보존하며 상호 호감 확인이나 교제를 추론하지 않는다.",
    ),
    "romantic_partner": RelationshipDefinition(
        "연인", "romance", "현재 교제하는 관계로 명시된 경우. 호감이나 썸만으로 확정하지 않는다."
    ),
    "former_partner": RelationshipDefinition(
        "전 연인", "romance", "과거 교제했던 관계. 현재 연락 여부와 별개다."
    ),
}

for _key, _label, _inverse, _replacement in [
    ("knows", "아는 사이", None, "acquaintance"),
    ("dating", "교제 중", None, "romantic_partner"),
    ("former_dating", "이전 교제", None, "former_partner"),
    ("dating_interest", "호감 (기존 유형)", None, None),
    ("manager_of", "상사 (기존 유형)", "부하", None),
    ("client_contact", "고객 연락처 (기존 유형)", None, None),
    ("vendor_contact", "거래처 연락처 (기존 유형)", None, None),
    ("introduced_by", "소개받음 (기존 유형)", "소개함", None),
    ("referred_by", "추천받음 (기존 유형)", "추천함", None),
    ("introduced_for_dating", "소개팅 (기존 유형)", "소개팅 연결", None),
    ("matched_on_app", "앱에서 알게 됨 (기존 유형)", None, None),
]:
    EDGE_DEFINITIONS[_key] = RelationshipDefinition(
        _label,
        "legacy",
        "기존 기록의 조회·정정용 유형. 새 기록에 사용하지 않는다. 기존 의미나 방향을 자동 변환하지 않는다.",
        _inverse,
        "legacy",
        _replacement,
    )

EDGE_PROPERTIES_SCHEMA = {
    "type": "object",
    "properties": {
        "context": {
            "type": "string",
            "minLength": 1,
            "maxLength": 300,
            "description": "관계가 성립하는 학교·회사·모임 등의 배경",
        },
        "relationship_detail": {
            "type": "string",
            "minLength": 1,
            "maxLength": 300,
            "description": "출처에 명시된 세부 관계·가족 호칭",
        },
        "origin": {
            "type": "string",
            "minLength": 1,
            "maxLength": 300,
            "description": "앱명·소개 경위 등. 만남 사건이나 약속 일정은 제외",
        },
    },
    "additionalProperties": False,
}


def edge_type_metadata(row: AllowedEdgeType) -> dict[str, Any]:
    definition = EDGE_DEFINITIONS.get(row.relation_type)
    return {
        "label": definition.label if definition else row.relation_type,
        "inverse_label": definition.inverse_label if definition else None,
        "category": definition.category if definition else "legacy",
        "support_level": definition.support_level if definition else "legacy",
        "write_supported": bool(
            row.active and definition and definition.support_level == "supported"
        ),
        "replacement_type": definition.replacement_type if definition else None,
    }


def validate_edge_write(
    session: Session,
    payload: dict[str, Any],
    *,
    previous: EntityEdge | None = None,
) -> AllowedEdgeType | None:
    """Normalize missing direction and validate every semantic edge mutation.

    Safe corrections may retain an old edge's complete structural tuple, even
    when it no longer satisfies today's vocabulary. Changing any part of that
    tuple requires the current contract; this never creates a new legacy claim.
    """
    structural_fields = (
        "from_entity_id",
        "to_entity_id",
        "relation_type",
        "directed",
        "properties",
    )
    if previous is not None and payload.get("directed") is None:
        if payload.get("relation_type") == previous.relation_type:
            payload["directed"] = previous.directed
    preserved = previous is not None and all(
        payload.get(field, {} if field == "properties" else None) == getattr(previous, field)
        for field in structural_fields
    )
    kind = session.scalar(
        select(AllowedEdgeType).where(
            AllowedEdgeType.relation_type == payload["relation_type"],
            AllowedEdgeType.active.is_(True),
        )
    )
    if preserved:
        return kind
    definition = EDGE_DEFINITIONS.get(payload["relation_type"])
    if kind is None or definition is None or definition.support_level != "supported":
        raise api_error(
            422,
            "validation_error",
            "Relationship type is not supported for new writes; refresh /api/ontology/edge-types.",
        )
    if payload["from_entity_id"] == payload["to_entity_id"]:
        raise api_error(422, "validation_error", "A relationship requires two different people.")
    source = session.get(Entity, payload["from_entity_id"])
    target = session.get(Entity, payload["to_entity_id"])
    if (
        not source
        or not target
        or source.entity_type != kind.from_entity_type
        or target.entity_type != kind.to_entity_type
    ):
        raise api_error(422, "validation_error", "Relation endpoint entity types do not match.")
    if payload.get("directed") is None:
        payload["directed"] = definition.directed
    if payload["directed"] is not definition.directed:
        raise api_error(
            422, "validation_error", "Relationship direction must match its ontology definition."
        )
    properties = payload.get("properties", {})
    if (
        not isinstance(properties, dict)
        or set(properties) - EDGE_PROPERTIES_SCHEMA["properties"].keys()
    ):
        raise api_error(
            422,
            "validation_error",
            "Only context, relationship_detail and origin relationship properties are supported.",
        )
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 300
        for value in properties.values()
    ):
        raise api_error(
            422,
            "validation_error",
            "Relationship property values must be nonempty strings of at most 300 characters.",
        )
    return kind
