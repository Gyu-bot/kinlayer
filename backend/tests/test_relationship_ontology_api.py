from copy import deepcopy

import pytest
from sqlalchemy import select

from kinlayer_backend.models import (
    AllowedEdgeType,
    EntityEdge,
    Episode,
    MemoryChange,
    OntologyRegistryValue,
)
from kinlayer_backend.services.ontology import seed_ontology_values


def people(client):
    return [
        client.post("/api/entities", json={"entity_type": "person", "display_name": name}).json()[
            "id"
        ]
        for name in ("A", "B")
    ]


def edge_payload(left, right, kind="friend", **extra):
    return {
        "from_entity_id": left,
        "to_entity_id": right,
        "relation_type": kind,
        "claim_text": "출처에 기록된 관계",
        "claim_basis": "reported",
        "confidence": 1,
        **extra,
    }


def memory(payload, request_id="edge-create"):
    return {
        "request_id": request_id,
        "record": {"record_type": "entity_edges", "payload": payload},
        "source": {"source_type": "manual_entry", "actor": "user", "excerpt": "출처의 관계 설명"},
    }


def test_ontology_contract_and_idempotent_seed_preserve_history(client):
    left, right = people(client)
    with client.app.state.session_factory() as session:
        edge = EntityEdge(
            from_entity_id=left,
            to_entity_id=right,
            relation_type="dating_interest",
            directed=False,
            claim_text="한쪽의 호감",
            claim_type="fact",
            created_by="user",
            properties={"old_key": "keep"},
        )
        session.add(edge)
        session.commit()
        old_id, old_updated = edge.id, edge.updated_at
        # Simulate registry/definition metadata from an earlier deployment.
        session.scalar(
            select(AllowedEdgeType).where(AllowedEdgeType.relation_type == "friend")
        ).description = "obsolete"
        seed_ontology_values(session)
        first = client.get("/api/ontology/edge-types").json()
        seed_ontology_values(session)
        session.expire_all()
        assert session.get(EntityEdge, old_id).properties == {"old_key": "keep"}
        assert session.get(EntityEdge, old_id).updated_at.replace(
            tzinfo=None
        ) == old_updated.replace(tzinfo=None)
        assert session.query(AllowedEdgeType).count() == 38
        assert (
            session.scalar(
                select(OntologyRegistryValue).where(
                    OntologyRegistryValue.category == "edge_type",
                    OntologyRegistryValue.value == "dating_interest",
                )
            ).support_level
            == "legacy"
        )
    second = client.get("/api/ontology/edge-types").json()
    assert first == second
    ontology = client.get("/api/ontology").json()
    assert ontology["version"] == second["version"] == "relationship-v1"
    assert ontology["edge_types"] == second["items"]
    assert client.get("/api/system/config").json()["ontology"]["version"] == "relationship-v1"
    items = {item["relation_type"]: item for item in second["items"]}
    assert sum(item["write_supported"] for item in items.values()) == 27
    assert items["parent_of"]["label"] == "부모"
    assert items["parent_of"]["inverse_label"] == "자녀"
    assert items["reports_to"]["label"] == "부하"
    assert items["reports_to"]["inverse_label"] == "상사"
    assert items["situationship"]["directed_default"] is False
    assert items["knows"]["replacement_type"] == "acquaintance"
    assert items["dating_interest"]["replacement_type"] is None
    assert items["dating_interest"]["active"] and not items["dating_interest"]["write_supported"]
    assert items["friend"]["allowed_properties_schema"]["additionalProperties"] is False
    assert client.get(f"/api/graph/ego/{left}").json()["edges"][0]["edge_id"] == old_id


@pytest.mark.parametrize(
    "kind,directed",
    [
        ("parent_of", True),
        ("sibling", False),
        ("spouse", False),
        ("relative", False),
        ("in_law", False),
        ("former_spouse", False),
        ("classmate", False),
        ("schoolmate", False),
        ("cohort_peer", False),
        ("senior_of", True),
        ("teacher_of", True),
        ("mentor_of", True),
        ("business_partner", False),
        ("client_of", True),
        ("reports_to", True),
        ("neighbor", False),
        ("housemate", False),
        ("community_peer", False),
        ("situationship", False),
    ],
)
def test_new_relationships_have_fixed_direction_and_single_edge_from_both_people(
    client, kind, directed
):
    left, right = people(client)
    payload = edge_payload(
        left,
        right,
        kind,
        properties={
            "context": "공통 배경",
            "relationship_detail": "출처의 호칭",
            "origin": "지인 소개",
        },
    )
    response = client.post("/api/memories", json=memory(payload))
    assert response.status_code == 200, response.text
    edge_id = response.json()["new_record_ref"].split(":")[1]
    stored = client.get(f"/api/edges/{edge_id}").json()
    assert stored["directed"] is directed
    for focal in (left, right):
        graph = client.get(f"/api/graph/ego/{focal}").json()
        assert [row["edge_id"] for row in graph["edges"]] == [edge_id]
    bad = client.post("/api/edges", json={**payload, "directed": not directed})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"relation_type": "dating_interest"},
        {"relation_type": "knows"},
        {"relation_type": "matched_on_app"},
        {"directed": True},
        {"properties": {"appointment_at": "tomorrow"}},
        {"properties": {"context": 2}},
        {"properties": {"origin": ""}},
        {"properties": {"relationship_detail": "x" * 301}},
        {"properties": {"context": {"name": "company"}}},
    ],
)
def test_invalid_new_relationship_writes_are_atomic(client, changes):
    left, right = people(client)
    payload = edge_payload(left, right, **changes)
    assert client.post("/api/memories", json=memory(payload)).status_code == 422
    assert client.post("/api/edges", json=payload).status_code == 422
    with client.app.state.session_factory() as session:
        assert session.query(EntityEdge).count() == 0
        assert session.query(MemoryChange).count() == 0
        assert session.query(Episode).count() == 0


def test_no_self_relationship_and_patch_constraints(client):
    left, right = people(client)
    assert client.post("/api/edges", json=edge_payload(left, left)).status_code == 422
    organization = client.post(
        "/api/entities", json={"entity_type": "organization", "display_name": "Org"}
    ).json()["id"]
    for path, body in (
        ("/api/edges", edge_payload(left, organization)),
        ("/api/memories", memory(edge_payload(left, organization))),
    ):
        assert client.post(path, json=body).status_code == 422
    created = client.post("/api/edges", json=edge_payload(left, right)).json()
    for patch in (
        {"directed": True},
        {"relation_type": "dating_interest"},
        {"properties": {"unknown": "value"}},
    ):
        assert client.patch(f"/api/edges/{created['id']}", json=patch).status_code == 422
    changed = client.patch(f"/api/edges/{created['id']}", json={"relation_type": "parent_of"})
    assert changed.status_code == 200
    assert changed.json()["directed"] is True


def test_legacy_correction_preserves_assertion_but_new_or_reattributed_legacy_rejected(client):
    left, right = people(client)
    payload = edge_payload(
        left, right, "dating_interest", directed=False, properties={"old_key": "original"}
    )
    with client.app.state.session_factory() as session:
        edge = EntityEdge(**payload, claim_type="fact", created_by="user")
        session.add(edge)
        session.commit()
        old_id = edge.id
    body = memory({**payload, "claim_text": "문장만 정정"}, "legacy-correct")
    body.update(action="correct", old_record_ref=f"entity_edges:{old_id}")
    changed_properties = deepcopy(body)
    changed_properties["record"]["payload"]["properties"]["context"] = "new"
    assert client.post("/api/memories", json=changed_properties).status_code == 422
    assert client.get(f"/api/edges/{old_id}").json()["status"] == "active"
    response = client.post("/api/memories", json=body)
    assert response.status_code == 200, response.text
    new_id = response.json()["new_record_ref"].split(":")[1]
    assert client.get(f"/api/edges/{new_id}").json()["properties"] == {"old_key": "original"}
    assert client.get(f"/api/edges/{old_id}").json()["status"] == "superseded"
    assert client.post("/api/memories", json=body).json() == response.json()
    assert client.post("/api/memories", json=memory(payload, "legacy-new")).status_code == 422
    third = client.post(
        "/api/entities", json={"entity_type": "person", "display_name": "C"}
    ).json()["id"]
    reattribute = memory({**payload, "to_entity_id": third}, "legacy-reattribute")
    reattribute.update(action="reattribute", old_record_ref=f"entity_edges:{new_id}")
    assert client.post("/api/memories", json=reattribute).status_code == 422


def test_agent_dry_run_enforces_legacy_and_direction_and_preserves_safe_correction(client):
    left, right = people(client)
    with client.app.state.session_factory() as session:
        edge = EntityEdge(
            **edge_payload(left, right, "dating_interest", directed=False),
            claim_type="fact",
            created_by="user",
        )
        session.add(edge)
        session.commit()
        old_id = edge.id
    correction = {
        "old_record_ref": f"entity_edges:{old_id}",
        "new_record": {
            "record_type": "entity_edges",
            "payload": edge_payload(left, right, "dating_interest"),
        },
        "correction_source": {
            "source_type": "agent_conversation",
            "source_actor": "user",
            "user_explicit": True,
            "excerpt": "출처 문장 정정",
        },
        "created_by": "ai_agent",
    }
    response = client.post(
        "/api/agent-writes/validate", json={"write_type": "correction", "payload": correction}
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted"], response.text
    correction["new_record"]["payload"]["directed"] = True
    response = client.post(
        "/api/agent-writes/validate", json={"write_type": "correction", "payload": correction}
    )
    assert not response.json()["accepted"]
