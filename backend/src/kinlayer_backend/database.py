from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from kinlayer_backend.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def create_session_maker(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(settings), autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Session:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session


def check_database(settings: Settings) -> str:
    try:
        engine = create_db_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        return "ok"
    except SQLAlchemyError:
        return "error"
