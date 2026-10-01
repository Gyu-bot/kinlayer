from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from threading import Barrier

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import (
    Candidate,
    EdgeEvidence,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Episode,
    MemoryChange,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.schemas.memories import MemoryWriteRequest
from kinlayer_backend.services.memories import MemoryService


def person(client, name="Alex"):
    response = client.post(
        "/api/entities", json={"entity_type": "person", "display_name": name, "created_by": "user"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def memory(entity_id, request_id="memory-1"):
    return {
        "request_id": request_id,
        "record": {
            "record_type": "observations",
            "payload": {
                "subject_entity_id": entity_id,
                "observation_type": "communication_preference",
                "content": "Alex may prefer short replies.",
                "claim_basis": "inferred",
                "confidence": 0.6,
            },
        },
        "source": {
            "source_type": "agent_conversation",
            "actor": "user",
            "excerpt": "Alex said they were busy and sent short replies.",
        },
    }


def write(client, body):
    response = client.post("/api/memories", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def session_maker(database_url):
    return create_session_maker(Settings(database_url=database_url))


def test_create_saves_inference_evidence_history_and_pending_embedding(client, database_url):
    target = person(client)
    experiencer = person(client, "User")
    body = memory(target)
    body["record"]["payload"]["related_entities"] = [
        {"entity_id": experiencer, "role": "experiencer", "confidence": 1}
    ]
    receipt = write(client, body)
    assert receipt["action"] == "create"
    assert receipt["old_record_ref"] is None
    with session_maker(database_url)() as session:
        row = session.get(Observation, receipt["new_record_ref"].split(":")[1])
        assert (row.status, row.claim_basis, float(row.confidence), row.embedding_status) == (
            "active",
            "inferred",
            0.6,
            "pending",
        )
        assert row.embedding is None
        link = session.scalar(
            select(ObservationEntity).where(ObservationEntity.observation_id == row.id)
        )
        assert (link.entity_id, link.role) == (experiencer, "experiencer")
        episode = session.get(Episode, receipt["source_episode_id"])
        assert episode.actor == "user"
        assert episode.body_excerpt == body["source"]["excerpt"]
        assert episode.occurred_at is None
        assert episode.body_hash.startswith("sha256:")
        assert (
            session.query(ObservationEvidence)
            .filter_by(observation_id=row.id, episode_id=episode.id)
            .count()
            == 1
        )
        change = session.get(MemoryChange, receipt["change_id"])
        assert change.request_id == body["request_id"]
        assert change.new_record_ref == receipt["new_record_ref"]
        assert session.query(Candidate).count() == 0


@pytest.mark.parametrize(
    "fact_type,content,value",
    [
        ("email", "alex@Example.COM", {"text": "alex@example.com"}),
        ("birth_date", "1994", {"year": 1994, "precision": "year"}),
        ("birthday", "--02-29", {"month": 2, "day": 29, "precision": "day"}),
    ],
)
def test_typed_profile_facts_save_with_evidence(client, database_url, fact_type, content, value):
    body = memory(person(client))
    body["record"] = {
        "record_type": "entity_facts",
        "payload": {
            "entity_id": body["record"]["payload"]["subject_entity_id"],
            "fact_type": fact_type,
            "content": content,
            "value": value,
            "claim_basis": "reported",
            "confidence": 0.9,
        },
    }
    receipt = write(client, body)
    with session_maker(database_url)() as session:
        row = session.get(EntityFact, receipt["new_record_ref"].split(":")[1])
        assert row.status == "active"
        assert session.query(EntityFactEvidence).filter_by(entity_fact_id=row.id).count() == 1
        if fact_type == "birthday":
            assert row.value["year"] is None
        if fact_type == "email":
            assert row.content == row.value["text"] == "alex@example.com"


def test_edge_write_and_correction_preserve_factual_end_time(client, database_url):
    left, right = person(client, "User"), person(client)
    body = memory(right)
    body["record"] = {
        "record_type": "entity_edges",
        "payload": {
            "from_entity_id": left,
            "to_entity_id": right,
            "relation_type": "coworker",
            "claim_text": "Alex worked with me in 2020.",
            "claim_basis": "reported",
            "confidence": 1,
            "valid_from": "2020-01-01T00:00:00Z",
            "valid_to": "2020-12-31T00:00:00Z",
        },
    }
    first = write(client, body)
    correction = deepcopy(body)
    correction.update(
        request_id="correction-1", action="correct", old_record_ref=first["new_record_ref"]
    )
    correction["record"]["payload"]["relation_type"] = "former_coworker"
    correction["source"]["excerpt"] = "Alex was a former coworker; we worked together in 2020."
    second = write(client, correction)
    with session_maker(database_url)() as session:
        old = session.get(EntityEdge, first["new_record_ref"].split(":")[1])
        new = session.get(EntityEdge, second["new_record_ref"].split(":")[1])
        assert old.status == "superseded" and new.status == "active"
        assert old.valid_to == datetime(2020, 12, 31)
        assert old.invalidated_by_edge_id == new.id
        assert session.query(EdgeEvidence).filter_by(edge_id=new.id).count() == 1


def test_retract_without_replacement_and_reattribute_with_roles(client, database_url):
    first_person, other = person(client), person(client, "Blair")
    body = memory(first_person)
    first = write(client, body)
    replacement = deepcopy(body)
    replacement.update(
        request_id="move-1", action="reattribute", old_record_ref=first["new_record_ref"]
    )
    replacement["record"]["payload"]["subject_entity_id"] = other
    replacement["record"]["payload"]["related_entities"] = [{"entity_id": other, "role": "about"}]
    replacement["source"]["excerpt"] = "I meant Blair, not Alex."
    second = write(client, replacement)
    third = write(
        client,
        {
            "request_id": "retract-1",
            "action": "retract",
            "old_record_ref": second["new_record_ref"],
            "source": {
                "source_type": "manual_entry",
                "actor": "user",
                "excerpt": "That claim was wrong. Remove it.",
            },
        },
    )
    assert third["new_record_ref"] is None
    with session_maker(database_url)() as session:
        old = session.get(Observation, first["new_record_ref"].split(":")[1])
        moved = session.get(Observation, second["new_record_ref"].split(":")[1])
        assert old.subject_entity_id == first_person and old.status == "superseded"
        assert moved.subject_entity_id == other and moved.status == "deleted"
        assert old.valid_to is None and moved.valid_to is None
        assert session.query(MemoryChange).count() == 3
        assert session.query(Episode).count() == 3


def test_request_id_replay_is_stable_and_different_payload_conflicts(client, database_url):
    body = memory(person(client))
    first = write(client, body)
    assert write(client, body) == first
    body["record"]["payload"]["confidence"] = 0.7
    response = client.post("/api/memories", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    with session_maker(database_url)() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(extra=True),
        lambda b: b["source"].update(extra=True),
        lambda b: b["source"].update(source_type="import"),
        lambda b: b["source"].update(source_type="connector"),
        lambda b: b["source"].update(actor="assistant"),
        lambda b: b["source"].update(excerpt="  "),
        lambda b: b["source"].update(excerpt="x" * 4001),
        lambda b: b["record"]["payload"].pop("confidence"),
        lambda b: b["record"]["payload"].pop("claim_basis"),
        lambda b: b["record"]["payload"].update(confidence=1.1),
        lambda b: b["record"]["payload"].update(claim_type="fact"),
        lambda b: b["record"]["payload"].update(ai_use_policy="never_surface"),
        lambda b: b["record"]["payload"].update(confirmation_status="confirmed"),
        lambda b: b["record"]["payload"].update(
            valid_from="2026-01-02T00:00:00Z", valid_to="2026-01-01T00:00:00Z"
        ),
    ],
)
def test_strict_write_contract_rejects_invalid_inputs_without_saving(client, database_url, change):
    body = memory(person(client))
    change(body)
    response = client.post("/api/memories", json=body)
    assert response.status_code == 422, response.text
    with session_maker(database_url)() as session:
        assert (
            session.query(MemoryChange).count()
            == session.query(Episode).count()
            == session.query(Observation).count()
            == 0
        )


@pytest.mark.parametrize(
    "fact_type,content,value",
    [
        ("memo", "context", {"text": "context"}),
        ("email", "a@example.com", {"text": "b@example.com"}),
        ("email", "invalid", {"text": "invalid"}),
        ("birthday", "--02-30", {"month": 2, "day": 30, "precision": "day"}),
        ("birth_date", "--02-28", {"month": 2, "day": 28, "precision": "day"}),
    ],
)
def test_invalid_fact_rolls_back_reserved_receipt_and_source(
    client, database_url, fact_type, content, value
):
    body = memory(person(client))
    body["record"] = {
        "record_type": "entity_facts",
        "payload": {
            "entity_id": body["record"]["payload"]["subject_entity_id"],
            "fact_type": fact_type,
            "content": content,
            "value": value,
            "claim_basis": "reported",
            "confidence": 1,
        },
    }
    assert client.post("/api/memories", json=body).status_code == 422
    with session_maker(database_url)() as session:
        assert (
            session.query(EntityFact).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 0
        )


def test_stale_preconditions_and_accidental_retargeting_do_not_mutate(client, database_url):
    body = memory(person(client))
    first = write(client, body)
    bad = deepcopy(body)
    bad.update(
        request_id="bad-precondition",
        action="correct",
        old_record_ref=first["new_record_ref"],
        expected_updated_at="2001-01-01T00:00:00Z",
    )
    assert client.post("/api/memories", json=bad).status_code == 409
    bad.pop("expected_updated_at")
    bad["record"]["payload"]["subject_entity_id"] = person(client, "Other")
    assert client.post("/api/memories", json=bad).status_code == 422
    retract = {
        "request_id": "retract",
        "action": "retract",
        "old_record_ref": first["new_record_ref"],
        "source": body["source"],
    }
    receipt = write(client, retract)
    assert write(client, retract) == receipt
    retract["request_id"] = "stale-retract"
    assert client.post("/api/memories", json=retract).status_code == 409
    with session_maker(database_url)() as session:
        assert session.query(MemoryChange).count() == 2


def test_failure_rolls_back_source_change_new_record_and_old_status(
    client, database_url, monkeypatch
):
    body = memory(person(client))
    first = write(client, body)
    body.update(request_id="failed", action="correct", old_record_ref=first["new_record_ref"])

    def fail(*args):
        raise RuntimeError("injected evidence failure")

    monkeypatch.setattr(MemoryService, "_link_evidence", fail)
    with pytest.raises(RuntimeError, match="injected"):
        client.post("/api/memories", json=body)
    with session_maker(database_url)() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 1
        )
        assert session.get(Observation, first["new_record_ref"].split(":")[1]).status == "active"


def test_history_links_both_sides_is_bounded_and_excludes_source_snapshot(client):
    body = memory(person(client))
    first = write(client, body)
    body.update(request_id="correct", action="correct", old_record_ref=first["new_record_ref"])
    second = write(client, body)
    response = client.get(
        "/api/memory-changes", params={"record_ref": first["new_record_ref"], "limit": 1}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["id"] == second["change_id"]
    assert len(response.json()["items"]) == 1
    detail = client.get(f"/api/memory-changes/{first['change_id']}")
    assert detail.status_code == 200
    assert "request_sha256" not in detail.json() and "excerpt" not in detail.json()
    assert client.get("/api/memory-changes/no-such-change").status_code == 404
    assert client.get("/api/memory-changes", params={"limit": 101}).status_code == 422
    assert client.get("/api/memory-changes", params={"offset": -1}).status_code == 422
    assert client.get("/api/memory-changes", params={"record_ref": "bad"}).status_code == 422


def concurrent_writes(database_url, bodies):
    barrier = Barrier(len(bodies))
    maker = session_maker(database_url)

    def submit(body):
        with maker() as session:
            barrier.wait(timeout=10)
            try:
                return MemoryService(session).write(MemoryWriteRequest.model_validate(body))
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
        return list(pool.map(submit, bodies))


def test_concurrent_same_request_writes_one_memory(client, database_url):
    body = memory(person(client))
    results = concurrent_writes(database_url, [body, deepcopy(body)])
    assert results[0] == results[1]
    assert isinstance(results[0], dict)
    with session_maker(database_url)() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 1
        )


def test_concurrent_corrections_cannot_replace_the_same_old_record_twice(client, database_url):
    body = memory(person(client))
    first = write(client, body)
    body.update(request_id="correct-a", action="correct", old_record_ref=first["new_record_ref"])
    other = deepcopy(body)
    other["request_id"] = "correct-b"
    results = concurrent_writes(database_url, [body, other])
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    with session_maker(database_url)() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 2
        )


def test_concurrent_conflicting_reuse_of_request_id_returns_one_conflict(client, database_url):
    body = memory(person(client))
    other = deepcopy(body)
    other["record"]["payload"]["content"] = "A different atomic claim."
    results = concurrent_writes(database_url, [body, other])
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    with session_maker(database_url)() as session:
        assert (
            session.query(Observation).count()
            == session.query(Episode).count()
            == session.query(MemoryChange).count()
            == 1
        )


@pytest.mark.parametrize("field", ["occurred_at", "valid_from", "valid_to"])
def test_naive_record_times_require_explicit_timezone(client, field):
    body = memory(person(client))
    body["record"]["payload"][field] = "2026-10-01T10:00:00"
    assert client.post("/api/memories", json=body).status_code == 422


def test_naive_source_and_precondition_times_are_rejected(client):
    body = memory(person(client))
    body["source"]["occurred_at"] = "2026-10-01T10:00:00"
    assert client.post("/api/memories", json=body).status_code == 422
    body["source"].pop("occurred_at")
    first = write(client, body)
    body.update(
        request_id="naive-precondition",
        action="correct",
        old_record_ref=first["new_record_ref"],
        expected_updated_at="2026-10-01T10:00:00",
    )
    assert client.post("/api/memories", json=body).status_code == 422


def test_explicit_offset_times_preserve_the_instant(client, database_url):
    body = memory(person(client))
    body["record"]["payload"]["occurred_at"] = "2026-10-01T09:00:00+09:00"
    body["source"]["occurred_at"] = "2026-10-01T09:00:00+09:00"
    receipt = write(client, body)
    with session_maker(database_url)() as session:
        row = session.get(Observation, receipt["new_record_ref"].split(":")[1])
        episode = session.get(Episode, receipt["source_episode_id"])
        assert row.occurred_at == episode.occurred_at == datetime(2026, 10, 1)


@pytest.mark.parametrize("action", ["correct", "retract", "reattribute"])
def test_disputed_memories_can_be_corrected_retracted_or_reattributed(client, database_url, action):
    body = memory(person(client))
    first = write(client, body)
    with session_maker(database_url)() as session:
        row = session.get(Observation, first["new_record_ref"].split(":")[1])
        row.status = "disputed"
        session.commit()
    body.update(
        request_id="resolve-disputed", action=action, old_record_ref=first["new_record_ref"]
    )
    if action == "retract":
        body.pop("record")
    elif action == "reattribute":
        body["record"]["payload"]["subject_entity_id"] = person(client, "Other")
    receipt = write(client, body)
    assert receipt["action"] == action
    with session_maker(database_url)() as session:
        row = session.get(Observation, first["new_record_ref"].split(":")[1])
        assert row.status == ("deleted" if action == "retract" else "superseded")
