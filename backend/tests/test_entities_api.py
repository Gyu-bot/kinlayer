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
