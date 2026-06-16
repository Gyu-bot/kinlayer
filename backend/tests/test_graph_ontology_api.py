from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine, create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base, EntityEdge, OntologyRegistryValue


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


def test_ego_graph_excludes_invalid_legacy_edge_types(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    organization = client.post(
        "/api/entities",
        json={"entity_type": "organization", "display_name": "Acme", "created_by": "user"},
    ).json()
    valid = create_edge(client, user["id"], alex["id"], "client_contact")
    with client.app.state.session_factory() as session:
        session.add(
            EntityEdge(
                from_entity_id=user["id"],
                to_entity_id=alex["id"],
                relation_type="reply_strategy",
                claim_text="Legacy invalid edge.",
                claim_type="fact",
                created_by="ai_agent",
            )
        )
        session.add(
            EntityEdge(
                from_entity_id=user["id"],
                to_entity_id=organization["id"],
                relation_type="client_contact",
                claim_text="Legacy endpoint mismatch edge.",
                claim_type="fact",
                created_by="ai_agent",
            )
        )
        session.commit()

    graph = client.get(f"/api/graph/ego/{user['id']}")

    assert graph.status_code == 200
    assert [edge["edge_id"] for edge in graph.json()["edges"]] == [valid["id"]]


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


def test_edge_type_diagnostics_reports_invalid_legacy_rows(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    organization = client.post(
        "/api/entities",
        json={"entity_type": "organization", "display_name": "Acme", "created_by": "user"},
    ).json()
    create_edge(client, user["id"], alex["id"], "client_contact")
    with client.app.state.session_factory() as session:
        invalid_edge = EntityEdge(
            from_entity_id=user["id"],
            to_entity_id=alex["id"],
            relation_type="reply_strategy",
            claim_text="Legacy invalid edge.",
            claim_type="fact",
            created_by="ai_agent",
            source_candidate_id="candidate-legacy",
        )
        session.add(invalid_edge)
        mismatch_edge = EntityEdge(
            from_entity_id=user["id"],
            to_entity_id=organization["id"],
            relation_type="client_contact",
            claim_text="Legacy endpoint mismatch edge.",
            claim_type="fact",
            created_by="ai_agent",
        )
        session.add(mismatch_edge)
        session.commit()
        invalid_edge_id = invalid_edge.id
        mismatch_edge_id = mismatch_edge.id

    response = client.get("/api/ontology/edge-type-diagnostics")

    assert response.status_code == 200
    body = response.json()
    relation_types = {item["relation_type"]: item for item in body["relation_types"]}
    assert relation_types["client_contact"]["exists_in_allowed_edge_types"] is True
    assert relation_types["reply_strategy"]["exists_in_allowed_edge_types"] is False
    assert relation_types["reply_strategy"]["active_edge_count"] == 1

    invalid_edges = {item["edge_id"]: item for item in body["invalid_edges"]}
    assert invalid_edges[invalid_edge_id]["relation_type"] == "reply_strategy"
    assert invalid_edges[invalid_edge_id]["edge_type_match"] == "missing_allowed_edge_type"
    assert invalid_edges[invalid_edge_id]["from_entity_type"] == "person"
    assert invalid_edges[invalid_edge_id]["to_entity_type"] == "person"
    assert invalid_edges[invalid_edge_id]["status"] == "active"
    assert invalid_edges[invalid_edge_id]["created_by"] == "ai_agent"
    assert invalid_edges[invalid_edge_id]["source_candidate_id"] == "candidate-legacy"
    assert invalid_edges[mismatch_edge_id]["relation_type"] == "client_contact"
    assert invalid_edges[mismatch_edge_id]["edge_type_match"] == "endpoint_type_mismatch"
    assert invalid_edges[mismatch_edge_id]["to_entity_type"] == "organization"


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
