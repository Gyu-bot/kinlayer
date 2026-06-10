from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kinlayer_backend.config import Settings
from kinlayer_backend.database import check_database

PUBLIC_PATHS = {"/api/system/health", "/api/system/version"}


def error_response(status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def create_app(overrides: dict[str, Any] | None = None) -> FastAPI:
    settings = Settings.from_overrides(overrides)
    app = FastAPI(title="Kinlayer", version="0.1.0")
    app.state.settings = settings

    @app.middleware("http")
    async def optional_token_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ):
        if settings.api_token and request.url.path not in PUBLIC_PATHS:
            expected = f"Bearer {settings.api_token}"
            if request.headers.get("authorization") != expected:
                return error_response(401, "unauthorized", "Bearer API token is required.")
        return await call_next(request)

    @app.get("/api/system/health")
    def health() -> dict[str, str]:
        database_status = check_database(settings)
        return {
            "status": "ok" if database_status == "ok" else "degraded",
            "database": database_status,
            "embedding": "disabled",
        }

    @app.get("/api/system/version")
    def version() -> dict[str, str]:
        return {"name": "kinlayer", "version": "0.1.0", "api_version": "v1"}

    @app.get("/api/system/config")
    def config() -> dict[str, Any]:
        return {
            "bind_host": settings.bind_host,
            "auth_token_configured": bool(settings.api_token),
            "embedding": {
                "provider": settings.embedding_provider or "disabled",
                "model": settings.embedding_model,
                "dim": settings.embedding_dim,
                "status": "disabled",
            },
        }

    return app


app = create_app()
