from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import (
    Entity,
    EntityAlias,
    EntityFact,
    EntityFactEvidence,
    Episode,
    MemoryChange,
    Observation,
)
from kinlayer_backend.schemas.memories import MemoryWriteRequest


def person(client, name="Alex"):
    response = client.post("/api/entities", json={"display_name": name, "entity_type": "person"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def body(entity_id, request_id, kind="observations", **fields):
    payload = {"claim_basis": "reported", "confidence": 0.7}
    if kind == "observations":
        payload.update(subject_entity_id=entity_id, observation_type="recent_interaction",
                       content="We discussed a project.")
    elif kind == "entity_facts":
        payload.update(entity_id=entity_id, fact_type="organization", content="Studio",
                       value={"text": "Studio"})
    else:
        payload.update(from_entity_id=entity_id, relation_type="friend", claim_text="We are friends.")
    payload.update(fields)
    return {"request_id": request_id, "record": {"record_type": kind, "payload": payload},
            "source": {"source_type": "manual_entry", "actor": "user",
                       "excerpt": f"Original human source for {request_id}."}}


def write(client, request):
    response = client.post("/api/memories", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def memories(client, **params):
    response = client.get("/api/memories", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def detail(client, ref):
    response = client.get("/api/memories/" + ref.replace(":", "/"))
    assert response.status_code == 200, response.text
    return response.json()


def session_for(database_url):
    return create_session_maker(Settings(database_url=database_url))()


def test_cross_type_pagination_is_stable_and_payloads_are_roundtrip_compatible(client, database_url):
    target, other = person(client), person(client, "Blair")
    inputs = [body(target, "fact", "entity_facts"),
              body(target, "edge", "entity_edges", to_entity_id=other, directed=True,
                   relation_type="reports_to", properties={"context": "team"}),
              body(target, "observation", related_entities=[
                  {"entity_id": other, "role": "speaker", "confidence": 0.9},
                  {"entity_id": other, "role": "experiencer", "confidence": None},
              ])]
    receipts = [write(client, request) for request in inputs]
    with session_for(database_url) as session:
        from kinlayer_backend.services.memories import RECORD_MODELS

        for receipt in receipts:
            kind, record_id = receipt["new_record_ref"].split(":")
            session.get(RECORD_MODELS[kind], record_id).created_at = datetime(2026, 1, 1, tzinfo=UTC)
        session.commit()
    whole = memories(client, entity_id=target)
    assert whole["total"] == 3
    pages = [memories(client, entity_id=target, limit=1, offset=index) for index in range(3)]
    assert all(page["total"] == 3 for page in pages)
    assert [page["items"][0]["record_ref"] for page in pages] == [
        item["record_ref"] for item in whole["items"]
    ]
    assert [item["record_type"] for item in whole["items"]] == [
        "entity_edges", "entity_facts", "observations"
    ]
    for item in whole["items"]:
        assert item["is_current"] is True
        assert item["updated_at"].endswith("Z")
        assert item["sources"][0]["actor"] == "user"
        assert item["sources"][0]["missing"] is False
        MemoryWriteRequest.model_validate({
            "request_id": "roundtrip", "record": {
                "record_type": item["record_type"], "payload": item["payload"],
            }, "source": inputs[0]["source"],
        })
    edge = whole["items"][0]
    assert edge["payload"]["properties"] == {"context": "team"}
    assert edge["payload"]["directed"] is True
    assert [entry["role"] for entry in edge["entities"]] == ["from", "to"]
    assert {entry["role"] for entry in whole["items"][2]["entities"]} == {
        "subject", "speaker", "experiencer"
    }


def test_filters_include_related_participants_and_reverse_sources(client):
    target, speaker = person(client), person(client, "Speaker")
    write(client, body(target, "ordinary"))
    receipt = write(client, body(target, "related", claim_basis="inferred",
                                content="The 100% plan is tentative.", related_entities=[
                                    {"entity_id": speaker, "role": "speaker"}]))
    assert memories(client, entity_id=speaker)["total"] == 1
    result = memories(client, record_type="observations", claim_basis="inferred", q="100%",
                      source_episode_id=receipt["source_episode_id"])
    assert result["total"] == 1
    assert result["items"][0]["record_ref"] == receipt["new_record_ref"]
    assert memories(client, q="100_")["total"] == 0
    assert memories(client, source_episode_id="unknown-source")["total"] == 0
    assert memories(client, claim_basis="unknown")["total"] == 0


def test_history_retains_original_evidence_and_reattribution_scopes_both_owners(client):
    original, destination = person(client), person(client, "Blair")
    request = body(original, "first")
    first = write(client, request)
    moved_request = deepcopy(request)
    moved_request.update(request_id="move", action="reattribute", old_record_ref=first["new_record_ref"])
    moved_request["record"]["payload"]["subject_entity_id"] = destination
    moved_request["source"]["excerpt"] = "I meant Blair, not Alex."
    moved = write(client, moved_request)
    old = detail(client, first["new_record_ref"])
    assert old["status"] == "superseded" and old["is_current"] is False
    assert old["sources"][0]["excerpt"] == request["source"]["excerpt"]
    assert old["sources"][0]["episode_id"] == first["source_episode_id"]
    assert memories(client, entity_id=original)["total"] == 0
    assert memories(client, entity_id=original, status="history")["total"] == 1
    for entity_id, expected_count in [(original, 2), (destination, 1)]:
        history = client.get("/api/memory-changes", params={"entity_id": entity_id, "limit": 1}).json()
        assert history["total"] == expected_count
        assert history["items"][0]["id"] == moved["change_id"]
    retract = write(client, {"request_id": "retract", "action": "retract",
                            "old_record_ref": moved["new_record_ref"], "source": request["source"]})
    assert memories(client, entity_id=destination)["total"] == 0
    assert detail(client, moved["new_record_ref"])["status"] == "deleted"
    assert client.get("/api/memory-changes", params={
        "entity_id": destination, "record_ref": moved["new_record_ref"],
    }).json()["items"][0]["id"] == retract["change_id"]


def test_current_validity_excludes_future_expired_and_retired_claims(client, database_url):
    target = person(client)
    now = datetime.now(UTC)
    write(client, body(target, "current", "entity_facts"))
    write(client, body(target, "future", "entity_facts", valid_from=(now + timedelta(days=1)).isoformat()))
    write(client, body(target, "expired", "entity_facts", valid_to=(now - timedelta(days=1)).isoformat()))
    disputed = write(client, body(target, "disputed"))
    retired = write(client, body(target, "retired"))
    with session_for(database_url) as session:
        session.get(Observation, disputed["new_record_ref"].split(":")[1]).status = "disputed"
        session.get(Observation, retired["new_record_ref"].split(":")[1]).status = "deprecated"
        session.commit()
    assert memories(client, entity_id=target)["total"] == 2
    historical = memories(client, entity_id=target, status="history")
    assert historical["total"] == 3
    assert all(item["is_current"] is False for item in historical["items"])
    assert memories(client, entity_id=target, status="all")["total"] == 5
    summary = client.get("/api/people").json()["items"][0]
    assert summary["memory_count"] == 2
    assert len(summary["profile_facts"]) == 1
    assert "ai_use_policy" not in summary and "confirmation_status" not in summary
    assert "ai_use_policy" not in summary["profile_facts"][0]


def test_unknown_sources_and_legacy_payloads_are_not_fabricated(client):
    target = person(client)
    legacy = client.post("/api/entity-facts", json={
        "entity_id": target, "fact_type": "memo", "content": "Legacy note", "created_by": "user",
    }).json()
    result = detail(client, "entity_facts:" + legacy["id"])
    assert result["claim_basis"] == "unknown"
    assert result["payload"]["value"] is None
    assert result["sources"] == [{"episode_id": None, "source_type": None, "source_ref": None,
                                   "actor": None, "excerpt": None, "occurred_at": None, "missing": True}]


def test_merged_identity_resolves_current_and_former_record_history(client, database_url):
    previous, canonical, newer = person(client, "Old"), person(client, "Canonical"), person(client, "Older")
    old = write(client, body(previous, "old"))
    write(client, body(canonical, "canonical"))
    write(client, body(newer, "older"))
    with session_for(database_url) as session:
        for old_id, target_id in [(previous, canonical), (newer, previous)]:
            entity = session.get(Entity, old_id)
            entity.status = "merged"
            entity.properties = {"merged_entity_ref": "entities:" + target_id}
        session.get(Observation, old["new_record_ref"].split(":")[1]).status = "superseded"
        session.commit()
    for entity_id in (previous, canonical, newer):
        assert memories(client, entity_id=entity_id, status="all")["total"] == 3
        assert client.get("/api/memory-changes", params={"entity_id": entity_id}).json()["total"] == 3
    assert client.get("/api/people").json()["total"] == 1


def test_person_history_includes_identity_and_inactive_alias_migration_receipts(client, database_url):
    target, other = person(client), person(client, "Other")
    memory = write(client, body(target, "current-memory"))
    with session_for(database_url) as session:
        alias = EntityAlias(entity_id=target, alias="Former name", status="deleted", created_by="user")
        session.add(alias)
        session.flush()
        entity_ref, alias_ref, other_ref = (
            "entities:" + target, "entity_aliases:" + alias.id, "entities:" + other,
        )
        migrations = [
            MemoryChange(request_id="identity-migration", old_record_ref=entity_ref,
                         new_record_ref=entity_ref),
            MemoryChange(request_id="alias-old-migration", old_record_ref=alias_ref),
            MemoryChange(request_id="alias-new-migration", new_record_ref=alias_ref),
            MemoryChange(request_id="other-migration", old_record_ref=other_ref,
                         new_record_ref=other_ref),
        ]
        for change in migrations:
            change.request_sha256 = "sha256:" + "0" * 64
            change.change_kind = "migrate"
            change.actor = "system"
            change.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        session.add_all(migrations)
        session.commit()
        expected_ids = {memory["change_id"], *(change.id for change in migrations[:3])}

    whole = client.get("/api/memory-changes", params={"entity_id": target})
    assert whole.status_code == 200, whole.text
    assert whole.json()["total"] == 4
    assert {item["id"] for item in whole.json()["items"]} == expected_ids
    pages = [client.get("/api/memory-changes", params={
        "entity_id": target, "limit": 1, "offset": offset,
    }).json() for offset in range(4)]
    assert all(page["total"] == 4 for page in pages)
    assert [page["items"][0]["id"] for page in pages] == [
        item["id"] for item in whole.json()["items"]
    ]
    for ref, expected_count in [(entity_ref, 1), (alias_ref, 2)]:
        for filters in ({"record_ref": ref}, {"entity_id": target, "record_ref": ref}):
            response = client.get("/api/memory-changes", params=filters)
            assert response.status_code == 200, response.text
            assert response.json()["total"] == expected_count
            assert all(item["source_episode_id"] is None for item in response.json()["items"])
        assert client.get("/api/memory-changes", params={
            "entity_id": other, "record_ref": ref,
        }).json()["total"] == 0
    # The wider read filter does not make identities/aliases writable memories.
    for ref in (entity_ref, alias_ref):
        request = {"request_id": "unsupported-retract-" + ref, "action": "retract",
                   "old_record_ref": ref, "source": body(target, "source")["source"]}
        assert client.post("/api/memories", json=request).status_code == 422
    assert client.get("/api/memory-changes").json()["total"] == 5


def test_identity_and_alias_history_filter_includes_complete_merged_lineage(client, database_url):
    oldest, previous, canonical, unrelated = [person(client, name) for name in (
        "Oldest", "Previous", "Canonical", "Unrelated",
    )]
    memory = write(client, body(canonical, "canonical-memory"))
    with session_for(database_url) as session:
        for old_id, target_id in ((oldest, previous), (previous, canonical)):
            entity = session.get(Entity, old_id)
            entity.status = "merged"
            entity.properties = {"merged_entity_ref": "entities:" + target_id}
        expected_ids = {memory["change_id"]}
        for entity_id in (oldest, previous, canonical, unrelated):
            alias = EntityAlias(entity_id=entity_id, alias="Historical alias",
                                status="deprecated", created_by="user")
            session.add(alias)
            session.flush()
            for kind, record_id in (("entities", entity_id), ("entity_aliases", alias.id)):
                change = MemoryChange(
                    request_id=f"migrate-{kind}-{record_id}", request_sha256="sha256:" + "0" * 64,
                    change_kind="migrate", actor="system", old_record_ref=f"{kind}:{record_id}",
                    new_record_ref=f"{kind}:{record_id}",
                )
                session.add(change)
                session.flush()
                if entity_id != unrelated:
                    expected_ids.add(change.id)
        session.commit()
    for entity_id in (oldest, previous, canonical):
        response = client.get("/api/memory-changes", params={"entity_id": entity_id})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 7
        assert {item["id"] for item in response.json()["items"]} == expected_ids
    assert client.get("/api/memory-changes", params={"entity_id": unrelated}).json()["total"] == 2


def test_change_reference_filter_accepts_only_known_read_kinds(client):
    for kind in ("entities", "entity_aliases", "entity_facts", "entity_edges", "observations"):
        response = client.get("/api/memory-changes", params={"record_ref": kind + ":missing"})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0
    for ref in ("", "entities", "entities:", "entity_aliases:", "candidates:missing", "unknown:missing"):
        assert client.get("/api/memory-changes", params={"record_ref": ref}).status_code == 422
    assert client.get("/api/memories/entities/missing").status_code == 422
    assert client.get("/api/memories/entity_aliases/missing").status_code == 422


def test_people_filter_sort_and_totals_apply_before_pagination(client, database_url):
    self_id = client.post("/api/entities", json={
        "display_name": "Me", "system_role": "self", "created_by": "system",
    }).json()["id"]
    first, last, outsider = person(client, "A first"), person(client, "Z last"), person(client, "Other")
    client.post(f"/api/entities/{last}/aliases", json={"alias": "Zed"})
    write(client, body(self_id, "friend-first", "entity_edges", to_entity_id=first))
    write(client, body(self_id, "friend-last", "entity_edges", to_entity_id=last))
    write(client, body(outsider, "unrelated-edge", "entity_edges", to_entity_id=last,
                       relation_type="coworker"))
    write(client, body(self_id, "future-edge", "entity_edges", to_entity_id=outsider,
                       valid_from="2099-01-01T00:00:00Z"))
    write(client, body(last, "related-once", related_entities=[
        {"entity_id": last, "role": "speaker"}, {"entity_id": last, "role": "about"}]))
    with session_for(database_url) as session:
        session.get(Entity, last).last_referenced_at = datetime(2026, 10, 1, tzinfo=UTC)
        session.get(Entity, first).last_referenced_at = datetime(2026, 1, 1, tzinfo=UTC)
        session.commit()
    params = {"relation_type": "friend", "sort": "recent_reference", "limit": 1}
    response = client.get("/api/people", params=params)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == 2 and result["items"][0]["id"] == last
    assert result["items"][0]["aliases"] == ["Zed"]
    assert result["items"][0]["memory_count"] == 3
    assert [r["relation_type"] for r in result["items"][0]["relations"]] == ["friend"]
    assert client.get("/api/people", params={**params, "offset": 1}).json()["items"][0]["id"] == first
    assert client.get("/api/people", params={"relation_type": "coworker"}).json()["total"] == 0
    assert client.get("/api/people", params={"q": "zed"}).json()["total"] == 1
    assert client.get("/api/people", params={"exclude_self": False}).json()["total"] == 4
    entities = client.get("/api/entities", params=params)
    assert entities.status_code == 200, entities.text
    assert entities.json()["items"][0]["id"] == last and entities.json()["total"] == 2


def test_read_validation_and_unknown_records(client):
    assert client.get("/api/memories", params={"status": "pending"}).status_code == 422
    assert client.get("/api/memories", params={"record_type": "candidates"}).status_code == 422
    assert client.get("/api/memories", params={"limit": 201}).status_code == 422
    assert client.get("/api/memories", params={"entity_id": "missing"}).status_code == 404
    assert client.get("/api/memories/entity_facts/missing").status_code == 404
    assert client.get("/api/memories/invalid/missing").status_code == 422
    assert client.get("/api/people", params={"sort": "random"}).status_code == 422


def test_current_graph_card_and_search_share_memory_validity(client):
    target, focal = person(client, "Alex"), person(client, "Me")
    now = datetime.now(UTC)
    current_refs, historical_refs = set(), set()
    for kind in ("entity_facts", "entity_edges", "observations"):
        for phase, validity in (
            ("current", {}),
            ("future", {"valid_from": (now + timedelta(days=1)).isoformat()}),
            ("expired", {"valid_to": (now - timedelta(days=1)).isoformat()}),
        ):
            fields = {**validity}
            if kind == "entity_edges":
                fields.update(to_entity_id=target)
            request = body(focal if kind == "entity_edges" else target, f"{kind}-{phase}",
                           kind, **fields)
            receipt = write(client, request)
            (current_refs if phase == "current" else historical_refs).add(receipt["new_record_ref"])
    graph = client.get(f"/api/graph/ego/{focal}").json()
    assert {"entity_edges:" + edge["edge_id"] for edge in graph["edges"]} == {
        ref for ref in current_refs if ref.startswith("entity_edges:")
    }
    card = client.get(f"/api/entities/{target}/context-card").json()
    assert {"entity_facts:" + fact["id"] for fact in card["profile_facts"]} == {
        ref for ref in current_refs if ref.startswith("entity_facts:")
    }
    assert {"entity_edges:" + edge["id"] for edge in card["relationship_edges"]} == {
        ref for ref in current_refs if ref.startswith("entity_edges:")
    }
    assert {"observations:" + observation["id"] for observation in card["recent_context"]} == {
        ref for ref in current_refs if ref.startswith("observations:")
    }
    current_ids = {ref.split(":")[1] for ref in current_refs}
    assert {entry["record_id"] for entry in card["provenance_summary"]["evidence"]} == current_ids
    for endpoint in ("retrieve", "pack"):
        response = client.post(f"/api/context/{endpoint}", json={
            "query": "We discussed a project.", "entity_hints": [target], "focal_entity_id": focal,
        })
        assert response.status_code == 200, response.text
        payload = response.json() if endpoint == "retrieve" else response.json()["context_pack"]
        observations = payload["observations" if endpoint == "retrieve" else "recent_context"]
        assert {"observations:" + item["observation_id"] for item in observations} == {
            ref for ref in current_refs if ref.startswith("observations:")
        }
        facts = [fact for match in payload["matched_entities"] for fact in match["profile_facts"]]
        assert {"entity_facts:" + item["id"] for item in facts} == {
            ref for ref in current_refs if ref.startswith("entity_facts:")
        }
        assert not {ref.split(":")[1] for ref in historical_refs}.intersection(
            entry["record_id"] for entry in payload["provenance"]
        )
    assert {item["record_ref"] for item in memories(client, entity_id=target)["items"]} == current_refs
    assert {item["record_ref"] for item in memories(client, entity_id=target, status="history")["items"]} == historical_refs


def test_directory_and_memory_reads_batch_hydration_without_per_row_queries(client):
    with client.app.state.session_factory() as session:
        for index in range(25):
            entity = Entity(entity_type="person", display_name=f"Person {index:02}",
                            canonical_name=f"person {index:02}", created_by="user")
            session.add(entity)
            session.flush()
            session.add(EntityFact(entity_id=entity.id, fact_type="organization", content="Studio",
                                   value={"text": "Studio"}, claim_type="fact", created_by="user"))
        session.commit()
    engine = client.app.state.session_factory.kw["bind"]
    counts = []

    def record_query(*_args):
        counts.append(1)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        for endpoint in ("/api/people", "/api/memories"):
            counts.clear()
            small = client.get(endpoint, params={"limit": 1})
            small_count = len(counts)
            counts.clear()
            large = client.get(endpoint, params={"limit": 25})
            assert small.status_code == large.status_code == 200
            assert small.json()["total"] == large.json()["total"] == 25
            assert len(large.json()["items"]) == 25
            assert len(counts) == small_count
    finally:
        event.remove(engine, "before_cursor_execute", record_query)


def test_inspection_respects_local_token_authentication(client, database_url):
    with TestClient(create_app({"database_url": database_url, "api_token": "test-only-token"})) as secured:
        for path in ("/api/people", "/api/memories", "/api/memory-changes"):
            assert secured.get(path).status_code == 401
            response = secured.get(path, headers={"Authorization": "Bearer test-only-token"})
            assert response.status_code == 200, response.text


def test_legacy_original_source_excerpt_and_unknown_time_are_preserved(client):
    target = person(client)
    with client.app.state.session_factory() as session:
        fact = EntityFact(entity_id=target, fact_type="memo", content="  Legacy words  ",
                          claim_type="fact", status="superseded", created_by="user")
        source = Episode(source_type="manual_entry", actor="Original human author",
                         body_excerpt="  Exact original source\n", body_hash="historical-hash")
        session.add_all([fact, source])
        session.flush()
        session.add(EntityFactEvidence(entity_fact_id=fact.id, episode_id=source.id, excerpt=None))
        session.commit()
        ref = "entity_facts:" + fact.id
    item = detail(client, ref)
    assert item["content"] == "  Legacy words  "
    assert item["payload"]["content"] == "  Legacy words  "
    assert item["sources"][0]["excerpt"] == "  Exact original source\n"
    assert item["sources"][0]["occurred_at"] is None
    assert item["sources"][0]["actor"] == "Original human author"
