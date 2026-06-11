from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine, create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base, OntologyRegistryValue


def create_person(client, name: str, sensitivity: str = "medium") -> dict:
    response = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": name,
            "sensitivity": sensitivity,
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_edge(
    client,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    sensitivity: str = "medium",
) -> dict:
    response = client.post(
        "/api/edges",
        json={
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "relation_type": relation_type,
            "claim_text": f"{relation_type} edge",
            "claim_type": "fact",
            "sensitivity": sensitivity,
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_ego_graph_returns_generic_depth_one_nodes_edges_and_filters(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex", sensitivity="low")
    dana = create_person(client, "Dana", sensitivity="high")
    client_contact = create_edge(client, user["id"], alex["id"], "client_contact", sensitivity="low")
    create_edge(client, user["id"], dana["id"], "former_coworker", sensitivity="high")

    graph = client.get(
        f"/api/graph/ego/{user['id']}",
        params={"depth": 1, "relation_type": "client_contact", "sensitivity": "low"},
    )

    assert graph.status_code == 200
    body = graph.json()
    assert body["focal_entity_id"] == user["id"]
    assert body["depth"] == 1
    assert body["filters_applied"]["relation_type"] == "client_contact"
    assert body["filters_applied"]["sensitivity"] == "low"
    node_ids = {node["entity_id"] for node in body["nodes"]}
    assert node_ids == {user["id"], alex["id"]}
    assert [node for node in body["nodes"] if node["is_focal"]][0]["entity_id"] == user["id"]
    assert body["edges"] == [
        {
            "edge_id": client_contact["id"],
            "from_entity_id": user["id"],
            "to_entity_id": alex["id"],
            "relation_type": "client_contact",
            "directed": client_contact["directed"],
            "status": "active",
            "confidence": client_contact["confidence"],
            "sensitivity": "low",
        }
    ]
    assert "source" not in body["edges"][0]
    assert "target" not in body["edges"][0]

    unsupported_depth = client.get(f"/api/graph/ego/{user['id']}", params={"depth": 2})
    assert unsupported_depth.status_code == 422
    assert unsupported_depth.json()["error"]["code"] == "validation_error"


def test_ego_graph_status_filter_excludes_deleted_by_default(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    deleted = create_edge(client, user["id"], alex["id"], "client_contact")
    delete_response = client.delete(f"/api/edges/{deleted['id']}")
    assert delete_response.status_code == 200

    default_graph = client.get(f"/api/graph/ego/{user['id']}")
    assert default_graph.status_code == 200
    assert default_graph.json()["edges"] == []

    deleted_graph = client.get(f"/api/graph/ego/{user['id']}", params={"status": "deleted"})
    assert deleted_graph.status_code == 200
    assert deleted_graph.json()["edges"][0]["edge_id"] == deleted["id"]


def test_ego_graph_missing_focal_returns_common_not_found(client) -> None:
    response = client.get("/api/graph/ego/missing-entity")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_ontology_read_endpoints_return_seed_registries(client) -> None:
    all_ontology = client.get("/api/ontology")
    assert all_ontology.status_code == 200
    body = all_ontology.json()
    assert "entity_types" in body
    assert "edge_types" in body
    assert "observation_types" in body
    assert "fact_types" in body
    assert "policies" in body
    assert any(item["value"] == "person" for item in body["entity_types"])
    assert any(item["relation_type"] == "client_contact" for item in body["edge_types"])
    assert any(
        item["observation_type"] == "recent_interaction"
        for item in body["observation_types"]
    )
    assert any(item["value"] == "organization" for item in body["fact_types"])
    assert "ai_use_policies" in body["policies"]
    assert "sensitivity_levels" in body["policies"]

    assert client.get("/api/ontology/edge-types").json()["items"]
    assert client.get("/api/ontology/observation-types").json()["items"]
    assert client.get("/api/ontology/entity-fact-types").json()["items"]
    assert client.get("/api/ontology/policies").json()["ai_use_policies"]


def test_ontology_excludes_inactive_registry_values(database_url) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_maker(Settings(database_url=database_url))
    with session_factory() as session:
        session.add(
            OntologyRegistryValue(
                category="fact_type",
                value="inactive_fact",
                label="Inactive fact",
                support_level="supported",
                is_active=False,
                sort_order=999,
            )
        )
        session.commit()

    with TestClient(create_app({"database_url": database_url})) as test_client:
        response = test_client.get("/api/ontology/entity-fact-types")

    assert response.status_code == 200
    values = {item["value"] for item in response.json()["items"]}
    assert "inactive_fact" not in values


def test_graph_and_ontology_obey_optional_api_token(database_url) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    with TestClient(
        create_app({"database_url": database_url, "api_token": "secret-token"})
    ) as authed_client:
        entity_response = authed_client.post(
            "/api/entities",
            json={
                "entity_type": "person",
                "display_name": "Token User",
                "created_by": "user",
            },
            headers={"Authorization": "Bearer secret-token"},
        )
        assert entity_response.status_code == 201

        unauthorized_ontology = authed_client.get("/api/ontology")
        assert unauthorized_ontology.status_code == 401
        authorized_ontology = authed_client.get(
            "/api/ontology",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert authorized_ontology.status_code == 200

        unauthorized_graph = authed_client.get(
            f"/api/graph/ego/{entity_response.json()['id']}",
        )
        assert unauthorized_graph.status_code == 401
        authorized_graph = authed_client.get(
            f"/api/graph/ego/{entity_response.json()['id']}",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert authorized_graph.status_code == 200
