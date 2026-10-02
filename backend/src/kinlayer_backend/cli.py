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
curation_app = typer.Typer(help="Prepare, plan, and inspect periodic curation runs.")
debug_app = typer.Typer(help="Inspect retrieval internals.")
graph_app = typer.Typer(help="Inspect relationship graph views.")
ontology_app = typer.Typer(help="Inspect ontology registries and diagnostics.")
agent_operations_app = typer.Typer(help="Inspect and export agent write operations.")
agent_write_app = typer.Typer(help="Validate agent write payloads.")
fact_app = typer.Typer(help="Promote and inspect profile facts.")
memory_app = typer.Typer(help="Save, correct, retract or reattribute memories immediately.")
app.add_typer(memory_app, name="memory")
app.add_typer(person_app, name="person")
app.add_typer(embedding_app, name="embedding")
app.add_typer(candidate_app, name="candidate")
app.add_typer(correction_app, name="correction")
app.add_typer(context_app, name="context")
app.add_typer(curation_app, name="curation")
app.add_typer(debug_app, name="debug")
app.add_typer(graph_app, name="graph")
app.add_typer(ontology_app, name="ontology")
app.add_typer(agent_operations_app, name="agent-operations")
app.add_typer(agent_write_app, name="agent-write")
app.add_typer(fact_app, name="fact")


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
    if path.startswith("/api/material-imports/"):
        if not settings.material_import_token:
            raise typer.BadParameter("KINLAYER_MATERIAL_IMPORT_TOKEN is required.")
        headers = {"Authorization": f"Bearer {settings.material_import_token}"}
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
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if isinstance(code, str) and isinstance(message, str):
            raise typer.BadParameter(f"{code}: {message}")
        if isinstance(message, str):
            raise typer.BadParameter(message)
    raise typer.BadParameter(f"HTTP {response.status_code}")


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


@app.command("material-import")
def material_import(
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    submit: Annotated[bool, typer.Option("--submit", help="Save authorized memories; default validates with rollback.")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate V1/V2 authorized material; submit explicitly and verify its receipt."""
    if file.stat().st_size > 100_000:
        raise typer.BadParameter("Import manifest exceeds 100000 bytes.")
    from pydantic import ValidationError
    from kinlayer_backend.schemas.material_imports import MaterialImportV2Request, material_import_adapter
    from kinlayer_backend.services.material_imports import request_fingerprint

    payload = _read_json_file(file)
    try:
        envelope = material_import_adapter.validate_python(payload)
    except ValidationError as exc:
        raise typer.BadParameter(f"Invalid material import: {exc}") from exc
    response = _request("POST", "/api/material-imports/" + ("submit" if submit else "validate"), payload=payload)
    _raise_for_api(response)
    result = response.json()
    if result.get("request_sha256") != request_fingerprint(envelope):
        raise typer.BadParameter("Import receipt has a different request hash; do not re-key.")
    if submit:
        from urllib.parse import quote

        if result.get("import_id") != envelope.idempotency_key:
            raise typer.BadParameter("Import receipt has a different import ID; do not re-key.")
        if isinstance(envelope, MaterialImportV2Request):
            refs = result.get("canonical_record_refs", [])
            episodes = result.get("episode_ids", [])
            if (
                result.get("validation_scope") != "immediate_memories"
                or result.get("candidate_ids") != []
                or len(set(refs)) != len(envelope.records)
                or sorted(ref.split(":", 1)[0] for ref in refs)
                != sorted(item.record.record_type for item in envelope.records)
                or len(set(episodes)) != len(envelope.sources)
            ):
                raise typer.BadParameter("Server did not return a V2 receipt; do not downgrade or re-key.")

        readback = _request("GET", "/api/material-imports/" + quote(result["import_id"], safe=""))
        _raise_for_api(readback)
        actual = readback.json()
        if (
            any(actual.get(key) != result.get(key) for key in (
                "import_id", "request_sha256", "candidate_ids", "canonical_record_refs",
                "episode_ids", "validation_scope",
            ))
            or actual.get("manifest") != envelope.model_dump(mode="json", exclude={"idempotency_key"})
        ):
            raise typer.BadParameter("Import committed but receipt readback did not match; do not re-key.")
    _emit(result, json_output)


def _query_path(path: str, params: list[tuple[str, Any]]) -> str:
    parts = [f"{key}={value}" for key, value in params if value is not None]
    return f"{path}?{'&'.join(parts)}" if parts else path


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


def _display_name_from_context_card(payload: dict[str, Any], fallback: str) -> str:
    entity = payload.get("entity")
    if isinstance(entity, dict):
        display_name = entity.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
    return fallback


def _emit_merge_candidate_summary(payload: dict[str, Any]) -> bool:
    if payload.get("candidate_type") != "merge":
        return False
    merge_payload = payload.get("payload")
    if not isinstance(merge_payload, dict):
        return False
    source_id = merge_payload.get("source_entity_id")
    target_id = merge_payload.get("target_entity_id") or payload.get("target_entity_id")
    if not isinstance(source_id, str) or not isinstance(target_id, str):
        return False

    source_response = _request("GET", f"/api/entities/{source_id}/context-card")
    _raise_for_api(source_response)
    target_response = _request("GET", f"/api/entities/{target_id}/context-card")
    _raise_for_api(target_response)
    source_card = source_response.json()
    target_card = target_response.json()
    source_name = _display_name_from_context_card(source_card, source_id)
    target_name = _display_name_from_context_card(target_card, target_id)

    typer.echo(f"Merge review: {source_name} -> {target_name}")
    reason = merge_payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        typer.echo(f"Reason: {reason.strip()}")
    fields = merge_payload.get("fields_to_merge")
    if isinstance(fields, list) and fields:
        typer.echo(f"Fields: {', '.join(str(field) for field in fields)}")
    risk_notes = merge_payload.get("risk_notes")
    if isinstance(risk_notes, list):
        for risk_note in risk_notes:
            if isinstance(risk_note, str) and risk_note.strip():
                typer.echo(f"Risk: {risk_note.strip()}")
    typer.echo(
        "Source: "
        f"{len(source_card.get('aliases', []))} aliases, "
        f"{len(source_card.get('profile_facts', []))} facts, "
        f"{len(source_card.get('relationship_edges', []))} relationships"
    )
    typer.echo(
        "Target: "
        f"{len(target_card.get('aliases', []))} aliases, "
        f"{len(target_card.get('profile_facts', []))} facts, "
        f"{len(target_card.get('relationship_edges', []))} relationships"
    )
    return True


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
    include_provisional: Annotated[bool, typer.Option("--include-provisional")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    path = f"/api/entities/{entity_id}/context-card"
    if include_provisional:
        path += "?include_provisional=true"
    response = _request("GET", path)
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
    include_provisional: Annotated[bool, typer.Option("--include-provisional")] = False,
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
    if include_provisional:
        payload["include_provisional"] = True
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


@curation_app.command("prepare")
def curation_prepare(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("POST", "/api/curation/source-packs", payload={"limit": limit})
    _raise_for_api(response)
    _emit(response.json(), json_output)


@curation_app.command("plan-file")
def curation_plan_file(
    plan_json: Path,
    mode: Annotated[str, typer.Option("--mode")] = "shadow",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _read_json_file(plan_json)
    payload["mode"] = mode
    response = _request("POST", "/api/curation/runs", payload=payload)
    _raise_for_api(response)
    _emit(response.json(), json_output)


def _curation_run_action(run_id: str, action: str, json_output: bool) -> None:
    response = _request("POST", f"/api/curation/runs/{run_id}/{action}")
    _raise_for_api(response)
    _emit(response.json(), json_output)


@curation_app.command("execute")
def curation_execute(
    run_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _curation_run_action(run_id, "execute", json_output)


@curation_app.command("resume")
def curation_resume(
    run_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _curation_run_action(run_id, "resume", json_output)


@curation_app.command("show")
def curation_show(
    run_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("GET", f"/api/curation/runs/{run_id}")
    _raise_for_api(response)
    _emit(response.json(), json_output)


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
    depth: Annotated[int, typer.Option("--depth", min=1, max=2)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params = [f"depth={depth}"]
    if relation_type:
        params.append(f"relation_type={relation_type}")
    if status:
        params.append(f"status={status}")
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
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params = []
    if status:
        params.append(f"status={status}")
    if candidate_type:
        params.append(f"candidate_type={candidate_type}")
    if target_entity_id:
        params.append(f"target_entity_id={target_entity_id}")
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
        if _emit_merge_candidate_summary(payload):
            return
        typer.echo(f"{payload['id']}  {payload['candidate_type']}  {payload['status']}")


def _candidate_action(
    candidate_id: str,
    action: str,
    resolution_note: str | None = None,
    resolved_by: str = "user",
    json_output: bool = False,
) -> None:
    payload: dict[str, Any] = {"resolved_by": resolved_by}
    if resolution_note:
        payload["resolution_note"] = resolution_note
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
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "user",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "accept", resolution_note, resolved_by, json_output)


@candidate_app.command("reject")
def candidate_reject(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "user",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "reject", resolution_note, resolved_by, json_output)


@candidate_app.command("archive")
def candidate_archive(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "user",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "archive", resolution_note, resolved_by, json_output)


@candidate_app.command("clarify")
def candidate_clarify(
    candidate_id: str,
    resolution_note: Annotated[str | None, typer.Option("--resolution-note", "--note")] = None,
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "user",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _candidate_action(candidate_id, "needs-clarification", resolution_note, resolved_by, json_output)


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


@fact_app.command("promote")
def fact_promote(
    fact_id: str,
    fact_type: Annotated[str, typer.Option("--fact-type")],
    content: Annotated[str, typer.Option("--content")],
    field_path: Annotated[str | None, typer.Option("--field-path")] = None,
    ai_use_policy: Annotated[str | None, typer.Option("--ai-use-policy")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    source_response = _request("GET", f"/api/entity-facts/{fact_id}")
    _raise_for_api(source_response)
    source = source_response.json()
    payload = {
        "entity_id": source["entity_id"],
        "fact_type": fact_type,
        "content": content,
    }
    if field_path:
        payload["field_path"] = field_path
    if ai_use_policy:
        payload["ai_use_policy"] = ai_use_policy
    response = _request("POST", f"/api/entity-facts/{fact_id}/promote", payload=payload)
    _raise_for_api(response)
    body = response.json()
    if json_output:
        _emit(body, json_output=True)
        return
    typer.echo(f"{body['source_record_ref']} -> {body['replacement_record_ref']}")


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


@agent_write_app.command("validate")
def agent_write_validate(
    agent_write_json: Path,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "POST",
        "/api/agent-writes/validate",
        payload=_read_json_file(agent_write_json),
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    status = "accepted" if payload["accepted"] else "rejected"
    typer.echo(f"Agent write validation: {status}")
    for issue in payload.get("errors", []):
        field = f" {issue['field']}" if issue.get("field") else ""
        typer.echo(f"- {issue['code']}{field}: {issue['message']}")


@agent_operations_app.command("list")
def agent_operations_list(
    actor: Annotated[str | None, typer.Option("--actor")] = None,
    source_path: Annotated[str | None, typer.Option("--source-path")] = None,
    operation_type: Annotated[str | None, typer.Option("--operation-type")] = None,
    result_status: Annotated[str | None, typer.Option("--result-status")] = None,
    has_error: Annotated[bool | None, typer.Option("--has-error")] = None,
    created_from: Annotated[str | None, typer.Option("--created-from")] = None,
    created_to: Annotated[str | None, typer.Option("--created-to")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request(
        "GET",
        _query_path(
            "/api/agent-operations",
            [
                ("actor", actor),
                ("source_path", source_path),
                ("operation_type", operation_type),
                ("result_status", result_status),
                ("has_error", has_error),
                ("created_from", created_from),
                ("created_to", created_to),
                ("limit", limit if limit != 50 else None),
            ],
        ),
    )
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    for item in payload["items"]:
        typer.echo(
            f"{item['id']}  {item['operation_type']}  "
            f"{item['result_status']}  {item['actor']}"
        )


@agent_operations_app.command("export")
def agent_operations_export(
    actor: Annotated[str | None, typer.Option("--actor")] = None,
    source_path: Annotated[str | None, typer.Option("--source-path")] = None,
    operation_type: Annotated[str | None, typer.Option("--operation-type")] = None,
    result_status: Annotated[str | None, typer.Option("--result-status")] = None,
    has_error: Annotated[bool | None, typer.Option("--has-error")] = None,
    created_from: Annotated[str | None, typer.Option("--created-from")] = None,
    created_to: Annotated[str | None, typer.Option("--created-to")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 200,
) -> None:
    response = _request(
        "GET",
        _query_path(
            "/api/agent-operations/export",
            [
                ("actor", actor),
                ("source_path", source_path),
                ("operation_type", operation_type),
                ("result_status", result_status),
                ("has_error", has_error),
                ("created_from", created_from),
                ("created_to", created_to),
                ("limit", limit),
            ],
        ),
    )
    _raise_for_api(response)
    typer.echo(response.text, nl=False)


@ontology_app.command("edge-diagnostics")
def ontology_edge_diagnostics(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("GET", "/api/ontology/edge-type-diagnostics")
    _raise_for_api(response)
    payload = response.json()
    if json_output:
        _emit(payload, json_output=True)
        return
    for item in payload["relation_types"]:
        status = "ok" if item["exists_in_allowed_edge_types"] else "invalid"
        typer.echo(f"{item['relation_type']}  {status}  active_edges={item['active_edge_count']}")
    if payload["invalid_edges"]:
        typer.echo("Invalid edges:")
        for edge in payload["invalid_edges"]:
            typer.echo(f"{edge['edge_id']}  {edge['relation_type']}  {edge['status']}")


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
        typer.echo(f"{item['id']}  {item['display_name']}")


@person_app.command("resolve")
def person_resolve(
    surface: str,
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
    relation_hint: Annotated[str | None, typer.Option("--relation-hint")] = None,
    entity_type: Annotated[str | None, typer.Option("--entity-type")] = "person",
    source_kind: Annotated[str, typer.Option("--source-kind")] = "agent",
    include_self: Annotated[bool, typer.Option("--include-self")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    source: dict[str, Any] = {"kind": source_kind}
    if include_self:
        source["include_self"] = True
    payload = {
        "surface": surface,
        "aliases": alias or [],
        "relation_hint": relation_hint,
        "entity_type": entity_type,
        "source": source,
    }
    response = _request("POST", "/api/entities/resolve", payload=payload)
    _raise_for_api(response)
    body = response.json()
    if json_output:
        _emit(body, json_output=True)
        return
    typer.echo(f"Ambiguity: {body['ambiguity']}")
    for match in body["matches"]:
        typer.echo(
            f"{match['entity_id']}  {match['display_name']}  "
            f"{match['score']}  {','.join(match['match_reasons'])}"
        )


@person_app.command("duplicates")
def person_duplicates(
    entity_id: str,
    limit: Annotated[int, typer.Option("--limit", min=1, max=25)] = 5,
    create_candidate: Annotated[bool, typer.Option("--create-candidate")] = False,
    evidence_episode_id: Annotated[str | None, typer.Option("--evidence-episode-id")] = None,
    evidence_excerpt: Annotated[str | None, typer.Option("--evidence-excerpt")] = None,
    evidence_confidence: Annotated[float, typer.Option("--evidence-confidence", min=0, max=1)] = 0.9,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload: dict[str, Any] = {
        "source_entity_id": entity_id,
        "limit": limit,
        "create_candidate": create_candidate,
    }
    if create_candidate:
        if not evidence_episode_id or not evidence_excerpt:
            raise typer.BadParameter(
                "--evidence-episode-id and --evidence-excerpt are required with --create-candidate"
            )
        payload["evidence"] = [
            {
                "episode_id": evidence_episode_id,
                "excerpt": evidence_excerpt,
                "confidence": evidence_confidence,
            }
        ]

    response = _request("POST", "/api/entities/duplicate-candidates", payload=payload)
    _raise_for_api(response)
    body = response.json()
    if json_output:
        _emit(body, json_output=True)
        return

    typer.echo(f"Recommended action: {body.get('recommended_action', 'unknown')}")
    created = body.get("created_candidate")
    if isinstance(created, dict):
        typer.echo(f"Created candidate: {created.get('id')} ({created.get('candidate_type')})")
    for item in body.get("candidates", []):
        if isinstance(item, dict):
            typer.echo(
                f"{item.get('target_entity_id')}  "
                f"{item.get('display_name', '-')}  "
                f"{item.get('score', '-')}"
            )


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


@memory_app.command("apply")
def memory_apply(
    request_json: Path,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    response = _request("POST", "/api/memories", payload=_read_json_file(request_json))
    _raise_for_api(response)
    payload = response.json()
    _emit(payload, json_output=json_output)
