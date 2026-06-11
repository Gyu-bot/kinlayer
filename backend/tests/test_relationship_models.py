from sqlalchemy import inspect

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.models import Base


def test_relationship_observation_tables_exist_in_metadata(database_url: str) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    for table in [
        "allowed_edge_types",
        "allowed_observation_types",
        "entity_edges",
        "observations",
        "observation_entities",
        "episodes",
        "entity_fact_evidence",
        "edge_evidence",
        "observation_evidence",
    ]:
        assert inspector.has_table(table)


def test_observation_model_includes_embedding_fields(database_url: str) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("observations")}

    for column in [
        "embedding",
        "embedding_status",
        "embedding_error",
        "embedding_model",
        "embedding_dim",
        "embedding_created_at",
        "ingested_at",
    ]:
        if column == "ingested_at":
            episode_columns = {
                item["name"] for item in inspect(engine).get_columns("episodes")
            }
            assert column in episode_columns
        else:
            assert column in columns
