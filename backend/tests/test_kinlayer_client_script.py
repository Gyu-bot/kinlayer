import io
import importlib.util
import json
import socket
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "kinlayer_client.py"
SPEC = importlib.util.spec_from_file_location("kinlayer_client", SCRIPT_PATH)
assert SPEC and SPEC.loader
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, method, url, *, headers=None, body=None, timeout=5):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": json.loads(body) if body else None,
                "timeout": timeout,
            }
        )
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def run(client_args, monkeypatch, responses):
    monkeypatch.setenv("KINLAYER_API_BASE_URL", "http://kinlayer.invalid:8765")
    transport = FakeTransport(responses)
    return client.run(client_args, transport=transport), transport


def output(capsys):
    return json.loads(capsys.readouterr().out)


def test_argument_parser_supports_required_options_and_structured_errors(capsys):
    args = client.build_parser().parse_args(
        [
            "--raw",
            "retrieve",
            "--query",
            "Jordan context",
            "--hint",
            "Jordan",
            "--hint",
            "J",
            "--include-debug",
        ]
    )
    assert args.raw is True
    assert args.hint == ["Jordan", "J"]
    assert args.limit == 10

    with pytest.raises(SystemExit) as exc:
        client.build_parser().parse_args(["candidate"])
    assert exc.value.code == 2
    assert output(capsys) == {
        "ok": False,
        "error": "argument_error",
        "message": "Invalid command arguments.",
    }

    with pytest.raises(SystemExit) as exc:
        client.build_parser().parse_args(["entities", "--offset", "-1"])
    assert exc.value.code == 2
    assert output(capsys)["error"] == "argument_error"


def test_base_url_resolution_order_and_safe_validation(monkeypatch):
    hermes_base_url = client._hermes_base_url
    monkeypatch.setenv("KINLAYER_API_BASE_URL", " https://env.example.test/kinlayer/ ")
    monkeypatch.setattr(client, "_hermes_base_url", lambda: "https://hermes.example.test")
    assert client.resolve_base_url() == "https://env.example.test/kinlayer"

    monkeypatch.delenv("KINLAYER_API_BASE_URL")
    monkeypatch.setattr(client.shutil, "which", lambda _name: "/usr/local/bin/hermes")

    call = {}

    def run_hermes(command, **kwargs):
        call.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout='"https://hermes.example.test/api/"')

    monkeypatch.setattr(
        client.subprocess,
        "run",
        run_hermes,
    )
    monkeypatch.setattr(client, "_hermes_base_url", hermes_base_url)
    assert client._hermes_base_url() == "https://hermes.example.test/api/"
    assert client.resolve_base_url() == "https://hermes.example.test/api"
    assert call["command"] == [
        "/usr/local/bin/hermes",
        "config",
        "get",
        client.HERMES_BASE_URL_KEY,
        "--json",
    ]
    assert call["kwargs"]["stdin"] is client.subprocess.DEVNULL
    assert call["kwargs"]["timeout"] == 2

    monkeypatch.setattr(client, "_hermes_base_url", lambda: None)
    assert client.resolve_base_url() == client.DEFAULT_BASE_URL

    for invalid in ("http://user:secret@example.test", "https://example.test/bad path"):
        monkeypatch.setenv("KINLAYER_API_BASE_URL", invalid)
        with pytest.raises(client.ClientError) as exc:
            client.resolve_base_url()
        assert exc.value.error == "invalid_base_url"
        assert invalid not in json.dumps(exc.value.to_payload())


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout='"https://ignored.example"'),
        SimpleNamespace(returncode=0, stdout="not-json"),
        SimpleNamespace(returncode=0, stdout='{"base_url":"https://ignored.example"}'),
        SimpleNamespace(returncode=0, stdout='"http://user:secret@example.test"'),
        SimpleNamespace(returncode=0, stdout='"https://example.test/bad path"'),
        SimpleNamespace(returncode=0, stdout='"https://example.test?secret=value"'),
        SimpleNamespace(returncode=0, stdout='"https://example.test/#private"'),
        SimpleNamespace(returncode=0, stdout='"https://example.test:70000"'),
    ],
)
def test_hermes_lookup_falls_back_on_unusable_output(result, monkeypatch, capsys):
    monkeypatch.delenv("KINLAYER_API_BASE_URL", raising=False)
    monkeypatch.setattr(client.shutil, "which", lambda _name: "/usr/local/bin/hermes")
    monkeypatch.setattr(client.subprocess, "run", lambda *args, **kwargs: result)
    assert client.resolve_base_url() == client.DEFAULT_BASE_URL
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_hermes_lookup_falls_back_when_missing_or_timed_out(monkeypatch):
    monkeypatch.delenv("KINLAYER_API_BASE_URL", raising=False)
    monkeypatch.setattr(client.shutil, "which", lambda _name: None)
    assert client.resolve_base_url() == client.DEFAULT_BASE_URL

    monkeypatch.setattr(client.shutil, "which", lambda _name: "/usr/local/bin/hermes")

    def timeout(*args, **kwargs):
        raise client.subprocess.TimeoutExpired(args[0], 2)

    monkeypatch.setattr(client.subprocess, "run", timeout)
    assert client.resolve_base_url() == client.DEFAULT_BASE_URL


def test_query_and_response_normalization(monkeypatch, capsys):
    observation = {
        "id": "obs_1",
        "subject_entity_id": "person_jordan",
        "related_entities": [{"entity_id": "person_lee"}],
        "observation_type": "communication_preference",
        "claim_type": "fact",
        "content": "Prefers bullets.",
        "sensitivity": "medium",
        "ai_use_policy": "cautious_use",
        "occurred_at": "2026-08-29T00:00:00Z",
    }
    code, transport = run(
        [
            "observations",
            "--subject-entity-id",
            "person jordan",
            "--observation-type",
            "communication_preference",
        ],
        monkeypatch,
        [{"items": [observation], "total": 1, "limit": 50, "offset": 0}],
    )
    assert code == 0
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(transport.calls[0]["url"]).query)
    assert query["subject_entity_id"] == ["person jordan"]
    assert "entity_id" not in query
    assert "status" not in query
    assert output(capsys)["items"][0]["related_entity_ids"] == ["person_lee"]

    card = {
        "entity": {"id": "person_jordan", "display_name": "Jordan", "entity_type": "person"},
        "provisional_context": [
            {
                "candidate_id": "cand_1",
                "content": "Possible preference.",
                "observation_type": "communication_preference",
                "sensitivity": "medium",
                "review_status": "unreviewed",
                "write_evidence_eligible": False,
            }
        ],
    }
    code, _ = run(
        ["context-card", "--entity-id", "person_jordan", "--include-provisional"],
        monkeypatch,
        [card],
    )
    assert code == 0
    assert output(capsys)["provisional_context"] == [
        {
            "candidate_id": "cand_1",
            "content": "Possible preference.",
            "observation_type": "communication_preference",
            "sensitivity": "medium",
            "review_status": "unreviewed",
        }
    ]

    code, transport = run(
        ["candidates"],
        monkeypatch,
        [{"items": [], "total": 0, "limit": 50, "offset": 0}],
    )
    assert code == 0
    assert "status" not in urllib.parse.parse_qs(
        urllib.parse.urlsplit(transport.calls[0]["url"]).query
    )
    output(capsys)

    candidate = {
        "id": "cand_1",
        "candidate_type": "observation",
        "status": "pending",
        "payload": {"content": "private", "subject_entity_id": "person_jordan"},
        "evidence": [{"id": "evidence_1"}],
    }
    code, _ = run(["candidate", "--id", "cand_1"], monkeypatch, [candidate])
    assert code == 0
    normalized = output(capsys)
    assert normalized["payload_keys"] == ["content", "subject_entity_id"]
    assert normalized["evidence_count"] == 1
    assert "payload" not in normalized

    retrieve = {
        "matched_entities": [{"entity_id": "person_jordan", "score": 0.8}],
        "observations": [],
        "scores": {"person_jordan": 0.8},
        "match_reasons": {"person_jordan": ["exact_name"]},
        "score_breakdown": {"person_jordan": {"name": 0.8}},
        "ambiguity_detected": True,
        "debug": {"details": True},
    }
    code, transport = run(
        ["retrieve", "--query", "Jordan", "--hint", "J", "--include-debug"],
        monkeypatch,
        [retrieve],
    )
    assert code == 0
    assert transport.calls[0]["body"] == {
        "query": "Jordan",
        "entity_hints": ["J"],
        "include_debug": True,
        "limit": 10,
    }
    normalized = output(capsys)
    assert normalized["ambiguity_detected"] is True
    assert normalized["debug_present"] is True
    assert "debug" not in normalized


def test_raw_returns_the_exact_api_payload(monkeypatch, capsys):
    payload = {"id": "cand_1", "payload": {"content": "explicit raw content"}}
    code, _ = run(["candidate", "--id", "cand_1", "--raw"], monkeypatch, [payload])
    assert code == 0
    assert output(capsys) == payload


@pytest.mark.parametrize(
    ("failure", "error", "status"),
    [
        (TimeoutError(), "timeout", None),
        (OSError(), "connection_failed", None),
        (
            client.ClientError("http_error", "HTTP failure.", "/api/system/health", 503),
            "http_error",
            503,
        ),
    ],
)
def test_runtime_errors_are_structured_and_do_not_leak_url(
    failure, error, status, monkeypatch, capsys
):
    code, _ = run(["health"], monkeypatch, [failure])
    assert code == 1
    payload = output(capsys)
    assert payload["error"] == error
    assert payload.get("status_code") == status
    assert "kinlayer.invalid" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("response", "error", "status"),
    [
        (b"not-json", "invalid_json", None),
        (b"\xff", "invalid_json", None),
        (b"[]", "invalid_json", None),
        (
            urllib.error.HTTPError("http://ignored", 404, "", {}, io.BytesIO(b"{}")),
            "not_found",
            404,
        ),
        (urllib.error.URLError(socket.timeout()), "timeout", None),
    ],
)
def test_http_transport_normalizes_protocol_errors(response, error, status, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return response

    def urlopen(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return Response()

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    with pytest.raises(client.ClientError) as exc:
        client.http_json_transport("GET", "http://base.invalid/api/system/health")
    assert exc.value.error == error
    assert exc.value.status_code == status
    assert exc.value.path == "/api/system/health"


def test_http_transport_does_not_forward_bearer_on_redirect(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    def urlopen(request, **kwargs):
        seen["request"] = request
        return Response()

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    client.http_json_transport(
        "GET",
        "http://base.invalid/api/entities",
        headers={"Authorization": "Bearer secret-token"},
    )

    request = seen["request"]
    assert request.get_header("Authorization") == "Bearer secret-token"
    redirected = client.urllib.request.HTTPRedirectHandler().redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "http://redirect.invalid/api/entities",
    )
    assert redirected.get_header("Authorization") is None


def test_command_surface_is_write_free_and_keeps_secrets_out_of_output(monkeypatch, capsys):
    subparsers = next(
        action
        for action in client.build_parser()._actions
        if isinstance(action, client.argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == {
        "health",
        "version",
        "schema-summary",
        "ontology",
        "entities",
        "context-card",
        "observations",
        "candidates",
        "candidate",
        "retrieve",
        "pack",
    }
    commands = [
        ["health"],
        ["version"],
        ["schema-summary"],
        ["ontology"],
        [
            "entities",
            "--query",
            "Jordan Kim",
            "--entity-type",
            "person",
            "--status",
            "active",
            "--sensitivity",
            "medium",
            "--system-role",
            "self",
            "--limit",
            "2",
            "--offset",
            "3",
        ],
        ["context-card", "--entity-id", "person/1", "--include-provisional"],
        [
            "observations",
            "--subject-entity-id",
            "person 1",
            "--related-entity-id",
            "person 2",
            "--observation-type",
            "caution",
            "--status",
            "archived",
            "--claim-type",
            "inference",
            "--limit",
            "4",
            "--offset",
            "5",
        ],
        [
            "candidates",
            "--status",
            "needs_clarification",
            "--candidate-type",
            "observation",
            "--target-entity-id",
            "person 1",
            "--sensitivity",
            "high",
            "--limit",
            "6",
            "--offset",
            "7",
        ],
        ["candidate", "--id", "cand/1"],
        [
            "retrieve",
            "--query",
            "context",
            "--hint",
            "Jordan",
            "--focal-entity-id",
            "person_1",
            "--include-debug",
            "--limit",
            "8",
        ],
        [
            "pack",
            "--query",
            "briefing",
            "--hint",
            "J",
            "--focal-entity-id",
            "person_2",
            "--include-debug",
            "--limit",
            "9",
            "--situation",
            "reply",
            "--include-provisional",
        ],
    ]
    monkeypatch.setenv("KINLAYER_API_TOKEN", "secret-token")
    transport = FakeTransport([{"status": "ok"}, *[{} for _ in commands[1:]]])
    monkeypatch.setenv("KINLAYER_API_BASE_URL", "http://private-host.invalid:8765")

    for command in commands:
        assert client.run(command, transport=transport) == 0
    text = capsys.readouterr().out

    expected = [
        ("GET", "/api/system/health", None),
        ("GET", "/api/system/version", None),
        ("GET", "/openapi.json", None),
        ("GET", "/api/ontology", None),
        (
            "GET",
            "/api/entities?q=Jordan+Kim&entity_type=person&status=active&sensitivity=medium&system_role=self&limit=2&offset=3",
            None,
        ),
        ("GET", "/api/entities/person%2F1/context-card?include_provisional=true", None),
        (
            "GET",
            "/api/observations?subject_entity_id=person+1&related_entity_id=person+2&observation_type=caution&status=archived&claim_type=inference&limit=4&offset=5",
            None,
        ),
        (
            "GET",
            "/api/candidates?status=needs_clarification&candidate_type=observation&target_entity_id=person+1&sensitivity=high&limit=6&offset=7",
            None,
        ),
        ("GET", "/api/candidates/cand%2F1", None),
        (
            "POST",
            "/api/context/retrieve",
            {
                "query": "context",
                "entity_hints": ["Jordan"],
                "focal_entity_id": "person_1",
                "include_debug": True,
                "limit": 8,
            },
        ),
        (
            "POST",
            "/api/context/pack",
            {
                "query": "briefing",
                "entity_hints": ["J"],
                "focal_entity_id": "person_2",
                "include_debug": True,
                "limit": 9,
                "situation": "reply",
                "include_provisional": True,
            },
        ),
    ]
    actual = []
    for call in transport.calls:
        parsed = urllib.parse.urlsplit(call["url"])
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        actual.append((call["method"], path, call["body"]))
    assert actual == expected
    assert all(
        "accept" not in call["url"] and "corrections" not in call["url"] for call in transport.calls
    )
    assert all(
        call["headers"].get("Authorization") == "Bearer secret-token" for call in transport.calls
    )
    assert "secret-token" not in text
    assert "private-host.invalid" not in text


def test_degraded_health_is_json_and_nonzero(monkeypatch, capsys):
    code, _ = run(
        ["health"],
        monkeypatch,
        [{"status": "degraded", "database": "unavailable", "embedding": "disabled"}],
    )
    assert code == 1
    assert output(capsys) == {
        "ok": False,
        "service": "kinlayer",
        "health": "degraded",
        "database": "unavailable",
        "embedding": "disabled",
    }
