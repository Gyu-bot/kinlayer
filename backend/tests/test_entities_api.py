def test_entity_alias_and_fact_lifecycle(client) -> None:
    created = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "Alex Kim",
            "canonical_name": "alex kim",
            "properties": {"short_note": "Met through work"},
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    assert created.status_code == 201
    entity = created.json()
    assert entity["display_name"] == "Alex Kim"
    assert entity["status"] == "active"

    listed = client.get("/api/entities", params={"q": "alex"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == entity["id"]

    alias = client.post(
        f"/api/entities/{entity['id']}/aliases",
        json={"alias": "알렉스", "created_by": "user"},
    )
    assert alias.status_code == 201
    alias_body = alias.json()
    assert alias_body["normalized_alias"] == "알렉스"

    aliases = client.get(f"/api/entities/{entity['id']}/aliases")
    assert aliases.status_code == 200
    assert aliases.json()["items"][0]["alias"] == "알렉스"

    deleted_alias = client.delete(f"/api/aliases/{alias_body['id']}")
    assert deleted_alias.status_code == 200
    assert deleted_alias.json()["status"] == "deleted"

    aliases_after_delete = client.get(f"/api/entities/{entity['id']}/aliases")
    assert aliases_after_delete.status_code == 200
    assert aliases_after_delete.json()["items"] == []
    assert aliases_after_delete.json()["total"] == 0

    fact = client.post(
        "/api/entity-facts",
        json={
            "entity_id": entity["id"],
            "fact_type": "organization",
            "content": "Example Corp",
            "claim_type": "fact",
            "confidence": 0.95,
            "sensitivity": "low",
            "ai_use_policy": "freely_use",
            "created_by": "user",
        },
    )
    assert fact.status_code == 201
    fact_body = fact.json()
    assert fact_body["fact_type"] == "organization"

    invalid_fact = client.post(
        "/api/entity-facts",
        json={
            "entity_id": entity["id"],
            "fact_type": "unsupported_fact",
            "content": "Nope",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert invalid_fact.status_code == 422
    assert invalid_fact.json()["error"]["code"] == "validation_error"

    patched = client.patch(f"/api/entities/{entity['id']}", json={"display_name": "Alex Park"})
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Alex Park"

    deleted = client.delete(f"/api/entities/{entity['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    default_list = client.get("/api/entities", params={"entity_type": "person"})
    assert default_list.status_code == 200
    assert default_list.json()["total"] == 0

    deleted_list = client.get(
        "/api/entities",
        params={"entity_type": "person", "status": "deleted"},
    )
    assert deleted_list.status_code == 200
    assert deleted_list.json()["total"] == 1


def test_structured_profile_fact_types_are_validated_and_visible_in_context_card(client) -> None:
    person = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Alex Kim", "created_by": "user"},
    ).json()

    ontology = client.get("/api/ontology")
    assert ontology.status_code == 200
    fact_types = {item["value"] for item in ontology.json()["fact_types"]}
    assert {
        "legal_name",
        "birth_date",
        "phone",
        "email",
        "address",
        "organization",
        "role",
        "memo",
    }.issubset(fact_types)

    created = client.post(
        "/api/entity-facts",
        json={
            "entity_id": person["id"],
            "fact_type": "email",
            "content": "alex@example.com",
            "value": {"kind": "work", "email": "alex@example.com"},
            "claim_type": "fact",
            "confidence": 0.87,
            "sensitivity": "high",
            "ai_use_policy": "ask_before_use",
            "created_by": "user",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["fact_type"] == "email"
    assert body["value"] == {"kind": "work", "email": "alex@example.com"}
    assert body["sensitivity"] == "high"
    assert body["ai_use_policy"] == "ask_before_use"

    invalid = client.post(
        "/api/entity-facts",
        json={
            "entity_id": person["id"],
            "fact_type": "unsupported_contact",
            "content": "Nope",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    context_card = client.get(f"/api/entities/{person['id']}/context-card")
    assert context_card.status_code == 200
    assert [fact["id"] for fact in context_card.json()["profile_facts"]] == [body["id"]]


def test_controlled_values_use_common_validation_error(client) -> None:
    response = client.post(
        "/api/entities",
        json={
            "entity_type": "unsupported",
            "display_name": "Invalid",
            "created_by": "user",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_entity_canonical_name_is_normalized_server_side(client) -> None:
    created = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "  Alex   Kim  ",
            "canonical_name": "  alex   kim  ",
            "created_by": "user",
        },
    )
    assert created.status_code == 201
    assert created.json()["canonical_name"] == "alex kim"

    listed = client.get("/api/entities", params={"q": "Alex Kim"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_protected_self_is_unique_and_cannot_be_mutated(client) -> None:
    first = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "Me",
            "canonical_name": "me",
            "created_by": "system",
            "system_role": "self",
            "is_system": True,
        },
    )
    assert first.status_code == 201
    self_entity = first.json()

    duplicate = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "Duplicate Me",
            "created_by": "system",
            "system_role": "self",
            "is_system": True,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    remove_role = client.patch(self_entity["id"].join(("/api/entities/", "")), json={"system_role": None})
    assert remove_role.status_code == 403
    assert remove_role.json()["error"]["code"] == "forbidden"

    delete = client.delete(f"/api/entities/{self_entity['id']}")
    assert delete.status_code == 403
    assert delete.json()["error"]["code"] == "forbidden"


def test_agent_entity_resolve_returns_no_match_and_single_alias_match(client) -> None:
    person = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Alex Kim", "created_by": "user"},
    ).json()
    alias = client.post(
        f"/api/entities/{person['id']}/aliases",
        json={"alias": "알렉스", "created_by": "user"},
    )
    assert alias.status_code == 201

    no_match = client.post(
        "/api/entities/resolve",
        json={"surface": "Minji", "entity_type": "person", "source": {"kind": "agent"}},
    )
    assert no_match.status_code == 200
    assert no_match.json()["ambiguity"] == "no_match"
    assert no_match.json()["matches"] == []

    resolved = client.post(
        "/api/entities/resolve",
        json={"surface": "알렉스", "entity_type": "person", "source": {"kind": "agent"}},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["ambiguity"] == "single_strong_match"
    assert body["matches"][0]["entity_id"] == person["id"]
    assert body["matches"][0]["display_name"] == "Alex Kim"
    assert body["matches"][0]["score"] > 0.8
    assert "exact_alias" in body["matches"][0]["match_reasons"]


def test_agent_entity_resolve_reports_ambiguity_and_excludes_self_by_default(client) -> None:
    self_entity = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "Me",
            "created_by": "system",
            "system_role": "self",
            "is_system": True,
        },
    ).json()
    alex = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Alex Kim", "created_by": "user"},
    ).json()
    alexa = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Alexa Kim", "created_by": "user"},
    ).json()

    ambiguous = client.post(
        "/api/entities/resolve",
        json={"surface": "Alex", "entity_type": "person", "source": {"kind": "agent"}},
    )
    assert ambiguous.status_code == 200
    body = ambiguous.json()
    assert body["ambiguity"] == "multiple_close_matches"
    assert {match["entity_id"] for match in body["matches"][:2]} == {alex["id"], alexa["id"]}

    excluded_self = client.post(
        "/api/entities/resolve",
        json={"surface": "Me", "entity_type": "person", "source": {"kind": "agent"}},
    )
    assert excluded_self.status_code == 200
    assert excluded_self.json()["matches"] == []

    requested_self = client.post(
        "/api/entities/resolve",
        json={
            "surface": "Me",
            "entity_type": "person",
            "source": {"kind": "agent", "system_role": "self"},
        },
    )
    assert requested_self.status_code == 200
    assert requested_self.json()["matches"][0]["entity_id"] == self_entity["id"]


def test_entity_resolve_is_token_protected(database_url) -> None:
    from fastapi.testclient import TestClient

    from kinlayer_backend.main import create_app

    with TestClient(create_app({"database_url": database_url, "api_token": "secret"})) as client:
        response = client.post("/api/entities/resolve", json={"surface": "Alex"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
