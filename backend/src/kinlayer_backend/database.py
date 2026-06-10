from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from kinlayer_backend.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def check_database(settings: Settings) -> str:
    try:
        engine = create_db_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        return "ok"
    except SQLAlchemyError:
        return "error"
