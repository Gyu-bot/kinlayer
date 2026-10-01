from copy import deepcopy
from datetime import UTC, datetime, timedelta
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from kinlayer_backend.models import Observation, Episode, MemoryChange
from kinlayer_backend.services.relationship_profiles import AXES


def person(client, name="Person", **extra):
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def setup_people(client):
    return person(client, "Self", system_role="self"), person(client, "A")


def body(perspective, subject, axis="closeness", value="close", request_id="profile-create"):
    return {
        "request_id": request_id,
        "record": {
            "record_type": "observations",
            "payload": {
                "observation_type": "relationship_assessment",
                "subject_entity_id": subject,
                "perspective_entity_id": perspective,
                "relationship_axis": axis,
                "relationship_value": value,
                "content": "사용자가 명시한 관계 평가",
                "claim_basis": "reported",
                "confidence": 1,
            },
        },
        "source": {
            "source_type": "manual_entry",
            "actor": "user",
            "excerpt": "나는 이 사람과 가까운 사이라고 느껴요.",
        },
    }


def profile(client, subject):
    response = client.get(f"/api/entities/{subject}/relationship-profile")
    assert response.status_code == 200, response.text
    return response.json()


def write(client, request):
    response = client.post("/api/memories", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_profile_and_ontology_no_inference(client):
    other = person(client)
    empty = profile(client, other)
    assert empty["perspective_entity_id"] is None
    assert set(empty["axes"]) == set(AXES)
    assert all(
        axis == {"value": None, "label": None, "record": None} for axis in empty["axes"].values()
    )
    self_id = person(client, "Self", system_role="self")
    assert profile(client, self_id)["axes"] == empty["axes"]
    assert profile(client, other)["perspective_entity_id"] == self_id
    ordinary = {
        "subject_entity_id": other,
        "observation_type": "relationship_pattern",
        "content": "매우 친하고 중요한 사람",
        "created_by": "user",
    }
    assert client.post("/api/observations", json=ordinary).status_code == 201
    assert profile(client, other)["axes"] == empty["axes"]
    ontology = client.get("/api/ontology").json()
    assert ontology["relationship_profile"]["version"] == "relationship-profile-v1"
    assert (
        sum(len(axis["values"]) for axis in ontology["relationship_profile"]["axes"].values()) == 15
    )
    assert (
        client.get("/api/system/config").json()["ontology"]["relationship_profile_version"]
        == "relationship-profile-v1"
    )


@pytest.mark.parametrize(
    "axis,value",
    [(axis, item["value"]) for axis, definition in AXES.items() for item in definition["values"]],
)
def test_each_axis_value_is_source_backed_and_exposed_without_self_inverse(client, axis, value):
    self_id, target = setup_people(client)
    request = body(self_id, target, axis, value)
    receipt = write(client, request)
    assert write(client, request) == receipt
    current = profile(client, target)["axes"][axis]
    assert current["value"] == value
    assert current["label"]
    record = current["record"]
    assert record["record_ref"] == receipt["new_record_ref"]
    assert record["payload"]["perspective_entity_id"] == self_id
    assert record["payload"]["relationship_axis"] == axis
    assert record["sources"][0]["excerpt"] == request["source"]["excerpt"]
    assert {row["role"] for row in record["entities"]} == {"subject", "perspective"}
    assert all(item["value"] is None for item in profile(client, self_id)["axes"].values())
    assert (
        client.get("/api/memory-changes", params={"record_ref": record["record_ref"]}).json()[
            "total"
        ]
        == 1
    )
    card = client.get(f"/api/entities/{target}/context-card").json()
    assert card["relationship_profile"]["axes"][axis] == current
    assert not any(
        row["observation_type"] == "relationship_assessment" for row in card["stable_context"]
    )
    assert any(item["record_id"] == record["id"] for item in card["provenance_summary"]["evidence"])
    pack = client.post("/api/context/pack", json={"query": "A", "entity_hints": [target]}).json()
    assert (
        pack["context_pack"]["matched_entities"][0]["relationship_profile"]["axes"][axis] == current
    )


def test_conflict_exact_correction_retract_and_history_are_atomic(client):
    self_id, target = setup_people(client)
    request = body(self_id, target)
    initial = write(client, request)
    other = body(self_id, target, value="very_close", request_id="duplicate")
    rejected = client.post("/api/memories", json=other)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "relationship_axis_conflict"
    assert rejected.json()["error"]["details"]["current_record_ref"] == initial["new_record_ref"]
    old = profile(client, target)["axes"]["closeness"]["record"]
    correction = {
        **other,
        "action": "correct",
        "old_record_ref": old["record_ref"],
        "expected_updated_at": old["updated_at"],
    }
    bad = deepcopy(correction)
    bad["record"]["payload"]["perspective_entity_id"] = target
    assert client.post("/api/memories", json=bad).status_code == 422
    assert profile(client, target)["axes"]["closeness"]["record"]["record_ref"] == old["record_ref"]
    changed = write(client, correction)
    assert changed["new_record_ref"] != old["record_ref"]
    assert write(client, correction) == changed
    assert profile(client, target)["axes"]["closeness"]["value"] == "very_close"
    assert client.get("/api/memories/observations/" + old["id"]).json()["status"] == "superseded"
    stale = {**correction, "request_id": "stale"}
    assert client.post("/api/memories", json=stale).status_code == 409
    current = profile(client, target)["axes"]["closeness"]["record"]
    retract = {
        "request_id": "reset",
        "action": "retract",
        "old_record_ref": current["record_ref"],
        "expected_updated_at": current["updated_at"],
        "source": request["source"],
    }
    write(client, retract)
    assert profile(client, target)["axes"]["closeness"]["value"] is None
    with client.app.state.session_factory() as session:
        assert session.query(Observation).count() == 2
        assert session.query(Episode).count() == 3
        assert session.query(MemoryChange).count() == 3


@pytest.mark.parametrize(
    "patch",
    [
        {"relationship_axis": "unknown"},
        {"relationship_value": "unknown"},
        {"relationship_value": "important"},
        {"perspective_entity_id": None},
        {"claim_basis": "inferred"},
        {"claim_basis": "unknown"},
        {"valid_from": "2099-01-01T00:00:00Z"},
        {"occurred_at": "2099-01-01T00:00:00Z"},
        {"valid_to": "2000-01-01T00:00:00Z"},
        {"valid_to": "2099-01-01T00:00:00Z"},
    ],
)
def test_reject_invalid_profile_assertions_without_any_saved_source(client, patch):
    self_id, target = setup_people(client)
    request = body(self_id, target)
    request["record"]["payload"].update(patch)
    assert client.post("/api/memories", json=request).status_code == 422
    with client.app.state.session_factory() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 0
        )


def test_subject_perspective_axis_and_legacy_bypass_guards(client):
    self_id, target = setup_people(client)
    request = body(self_id, target)
    for overrides in (
        {"subject_entity_id": self_id},
        {"perspective_entity_id": target},
        {"related_entities": [{"entity_id": self_id, "role": "experiencer"}]},
        {"observation_type": "stable_fact"},
    ):
        invalid = deepcopy(request)
        invalid["record"]["payload"].update(overrides)
        assert client.post("/api/memories", json=invalid).status_code == 422
    generic = {**request["record"]["payload"], "claim_type": "fact", "created_by": "user"}
    assert client.post("/api/observations", json=generic).status_code == 422
    candidate = {"candidate_type": "observation", "payload": generic, "created_by": "user"}
    assert client.post("/api/candidates", json=candidate).status_code == 422
    receipt = write(client, request)
    record = profile(client, target)["axes"]["closeness"]["record"]
    assert (
        client.patch("/api/observations/" + record["id"], json={"content": "overwrite"}).status_code
        == 422
    )
    assert client.delete("/api/observations/" + record["id"]).status_code == 422
    correction = {
        **request,
        "request_id": "axis-change",
        "action": "correct",
        "old_record_ref": receipt["new_record_ref"],
    }
    correction["record"]["payload"].update(
        relationship_axis="importance", relationship_value="important"
    )
    assert client.post("/api/memories", json=correction).status_code == 422


def test_reattribute_guard_and_merge_conflict_preserve_both_sources(client):
    self_id, left = setup_people(client)
    right = person(client, "B")
    left_receipt = write(client, body(self_id, left))
    right_receipt = write(client, body(self_id, right, value="very_close", request_id="right"))
    moved = body(self_id, right, request_id="move")
    moved.update(action="reattribute", old_record_ref=left_receipt["new_record_ref"])
    assert client.post("/api/memories", json=moved).status_code == 409
    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "created_by": "user",
            "confidence": 1,
            "payload": {
                "source_entity_id": left,
                "target_entity_id": right,
                "reason": "동일인",
                "fields_to_merge": ["observations"],
            },
        },
    ).json()
    conflict = client.post(f"/api/candidates/{candidate['id']}/accept")
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "relationship_profile_merge_conflict"
    assert (
        profile(client, left)["axes"]["closeness"]["record"]["record_ref"]
        == left_receipt["new_record_ref"]
    )
    assert (
        profile(client, right)["axes"]["closeness"]["record"]["record_ref"]
        == right_receipt["new_record_ref"]
    )
    write(
        client,
        {
            "request_id": "remove-right",
            "action": "retract",
            "old_record_ref": right_receipt["new_record_ref"],
            "source": body(self_id, right)["source"],
        },
    )
    accepted = client.post(f"/api/candidates/{candidate['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert profile(client, left)["entity_id"] == right
    assert (
        profile(client, right)["axes"]["closeness"]["record"]["record_ref"]
        == left_receipt["new_record_ref"]
    )


def test_people_filters_apply_before_paging_and_have_null_summaries(client):
    self_id, first = setup_people(client)
    middle, last = person(client, "B"), person(client, "C")
    write(client, body(self_id, last, "importance", "very_important"))
    write(client, body(self_id, last, "connection_state", "disconnected", request_id="connection"))
    response = client.get(
        "/api/people",
        params={"importance": "very_important", "connection_state": "disconnected", "limit": 1},
    ).json()
    assert response["total"] == 1
    assert response["items"][0]["id"] == last
    assert response["items"][0]["relationship_profile"] == {
        "importance": "very_important",
        "closeness": None,
        "interaction_frequency": None,
        "connection_state": "disconnected",
    }
    unset = client.get(
        "/api/people", params={"importance": "unset", "limit": 1, "offset": 1}
    ).json()
    assert unset["total"] == 2 and unset["items"][0]["id"] == middle
    assert client.get("/api/people", params={"importance": "frequent"}).status_code == 422
    assert (
        client.get("/api/people", params={"q": "A", "importance": "very_important"}).json()["total"]
        == 0
    )
    assert (
        client.get("/api/people", params={"importance": "unset"}).json()["items"][0]["id"] == first
    )


def test_importance_only_tiebreaks_relevant_matches_and_never_creates_match(client):
    self_id, first = setup_people(client)
    client.patch(
        f"/api/entities/{first}", json={"display_name": "은하수", "canonical_name": "은하수"}
    )
    second, unrelated = person(client, "백두산"), person(client, "제주도")
    write(client, body(self_id, second, "importance", "important"))
    write(client, body(self_id, unrelated, "importance", "very_important", request_id="unrelated"))
    response = client.post(
        "/api/context/retrieve", json={"query": "zzzz", "entity_hints": [first, second]}
    ).json()
    assert [row["entity_id"] for row in response["matched_entities"]] == [second, first]
    assert response["matched_entities"][0]["score"] == response["matched_entities"][1]["score"]
    only = client.post("/api/context/retrieve", json={"query": "은하수"}).json()
    assert [row["entity_id"] for row in only["matched_entities"]] == [first]
    assert not only["observations"]


def test_database_unique_index_and_future_projection_guards(client):
    self_id, target = setup_people(client)
    receipt = write(client, body(self_id, target))
    with client.app.state.session_factory() as session:
        existing = session.get(Observation, receipt["new_record_ref"].split(":")[1])
        duplicate = Observation(
            subject_entity_id=target,
            perspective_entity_id=self_id,
            relationship_axis="closeness",
            relationship_value="close",
            observation_type="relationship_assessment",
            content="duplicate",
            claim_basis="reported",
            claim_type="fact",
            created_by="user",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        existing = session.get(Observation, receipt["new_record_ref"].split(":")[1])
        existing.occurred_at = datetime.now(UTC) + timedelta(days=1)
        session.commit()
    assert profile(client, target)["axes"]["closeness"]["record"] is None
    assert client.get("/api/people", params={"closeness": "close"}).json()["total"] == 0
    assert client.get("/api/people", params={"closeness": "unset"}).json()["total"] == 1


def test_additive_migration_keeps_old_observations_and_guards_history(tmp_path):
    migration = runpy.run_path(
        str(Path("backend/alembic/versions/20261001_0013_relationship_profiles.py"))
    )
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entities (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE observations (id VARCHAR(36) PRIMARY KEY, subject_entity_id VARCHAR(36) NOT NULL, observation_type VARCHAR(120) NOT NULL, content TEXT NOT NULL, status VARCHAR(40), claim_basis VARCHAR(40))"
            )
        )
        connection.execute(text("INSERT INTO entities VALUES ('self'), ('other')"))
        connection.execute(
            text(
                "INSERT INTO observations VALUES ('old', 'other', 'relationship_pattern', 'old prose', 'active', 'unknown')"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        old = dict(
            connection.execute(text("SELECT * FROM observations WHERE id='old'")).mappings().one()
        )
        assert (
            old["content"] == "old prose"
            and old["relationship_axis"] is None
            and old["perspective_entity_id"] is None
        )
        connection.execute(
            text(
                "INSERT INTO observations VALUES ('new', 'other', 'relationship_assessment', 'reported assessment', 'deleted', 'reported', 'self', 'importance', 'important')"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="history"):
                migration["downgrade"]()


def test_agent_correction_dry_run_matches_canonical_profile_rules_and_replay(client):
    self_id, target = setup_people(client)
    receipt = write(client, body(self_id, target))
    request = {
        "request_id": "compat-profile-correction",
        "old_record_ref": receipt["new_record_ref"],
        "new_record": body(self_id, target, value="very_close")["record"],
        "correction_source": {
            "source_type": "agent_conversation",
            "source_actor": "user",
            "user_explicit": True,
            "excerpt": "이 사람과 매우 가까워졌어요.",
        },
        "created_by": "ai_agent",
    }
    accepted = client.post(
        "/api/agent-writes/validate", json={"write_type": "correction", "payload": request}
    )
    assert accepted.status_code == 200 and accepted.json()["accepted"], accepted.text
    for patch in (
        {"relationship_axis": "importance", "relationship_value": "important"},
        {"perspective_entity_id": target},
        {"occurred_at": "2099-01-01T00:00:00Z"},
    ):
        bad = deepcopy(request)
        bad["new_record"]["payload"].update(patch)
        validation = client.post(
            "/api/agent-writes/validate", json={"write_type": "correction", "payload": bad}
        )
        assert validation.status_code == 200 and not validation.json()["accepted"], validation.text
        assert client.post("/api/corrections/apply", json=bad).status_code == 422
    applied = client.post("/api/corrections/apply", json=request)
    assert applied.status_code == 200, applied.text
    replay = client.post("/api/corrections/apply", json=request)
    assert replay.status_code == 200 and replay.json() == applied.json(), replay.text
