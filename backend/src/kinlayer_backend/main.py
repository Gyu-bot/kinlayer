from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from kinlayer_backend.api.candidates import router as candidates_router
from kinlayer_backend.api.context import router as context_router
from kinlayer_backend.api.corrections import router as corrections_router
from kinlayer_backend.api.embeddings import router as embeddings_router
from kinlayer_backend.api.entities import router as entities_router
from kinlayer_backend.api.graph import router as graph_router
from kinlayer_backend.api.ontology import router as ontology_router
from kinlayer_backend.api.errors import (
    error_response,
    http_exception_handler,
    validation_exception_handler,
)
from kinlayer_backend.api.system import router as system_router
from kinlayer_backend.api.relationships import router as relationships_router
from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.services.ontology import seed_ontology_values

PUBLIC_PATHS = {"/api/system/health", "/api/system/version"}


def create_app(overrides: dict[str, Any] | None = None) -> FastAPI:
    settings = Settings.from_overrides(overrides)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with app.state.session_factory() as session:
            if inspect(session.get_bind()).has_table("ontology_registry_values"):
                seed_ontology_values(session)
        yield

    app = FastAPI(title="Kinlayer", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = create_session_maker(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.middleware("http")
    async def optional_token_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ):
        if (
            settings.api_token
            and request.method != "OPTIONS"
            and request.url.path not in PUBLIC_PATHS
        ):
            expected = f"Bearer {settings.api_token}"
            if request.headers.get("authorization") != expected:
                return error_response(401, "unauthorized", "Bearer API token is required.")
        return await call_next(request)

    app.include_router(system_router)
    app.include_router(entities_router)
    app.include_router(relationships_router)
    app.include_router(embeddings_router)
    app.include_router(candidates_router)
    app.include_router(corrections_router)
    app.include_router(context_router)
    app.include_router(graph_router)
    app.include_router(ontology_router)

    return app


app = create_app()
