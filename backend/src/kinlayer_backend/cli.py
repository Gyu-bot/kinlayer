import json
import subprocess
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
import uvicorn

from kinlayer_backend.config import Settings

app = typer.Typer(help="Kinlayer local-first relationship context CLI.")
person_app = typer.Typer(help="Create and inspect person entities.")
embedding_app = typer.Typer(help="Inspect and backfill observation embeddings.")
candidate_app = typer.Typer(help="Submit and resolve candidate records.")
correction_app = typer.Typer(help="Apply explicit corrections.")
context_app = typer.Typer(help="Retrieve and package context.")
debug_app = typer.Typer(help="Inspect retrieval internals.")
graph_app = typer.Typer(help="Inspect relationship graph views.")
app.add_typer(person_app, name="person")
app.add_typer(embedding_app, name="embedding")
app.add_typer(candidate_app, name="candidate")
app.add_typer(correction_app, name="correction")
app.add_typer(context_app, name="context")
app.add_typer(debug_app, name="debug")
app.add_typer(graph_app, name="graph")


def _headers(settings: Settings) -> dict[str, str]:
    if not settings.api_token:
        return {}
    return {"Authorization": f"Bearer {settings.api_token}"}


def _api_url(settings: Settings, path: str) -> str:
    return f"{settings.api_url.rstrip('/')}/{path.lstrip('/')}"


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> httpx.Response:
    settings = Settings()
    url = _api_url(settings, path)
    headers = _headers(settings)
    if method == "GET":
        return httpx.get(url, headers=headers, timeout=5)
    if method == "POST":
        return httpx.post(url, headers=headers, json=payload, timeout=5)
    if method == "PATCH":
        return httpx.patch(url, headers=headers, json=payload, timeout=5)
    if method == "DELETE":
        return httpx.delete(url, headers=headers, timeout=5)
    raise typer.BadParameter(f"Unsupported method: {method}")


def _emit(payload: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return
    typer.echo(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))


def _raise_for_api(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": {"message": response.text}}
    error = payload.get("error", {})
    raise typer.BadParameter(error.get("message", f"HTTP {response.status_code}"))


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise typer.BadParameter(f"Cannot read JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("JSON file must contain an object.")
    return payload


def _context_payload(
    query: str,
    entity_hints: list[str] | None = None,
    focal_entity_id: str | None = None,
    include_debug: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "entity_hints": entity_hints or [],
        "include_debug": include_debug,
        "limit": limit,
    }
    if focal_entity_id:
        payload["focal_entity_id"] = focal_entity_id
    return payload


def _emit_context_summary(payload: dict[str, Any]) -> None:
    matches = payload.get("matched_entities") or payload.get("context_pack", {}).get(
        "matched_entities",
        [],
    )
    if not matches:
        typer.echo("No context matches.")
        return
    for match in matches:
        typer.echo(
            f"{match.get('entity_id')}  "
            f"{match.get('display_name', '-')}  "
            f"{match.get('confidence_band', '-')}  "
            f"{match.get('score', '-')}"
        )


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


@app.command("retrieve")
def retrieve_context(
    query: str,
    entity_hint: Annotated[list[str] | None, typer.Option("--entity-hint")] = None,
    focal_entity_id: Annotated[str | None, typer.Option("--focal-entity-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        "/api/context/retrieve",
        payload=_context_payload(
            query,
            entity_hints=entity_hint,
            focal_entity_id=focal_entity_id,
            limit=limit,
        ),
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        _emit_context_summary(payload)


@app.command("context-card")
def context_card(
    entity_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("GET", f"/api/entities/{entity_id}/context-card")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    entity = payload["entity"]
    typer.echo(f"{entity['display_name']} ({entity['id']})")
    typer.echo(f"Aliases: {len(payload['aliases'])}")
    typer.echo(f"Facts: {len(payload['profile_facts'])}")
    typer.echo(f"Relationships: {len(payload['relationship_edges'])}")
    typer.echo(f"Recent context: {len(payload['recent_context'])}")


@context_app.command("pack")
def context_pack(
    query: str,
    entity_hint: Annotated[list[str] | None, typer.Option("--entity-hint")] = None,
    focal_entity_id: Annotated[str | None, typer.Option("--focal-entity-id")] = None,
    situation: Annotated[str | None, typer.Option("--situation")] = None,
    include_debug: Annotated[bool, typer.Option("--debug")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _context_payload(
        query,
        entity_hints=entity_hint,
        focal_entity_id=focal_entity_id,
        include_debug=include_debug,
        limit=limit,
    )
    if situation:
        payload["situation"] = situation
    response = _request("POST", "/api/context/pack", payload=payload)
    _raise_for_api(response)
    body = response.json()
    if json_output:
        _emit(body, json_output=True)
        return
    pack = body["context_pack"]
    typer.echo(f"Confidence: {pack['confidence']}")
    typer.echo(f"Policy: {pack['suggested_response_policy']}")
    _emit_context_summary(body)


@debug_app.command("retrieval")
def debug_retrieval(
    query: str,
    entity_hint: Annotated[list[str] | None, typer.Option("--entity-hint")] = None,
    focal_entity_id: Annotated[str | None, typer.Option("--focal-entity-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        "/api/context/retrieve",
        payload=_context_payload(
            query,
            entity_hints=entity_hint,
            focal_entity_id=focal_entity_id,
            include_debug=True,
            limit=limit,
        ),
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    _emit_context_summary(payload)
    typer.echo(json.dumps(payload.get("debug", {}), ensure_ascii=False, sort_keys=True))


@graph_app.command("ego")
def graph_ego(
    entity_id: str,
    relation_type: Annotated[str | None, typer.Option("--relation-type")] = None,
    status: Annotated[str, typer.Option("--status")] = "active",
    sensitivity: Annotated[str | None, typer.Option("--sensitivity")] = None,
    depth: Annotated[int, typer.Option("--depth", min=1, max=2)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params = [f"depth={depth}"]
    if relation_type:
        params.append(f"relation_type={relation_type}")
    if status:
        params.append(f"status={status}")
    if sensitivity:
        params.append(f"sensitivity={sensitivity}")
    response = _request("GET", f"/api/graph/ego/{entity_id}?{'&'.join(params)}")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    typer.echo(f"Nodes: {len(payload['nodes'])}")
    typer.echo(f"Edges: {len(payload['edges'])}")


@embedding_app.command("status")
def embedding_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("GET", "/api/embeddings/status")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"Provider: {payload['provider']}")
        typer.echo(f"Status: {payload['status']}")
        typer.echo(f"Model: {payload.get('model') or '-'}")


@embedding_app.command("backfill")
def embedding_backfill(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    path = "/api/embeddings/backfill" if limit == 100 else f"/api/embeddings/backfill?limit={limit}"
    response = _request("POST", path)
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(
            "Backfill: "
            f"{payload['processed']} processed, "
            f"{payload['failed']} failed, "
            f"{payload['skipped']} skipped"
        )


@candidate_app.command("submit")
def candidate_submit(
    candidate_json: Path,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("POST", "/api/candidates", payload=_read_json_file(candidate_json))
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"Submitted candidate: {payload['id']} ({payload['status']})")


@candidate_app.command("list")
def candidate_list(
    status: Annotated[str | None, typer.Option("--status")] = None,
    candidate_type: Annotated[str | None, typer.Option("--candidate-type", "--type")] = None,
    target_entity_id: Annotated[str | None, typer.Option("--target-entity-id", "--target")] = None,
    sensitivity: Annotated[str | None, typer.Option("--sensitivity")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params = []
    if status:
        params.append(f"status={status}")
    if candidate_type:
        params.append(f"candidate_type={candidate_type}")
    if target_entity_id:
        params.append(f"target_entity_id={target_entity_id}")
    if sensitivity:
        params.append(f"sensitivity={sensitivity}")
    query = f"?{'&'.join(params)}" if params else ""
    response = _request("GET", f"/api/candidates{query}")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    for item in payload["items"]:
        typer.echo(f"{item['id']}  {item['candidate_type']}  {item['status']}")


@candidate_app.command("show")
def candidate_show(
    candidate_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("GET", f"/api/candidates/{candidate_id}")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"{payload['id']}  {payload['candidate_type']}  {payload['status']}")


def _candidate_action(
    candidate_id: str,
    action: str,
    resolution_note: str | None = None,
    json_output: bool = False,
) -> None:
    payload = {"resolution_note": resolution_note} if resolution_note else {}
    response = _request("POST", f"/api/candidates/{candidate_id}/{action}", payload=payload)
    _raise_for_api(response)
    body = response.json()
    if json_output:
        _emit(body, json_output=True)
        return
    canonical = body.get("canonical_record_ref")
    suffix = f" -> {canonical}" if canonical else ""
    typer.echo(f"{body['id']}  {body['status']}{suffix}")


@candidate_app.command("accept")
def candidate_accept(
    candidate_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "accept", json_output=json_output)


@candidate_app.command("reject")
def candidate_reject(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "reject", resolution_note, json_output)


@candidate_app.command("archive")
def candidate_archive(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "archive", resolution_note, json_output)


@candidate_app.command("clarify")
def candidate_clarify(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "needs-clarification", resolution_note, json_output)


@candidate_app.command("edit-accept")
def candidate_edit_accept(
    candidate_id: str,
    payload_json: Path,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        f"/api/candidates/{candidate_id}/edit-accept",
        payload={"payload": _read_json_file(payload_json), "resolution_note": resolution_note},
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"{payload['id']}  {payload['status']} -> {payload['canonical_record_ref']}")


@candidate_app.command("supersede")
def candidate_supersede(
    candidate_id: str,
    supersedes_candidate_id: Annotated[str, typer.Option("--supersedes-candidate-id")],
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        f"/api/candidates/{candidate_id}/supersede",
        payload={
            "supersedes_candidate_id": supersedes_candidate_id,
            "resolution_note": resolution_note,
        },
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"{payload['id']}  {payload['status']}")


@correction_app.command("apply")
def correction_apply(
    correction_json: Path,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("POST", "/api/corrections/apply", payload=_read_json_file(correction_json))
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"{payload['old_record_ref']} -> {payload['new_record_ref']}")


@app.command()
def init(
    self_name: Annotated[str, typer.Option("--self-name")] = "Self",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    env_example = Path(".env.example")
    response = _request(
        "POST",
        "/api/entities",
        payload={
            "entity_type": "person",
            "display_name": self_name,
            "created_by": "system",
            "system_role": "self",
            "is_system": True,
            "confirmation_status": "confirmed",
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
        },
    )
    if response.status_code == 409:
        response = _request("GET", "/api/entities?system_role=self&limit=1")
        _raise_for_api(response)
        payload = response.json()["items"][0]
    else:
        _raise_for_api(response)
        payload = response.json()

    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"Protected self ready: {payload['display_name']} ({payload['id']})")
        typer.echo("Kinlayer config defaults are documented in .env.example.")
    if not env_example.exists():
        typer.echo("Warning: .env.example is missing.")


@person_app.command("create")
def person_create(
    name: Annotated[str, typer.Option("--name")],
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
    sensitivity: Annotated[str, typer.Option("--sensitivity")] = "medium",
    ai_use_policy: Annotated[str, typer.Option("--ai-use-policy")] = "cautious_use",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        "/api/entities",
        payload={
            "entity_type": "person",
            "display_name": name,
            "properties": {"short_note": note} if note else {},
            "confirmation_status": "confirmed",
            "sensitivity": sensitivity,
            "ai_use_policy": ai_use_policy,
            "created_by": "user",
        },
    )
    _raise_for_api(response)
    entity = response.json()
    aliases = []
    for value in alias or []:
        alias_response = _request(
            "POST",
            f"/api/entities/{entity['id']}/aliases",
            payload={"alias": value, "created_by": "user"},
        )
        _raise_for_api(alias_response)
        aliases.append(alias_response.json())
    payload = {"entity": entity, "aliases": aliases}
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"Created person: {entity['display_name']} ({entity['id']})")


@person_app.command("list")
def person_list(
    query: Annotated[str | None, typer.Option("--query")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params = "entity_type=person"
    if query:
        params += f"&q={query}"
    response = _request("GET", f"/api/entities?{params}")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    for item in payload["items"]:
        typer.echo(f"{item['id']}  {item['display_name']}  {item['sensitivity']}")


@person_app.command("show")
def person_show(
    entity_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    entity_response = _request("GET", f"/api/entities/{entity_id}")
    _raise_for_api(entity_response)
    alias_response = _request("GET", f"/api/entities/{entity_id}/aliases")
    _raise_for_api(alias_response)
    fact_response = _request("GET", f"/api/entity-facts?entity_id={entity_id}&status=active")
    _raise_for_api(fact_response)
    payload = {
        "entity": entity_response.json(),
        "aliases": alias_response.json()["items"],
        "facts": fact_response.json()["items"],
    }
    if json_output:
        _emit(payload, json_output=True)
    else:
        typer.echo(f"{payload['entity']['display_name']} ({entity_id})")
        for alias_item in payload["aliases"]:
            typer.echo(f"alias: {alias_item['alias']}")
        for fact in payload["facts"]:
            typer.echo(f"{fact['fact_type']}: {fact['content']}")


if __name__ == "__main__":
    app()
