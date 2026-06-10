import json
import subprocess
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn

from kinlayer_backend.config import Settings

app = typer.Typer(help="Kinlayer local-first relationship context CLI.")


def _headers(settings: Settings) -> dict[str, str]:
    if not settings.api_token:
        return {}
    return {"Authorization": f"Bearer {settings.api_token}"}


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
) -> None:
    uvicorn.run("kinlayer_backend.main:app", host=host, port=port, reload=False)


@app.command()
def migrate() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.command()
def status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    settings = Settings()
    payload: dict[str, object] = {
        "api_url": settings.api_url,
        "api": "unknown",
        "database": "unknown",
        "embedding": "unknown",
    }

    try:
        response = httpx.get(
            f"{settings.api_url.rstrip('/')}/api/system/health",
            headers=_headers(settings),
            timeout=5,
        )
        payload["api"] = "ok" if response.status_code == 200 else f"http_{response.status_code}"
        if response.status_code == 200:
            body = response.json()
            payload["database"] = body.get("database", "unknown")
            payload["embedding"] = body.get("embedding", "unknown")
    except httpx.HTTPError as exc:
        payload["api"] = "error"
        payload["error"] = str(exc)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(f"API: {payload['api']} ({payload['api_url']})")
    typer.echo(f"Database: {payload['database']}")
    typer.echo(f"Embedding: {payload['embedding']}")


@app.command()
def init() -> None:
    env_example = Path(".env.example")
    typer.echo("Kinlayer config defaults are documented in .env.example.")
    if not env_example.exists():
        typer.echo("Warning: .env.example is missing.")


if __name__ == "__main__":
    app()
