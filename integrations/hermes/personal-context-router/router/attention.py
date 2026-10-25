from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


MAX_OUTPUT_BYTES = 8_192
MAX_SPEC_BYTES = 64 * 1_024
MAX_REPLY_BYTES = 16_000
TIMEOUT_SECONDS = 10.0
ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,160}$")
PERSON_TAG_RE = re.compile(r"^person:[0-9a-f]{16,64}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
PRODUCERS = {"kinlayer-reconciliation", "kinlayer-enrichment"}
ATTENTION_STATES = {
    "queued", "claimed", "sending", "delivery_unknown", "delivered",
    "completed", "cancelled", "expired",
}
BRIDGE_STATES = {
    "prepared", "sending", "delivery_unknown", "awaiting_first_reply",
    "bound", "conversing", "completed", "cancelled", "expired",
}
BRIDGE_REPLY_STATES = {"awaiting_first_reply", "bound", "conversing"}
_TECHNICAL = (
    re.compile(r"\[\[.*?\]\]", re.S),
    re.compile(
        r"(?<!\w)(?:nonce|claim[\s_]+token|fingerprint|message[\s_]+id|"
        r"메시지\s*(?:id|아이디|식별자)|session[\s_]+(?:id|identifier)|"
        r"conversation[\s_]+(?:id|identifier)|세션\s*식별자|대화\s*식별자|"
        r"option[\s_]+code|action[\s_]+code|옵션\s*코드|액션\s*코드|"
        r"작업\s*코드)(?!\w)(?:\s*[:=]\s*\S+|\s+[a-z0-9][a-z0-9_.:@/-]*)"
    ),
)


class AttentionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _id(name: str, value: object, *, optional: bool = False) -> str | None:
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise AttentionError(f"{name}_invalid")
    return value


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _closed(value: object, *, optional: bool = False) -> bool:
    return (optional and value is None) or (
        isinstance(value, str) and ID_RE.fullmatch(value) is not None
    )


def _timestamp(name: str, value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise AttentionError(f"attention_{name}_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AttentionError(f"attention_{name}_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttentionError(f"attention_{name}_invalid")
    return parsed


def _route(route: Mapping[str, object]) -> dict[str, str | None]:
    required = {"platform", "scope_id", "channel_id", "owner_id"}
    if (
        not isinstance(route, Mapping)
        or required - set(route)
        or set(route) - required - {"thread_id"}
    ):
        raise AttentionError("route_invalid")
    platform = _id("platform", route["platform"])
    if platform is None:
        raise AttentionError("platform_invalid")
    return {
        "platform": platform.lower(),
        "scope_id": _id("scope_id", route["scope_id"]),
        "channel_id": _id("channel_id", route["channel_id"]),
        "thread_id": _id("thread_id", route.get("thread_id"), optional=True),
        "owner_id": _id("owner_id", route["owner_id"]),
    }


def _owner_scope(scope: Mapping[str, object]) -> dict[str, str]:
    required = {"platform", "scope_id", "owner_id"}
    optional = {"channel_id", "thread_id"}
    if (
        not isinstance(scope, Mapping)
        or required - set(scope)
        or set(scope) - required - optional
    ):
        raise AttentionError("owner_scope_invalid")
    platform = _id("platform", scope["platform"])
    if platform is None:
        raise AttentionError("platform_invalid")
    return {
        "platform": platform.lower(),
        "scope_id": _id("scope_id", scope["scope_id"]) or "",
        "owner_id": _id("owner_id", scope["owner_id"]) or "",
    }


def attention_spec(spec: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "producer", "intent_ref", "idempotency_key", "platform", "scope_id",
        "channel_id", "thread_id", "owner_id", "priority", "delivery_mode",
        "context_tags", "interruptibility", "cooldown_group", "created_at",
        "not_before", "expires_at", "deadline_at",
    }
    required = allowed - {"thread_id", "deadline_at"}
    if not isinstance(spec, Mapping) or set(spec) - allowed or required - set(spec):
        raise AttentionError("attention_spec_invalid")
    producer = spec.get("producer")
    tags = spec.get("context_tags")
    if (
        producer not in PRODUCERS
        or spec.get("priority") != "normal"
        or spec.get("delivery_mode") != "adaptive"
        or spec.get("interruptibility") != "deferable"
        or spec.get("cooldown_group") != "kinlayer-question"
        or not isinstance(tags, list)
        or len(tags) != 1
        or not isinstance(tags[0], str)
        or not PERSON_TAG_RE.fullmatch(tags[0])
        or ("deadline_at" in spec and spec.get("deadline_at") is not None)
    ):
        raise AttentionError("attention_spec_invalid")
    route = _route({key: spec.get(key) for key in (
        "platform", "scope_id", "channel_id", "thread_id", "owner_id"
    )})
    created = _timestamp("created_at", spec.get("created_at"))
    not_before = _timestamp("not_before", spec.get("not_before"))
    expires = _timestamp("expires_at", spec.get("expires_at"))
    if not created <= not_before < expires:
        raise AttentionError("attention_timestamps_invalid")
    return {
        "producer": producer,
        "intent_ref": _id("intent_ref", spec.get("intent_ref")),
        "idempotency_key": _id("idempotency_key", spec.get("idempotency_key")),
        **route,
        "priority": "normal",
        "delivery_mode": "adaptive",
        "context_tags": [tags[0]],
        "interruptibility": "deferable",
        "cooldown_group": "kinlayer-question",
        "created_at": spec["created_at"],
        "not_before": spec["not_before"],
        "expires_at": spec["expires_at"],
        **({"deadline_at": None} if "deadline_at" in spec else {}),
    }


def bridge_spec(spec: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "adapter_key", "adapter_version", "conversation_key", "conversation_ref",
        "platform", "scope_id", "channel_id", "thread_id", "owner_id", "question",
        "skills", "initial_ttl_seconds", "lease_idle_seconds", "idempotency_key",
    }
    required = {
        "adapter_key", "adapter_version", "conversation_key", "conversation_ref",
        "platform", "scope_id", "channel_id", "owner_id", "question", "idempotency_key",
    }
    if not isinstance(spec, Mapping) or set(spec) - allowed or required - set(spec):
        raise AttentionError("bridge_spec_invalid")
    question = spec.get("question")
    skills = spec.get("skills", [])
    initial = spec.get("initial_ttl_seconds", 86_400)
    idle = spec.get("lease_idle_seconds", 1_800)
    if (
        spec.get("platform") != "discord"
        or not isinstance(question, str)
        or not question
        or question != question.strip()
        or len(question) > 1_800
        or any(
            pattern.search(unicodedata.normalize("NFKC", question).casefold())
            for pattern in _TECHNICAL
        )
        or not isinstance(skills, list)
        or len(skills) > 16
        or any(not isinstance(skill, str) for skill in skills)
        or len(skills) != len(set(skills))
        or type(initial) is not int
        or not 300 <= initial <= 604_800
        or type(idle) is not int
        or not 60 <= idle <= 86_400
    ):
        raise AttentionError("bridge_spec_invalid")
    return {
        "adapter_key": _id("adapter_key", spec.get("adapter_key")),
        "adapter_version": _id("adapter_version", spec.get("adapter_version")),
        "conversation_key": _id("conversation_key", spec.get("conversation_key")),
        "conversation_ref": _id("conversation_ref", spec.get("conversation_ref")),
        "platform": "discord",
        "scope_id": _id("scope_id", spec.get("scope_id")),
        "channel_id": _id("channel_id", spec.get("channel_id")),
        "thread_id": _id("thread_id", spec.get("thread_id"), optional=True),
        "owner_id": _id("owner_id", spec.get("owner_id")),
        "question": question,
        "skills": [_id("skill", skill) for skill in skills],
        "initial_ttl_seconds": initial,
        "lease_idle_seconds": idle,
        "idempotency_key": _id("idempotency_key", spec.get("idempotency_key")),
    }


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _json(raw: bytes, code: str) -> dict[str, object]:
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_closed_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise AttentionError(code) from None
    if not isinstance(value, dict):
        raise AttentionError(code)
    return value


def _bytes(value: object, code: str) -> bytes:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, bytearray):
        raw = bytes(value)
    elif isinstance(value, str):
        try:
            raw = value.encode("utf-8", "strict")
        except UnicodeEncodeError:
            raise AttentionError(code) from None
    else:
        raise AttentionError(code)
    if len(raw) > MAX_OUTPUT_BYTES:
        raise AttentionError(code)
    return raw


def _real_run(argv: list[str], input_data: bytes | None, timeout: float) -> tuple[int, bytes, bytes]:
    paths: list[str] = []
    files = []
    try:
        for _ in range(2):
            fd, path = tempfile.mkstemp(prefix="pcr-attention-output-")
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            paths.append(path)
            files.append(os.fdopen(fd, "w+b", buffering=0))
        try:
            kwargs: dict[str, object] = {
                "shell": False,
                "stdout": files[0],
                "stderr": files[1],
                "timeout": timeout,
                "check": False,
            }
            if input_data is None:
                kwargs["stdin"] = subprocess.DEVNULL
            else:
                kwargs["input"] = input_data
            result = subprocess.run(argv, **kwargs)
        except (OSError, subprocess.SubprocessError):
            raise AttentionError("subprocess_unavailable") from None
        output = []
        for file in files:
            if os.fstat(file.fileno()).st_size > MAX_OUTPUT_BYTES:
                raise AttentionError("subprocess_output_invalid")
            file.seek(0)
            output.append(file.read(MAX_OUTPUT_BYTES + 1))
        return result.returncode, output[0], output[1]
    finally:
        for file in files:
            file.close()
        for path in paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def _run(
    argv: list[str], *, input_data: bytes | None = None,
    runner: Callable[..., object] | None = None, timeout: float = TIMEOUT_SECONDS,
) -> tuple[int, bytes, bytes]:
    if runner is None:
        return _real_run(argv, input_data, timeout)
    try:
        kwargs: dict[str, object] = {
            "shell": False, "capture_output": True, "timeout": timeout,
        }
        if input_data is not None:
            kwargs["input"] = input_data
        result = runner(argv, **kwargs)
    except (OSError, subprocess.SubprocessError):
        raise AttentionError("subprocess_unavailable") from None
    returncode = getattr(result, "returncode", None)
    if type(returncode) is not int:
        raise AttentionError("subprocess_output_invalid")
    return (
        returncode,
        _bytes(getattr(result, "stdout", None), "subprocess_output_invalid"),
        _bytes(getattr(result, "stderr", None), "subprocess_output_invalid"),
    )


def _call(
    service: str,
    operation: str,
    args: list[str],
    validator: Callable[[dict[str, object]], dict[str, object]],
    *,
    input_data: bytes | None = None,
    runner: Callable[..., object] | None = None,
    returncodes: tuple[int, ...] = (0,),
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, object]:
    code = f"{service}_{operation}_invalid"
    try:
        returncode, stdout, stderr = _run(
            ["hermes", service, operation, *args], input_data=input_data,
            runner=runner, timeout=timeout,
        )
    except AttentionError as exc:
        if exc.code.startswith("subprocess_"):
            raise AttentionError(f"{service}_{operation}_unavailable") from None
        raise
    if stderr:
        raise AttentionError(code)
    value = _json(stdout, code)
    sanitized = validator(value)
    if returncode not in returncodes:
        raise AttentionError(code)
    return sanitized


def _private_spec_file(spec: Mapping[str, object]):
    class PrivateSpec:
        def __enter__(self):
            try:
                raw = json.dumps(
                    spec, ensure_ascii=False, separators=(",", ":"),
                    sort_keys=True, allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, UnicodeEncodeError):
                raise AttentionError("spec_encoding_invalid") from None
            if len(raw) > MAX_SPEC_BYTES:
                raise AttentionError("spec_too_large")
            fd, self.path = tempfile.mkstemp(prefix="pcr-private-spec-", suffix=".json")
            try:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                with os.fdopen(fd, "wb") as target:
                    target.write(raw)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(self.path)
                except FileNotFoundError:
                    pass
                raise
            return Path(self.path)

        def __exit__(self, *_args):
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass

    return PrivateSpec()


def _id_state_result(
    value: dict[str, object], expected_id: str, expected_states: set[str],
    *, id_key: str = "intent_id", optional_idempotent: bool = True,
    required_idempotent: bool = False,
) -> dict[str, object]:
    allowed = {"ok", id_key, "state"} | ({"idempotent"} if optional_idempotent else set())
    if (
        (set(value) != allowed if required_idempotent else set(value) not in ({"ok", id_key, "state"}, allowed))
        or value.get("ok") is not True
        or value.get(id_key) != expected_id
        or value.get("state") not in expected_states
        or ("idempotent" in value and type(value["idempotent"]) is not bool)
    ):
        raise AttentionError("command_result_invalid")
    result = {"ok": True, id_key: expected_id, "state": value["state"]}
    if "idempotent" in value:
        result["idempotent"] = value["idempotent"]
    return result


def attention_submit(
    spec: Mapping[str, object], *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    checked = attention_spec(spec)
    with _private_spec_file(checked) as path:
        def validate(value):
            if set(value) != {"ok", "intent_id", "state", "idempotent"}:
                raise AttentionError("attention_submit_invalid")
            intent_id = _id("intent_id", value.get("intent_id"))
            return _id_state_result(value, intent_id or "", ATTENTION_STATES)
        return _call(
            "proactive-attention", "submit", ["--spec-file", str(path)], validate,
            runner=runner,
        )


def attention_signal(
    route: Mapping[str, object], producer: str, context_tag: str,
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    checked_route = _route(route)
    if producer not in PRODUCERS or not PERSON_TAG_RE.fullmatch(context_tag):
        raise AttentionError("attention_signal_invalid")
    args = _route_args(checked_route) + ["--producer", producer, "--context-tag", context_tag]

    def validate(value):
        if (
            set(value) != {"ok", "action", "producer", "at"}
            or value.get("ok") is not True
            or value.get("action") != "signal"
            or value.get("producer") != producer
            or not _number(value.get("at"))
        ):
            raise AttentionError("attention_signal_invalid")
        return {"ok": True, "action": "signal", "producer": producer, "at": value["at"]}

    return _call("proactive-attention", "signal", args, validate, runner=runner)


def _route_args(route: Mapping[str, str | None]) -> list[str]:
    args = [
        "--platform", str(route["platform"]), "--scope-id", str(route["scope_id"]),
        "--channel-id", str(route["channel_id"]), "--owner-id", str(route["owner_id"]),
    ]
    if route.get("thread_id"):
        args.extend(("--thread-id", str(route["thread_id"])))
    return args


def begin_delivery(
    intent_id: str, lease_id: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""
    lease_id = _id("lease_id", lease_id) or ""
    return _call(
        "proactive-attention", "begin-delivery",
        ["--intent-id", intent_id, "--lease-id", lease_id],
        lambda value: _id_state_result(
            value, intent_id, {"sending"}, required_idempotent=True
        ), runner=runner,
    )


def complete(
    intent_id: str, lease_id: str, receipt_ref: str,
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""
    lease_id = _id("lease_id", lease_id) or ""
    receipt_ref = _id("receipt_ref", receipt_ref) or ""
    return _call(
        "proactive-attention", "complete",
        ["--intent-id", intent_id, "--lease-id", lease_id, "--receipt-ref", receipt_ref],
        lambda value: _id_state_result(
            value, intent_id, {"delivered", "completed"}, required_idempotent=True
        ),
        runner=runner,
    )


def release(
    intent_id: str, lease_id: str, outcome: str,
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""
    lease_id = _id("lease_id", lease_id) or ""
    if outcome not in {"not_started", "deferral", "failed_before_send"}:
        raise AttentionError("attention_release_invalid")

    def validate(value):
        if (
            set(value) != {"ok", "intent_id", "state", "retry_after"}
            or value.get("ok") is not True
            or value.get("intent_id") != intent_id
            or value.get("state") != "queued"
            or not _number(value.get("retry_after"))
        ):
            raise AttentionError("attention_release_invalid")
        return dict(value)

    return _call(
        "proactive-attention", "release",
        ["--intent-id", intent_id, "--lease-id", lease_id, "--outcome", outcome],
        validate, runner=runner,
    )


def cancel(
    intent_id: str, lease_id: str | None = None, outcome: str = "domain:cancelled",
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""
    outcome = _id("outcome", outcome) or ""
    args = ["--intent-id", intent_id]
    if lease_id is not None:
        args.extend(("--lease-id", _id("lease_id", lease_id) or ""))
    args.extend(("--outcome", outcome))

    def validate(value):
        if (
            set(value) != {"ok", "intent_id", "state", "outcome", "idempotent"}
            or value.get("outcome") != outcome
        ):
            raise AttentionError("attention_cancel_invalid")
        result = _id_state_result(
            {key: value[key] for key in ("ok", "intent_id", "state", "idempotent")},
            intent_id, {"cancelled"}, required_idempotent=True,
        )
        result["outcome"] = outcome
        return result

    return _call(
        "proactive-attention", "cancel", args,
        validate, runner=runner,
    )


def release_visible(
    intent_id: str, receipt_ref: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""
    receipt_ref = _id("receipt_ref", receipt_ref) or ""
    return _call(
        "proactive-attention", "release-visible",
        ["--intent-id", intent_id, "--receipt-ref", receipt_ref],
        lambda value: _id_state_result(
            value, intent_id, {"completed"}, required_idempotent=True
        ), runner=runner,
    )


def status(
    intent_id: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    intent_id = _id("intent_id", intent_id) or ""

    def validate(value):
        if set(value) != {"ok", "intent"} or value.get("ok") is not True:
            raise AttentionError("attention_status_invalid")
        intent = value.get("intent")
        base = {
            "producer", "intent_ref", "idempotency_key", "platform", "scope_id",
            "channel_id", "thread_id", "owner_id", "priority", "delivery_mode",
            "context_tags", "interruptibility", "cooldown_group", "created_at",
            "not_before", "expires_at", "deadline_at", "intent_id", "route", "state",
            "attempts",
        }
        optional = {
            "claimed_at", "lease_expires_at", "delivery_started_at", "delivered_at",
            "receipt_ref", "completed_at", "visible_released_at", "cancelled_at",
            "expired_at", "retry_after", "delivery_unknown_at", "last_release_at",
            "last_release_outcome",
        }
        if not isinstance(intent, dict) or not base <= set(intent) or set(intent) - base - optional:
            raise AttentionError("attention_status_invalid")
        timestamps = {
            "created_at", "not_before", "expires_at", "deadline_at", "claimed_at",
            "lease_expires_at", "delivery_started_at", "delivered_at", "completed_at",
            "visible_released_at", "cancelled_at", "expired_at", "retry_after",
            "delivery_unknown_at", "last_release_at",
        }
        route = intent.get("route")
        tags = intent.get("context_tags")
        if (
            intent.get("intent_id") != intent_id
            or intent.get("state") not in ATTENTION_STATES
            or intent.get("producer") not in PRODUCERS
            or any(not _closed(intent.get(key)) for key in (
                "intent_ref", "idempotency_key", "platform", "scope_id", "channel_id",
                "owner_id", "cooldown_group",
            ))
            or not _closed(intent.get("thread_id"), optional=True)
            or intent.get("priority") != "normal"
            or intent.get("delivery_mode") != "adaptive"
            or intent.get("interruptibility") != "deferable"
            or intent.get("cooldown_group") != "kinlayer-question"
            or not isinstance(tags, list)
            or len(tags) != 1
            or not isinstance(tags[0], str)
            or not PERSON_TAG_RE.fullmatch(tags[0])
            or not isinstance(route, list)
            or len(route) != 5
            or any(not _closed(part) for part in route)
            or route != [
                intent.get("platform"), intent.get("scope_id"), intent.get("channel_id"),
                intent.get("thread_id") or intent.get("channel_id"), intent.get("owner_id"),
            ]
            or type(intent.get("attempts")) is not int
            or intent["attempts"] < 0
            or any(not _number(intent[key]) for key in ("created_at", "not_before", "expires_at"))
            or any(key in intent and intent[key] is not None and not _number(intent[key]) for key in timestamps)
            or ("receipt_ref" in intent and not _closed(intent["receipt_ref"]))
            or (
                "last_release_outcome" in intent
                and intent["last_release_outcome"] not in {
                    "not_started", "deferral", "failed_before_send", "resolved_not_delivered",
                    "lease_expired_before_send",
                }
            )
        ):
            raise AttentionError("attention_status_invalid")
        result = {"ok": True, "intent_id": intent_id, "state": intent["state"]}
        for key in (
            "receipt_ref", "expires_at", "claimed_at", "lease_expires_at",
            "delivery_started_at", "delivered_at", "completed_at", "cancelled_at",
            "expired_at", "retry_after", "delivery_unknown_at",
        ):
            if key in intent:
                result[key] = intent[key]
        return result

    return _call(
        "proactive-attention", "status", ["--intent-id", intent_id], validate, runner=runner
    )


def claim_next(
    scope: Mapping[str, object], *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    checked = _owner_scope(scope)

    def validate(value):
        if value == {"ok": False, "error": "owner scope already has a visible lease"}:
            return {"ok": True, "claimed": False, "blocked": "visible_lease"}
        if not isinstance(value, dict) or set(value) not in (
            {"ok", "claimed"},
            {"ok", "claimed", "blocked"},
            {
                "ok", "claimed", "intent_id", "lease_id", "lease_expires_at",
                "producer", "intent_ref", "delivery_mode", "priority", "route",
            },
        ):
            raise AttentionError("attention_claim_next_invalid")
        if value.get("ok") is not True or type(value.get("claimed")) is not bool:
            raise AttentionError("attention_claim_next_invalid")
        if value["claimed"] is False:
            if set(value) == {"ok", "claimed"}:
                return {"ok": True, "claimed": False}
            if value == {"ok": True, "claimed": False, "blocked": "visible_lease"}:
                return dict(value)
            raise AttentionError("attention_claim_next_invalid")
        route = value.get("route")
        if (
            _id("intent_id", value.get("intent_id")) is None
            or _id("lease_id", value.get("lease_id")) is None
            or not _number(value.get("lease_expires_at"))
            or value.get("producer") not in PRODUCERS
            or _id("intent_ref", value.get("intent_ref")) is None
            or value.get("delivery_mode") not in {"contextual", "opportunistic", "deadline"}
            or value.get("priority") != "normal"
            or not isinstance(route, list)
            or len(route) != 5
            or any(not _closed(part) for part in route)
            or route[0] != checked["platform"]
            or route[1] != checked["scope_id"]
            or route[4] != checked["owner_id"]
        ):
            raise AttentionError("attention_claim_next_invalid")
        return {
            "ok": True,
            "claimed": True,
            "intent_id": value["intent_id"],
            "lease_id": value["lease_id"],
            "lease_expires_at": value["lease_expires_at"],
            "producer": value["producer"],
            "intent_ref": value["intent_ref"],
            "delivery_mode": value["delivery_mode"],
            "priority": "normal",
            "route": list(route),
        }

    return _call(
        "proactive-attention",
        "claim-next",
        [
            "--platform", checked["platform"],
            "--scope-id", checked["scope_id"],
            "--owner-id", checked["owner_id"],
        ],
        validate,
        runner=runner,
        returncodes=(0, 2),
    )


def bridge_stage(
    spec: Mapping[str, object], *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    checked = bridge_spec(spec)
    with _private_spec_file(checked) as path:
        def validate(value):
            if set(value) != {"ok", "conversation_id", "state", "idempotent"}:
                raise AttentionError("bridge_stage_invalid")
            conversation_id = _id("bridge_conversation_id", value.get("conversation_id")) or ""
            return _id_state_result(
                value, conversation_id, BRIDGE_STATES, id_key="conversation_id"
            )
        return _call(
            "proactive-conversation", "stage", ["--spec-file", str(path)], validate,
            runner=runner,
        )


def bridge_context(
    conversation_id: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    conversation_id = _id("bridge_conversation_id", conversation_id) or ""

    def validate(value):
        adapter = value.get("adapter")
        skills = value.get("skills")
        if (
            set(value) != {"ok", "conversation_id", "state", "adapter", "conversation_ref", "skills", "expires_at"}
            or value.get("ok") is not True
            or value.get("conversation_id") != conversation_id
            or value.get("state") not in BRIDGE_STATES
            or not isinstance(adapter, dict)
            or set(adapter) != {"key", "version"}
            or _id("adapter_key", adapter.get("key")) is None
            or _id("adapter_version", adapter.get("version")) is None
            or _id("conversation_ref", value.get("conversation_ref")) is None
            or not isinstance(skills, list)
            or len(skills) > 16
            or any(not isinstance(skill, str) for skill in skills)
            or len(skills) != len(set(skills))
            or any(_id("skill", skill) is None for skill in skills)
            or (value.get("expires_at") is not None and not _number(value.get("expires_at")))
        ):
            raise AttentionError("bridge_context_invalid")
        return {
            "ok": True, "conversation_id": conversation_id, "state": value["state"],
            "adapter": dict(adapter), "conversation_ref": value["conversation_ref"],
            "skills": list(skills), "expires_at": value["expires_at"],
        }

    return _call(
        "proactive-conversation", "context", ["--conversation-id", conversation_id],
        validate, runner=runner,
    )


def bridge_status(
    conversation_id: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    conversation_id = _id("bridge_conversation_id", conversation_id) or ""

    def validate(value):
        message_id = value.get("message_id")
        if (
            set(value) != {"ok", "conversation_id", "state", "expires_at", "message_id"}
            or value.get("ok") is not True
            or value.get("conversation_id") != conversation_id
            or value.get("state") not in BRIDGE_STATES
            or (value.get("expires_at") is not None and not _number(value.get("expires_at")))
            or (message_id is not None and _id("bridge_message_id", message_id) is None)
        ):
            raise AttentionError("bridge_status_invalid")
        return dict(value)

    return _call(
        "proactive-conversation", "status", ["--conversation-id", conversation_id],
        validate, runner=runner,
    )


def bridge_deliver(
    conversation_id: str, *, runner: Callable[..., object] | None = None
) -> dict[str, object]:
    conversation_id = _id("bridge_conversation_id", conversation_id) or ""

    def validate(value):
        if value.get("ok") is False:
            if (
                set(value) == {"ok", "conversation_id", "state", "recovery"}
                and value.get("conversation_id") == conversation_id
                and value.get("state") == "delivery_unknown"
                and value.get("recovery") in {"not_found", "ambiguous"}
            ):
                return dict(value)
            raise AttentionError("bridge_deliver_invalid")
        allowed = {"ok", "conversation_id", "state", "message_id", "duplicate"}
        if (
            set(value) not in (allowed - {"duplicate"}, allowed)
            or value.get("ok") is not True
            or value.get("conversation_id") != conversation_id
            or value.get("state") not in BRIDGE_STATES - {"prepared", "sending", "delivery_unknown"}
            or (value.get("message_id") is not None and _id("bridge_message_id", value["message_id"]) is None)
            or ("duplicate" in value and value["duplicate"] is not True)
        ):
            raise AttentionError("bridge_deliver_invalid")
        return dict(value)

    return _call(
        "proactive-conversation", "deliver", ["--conversation-id", conversation_id],
        validate, runner=runner, returncodes=(0, 2),
    )


def _bridge_terminal(
    operation: str, conversation_id: str, outcome: str,
    runner: Callable[..., object] | None,
) -> dict[str, object]:
    conversation_id = _id("bridge_conversation_id", conversation_id) or ""
    outcome = _id("bridge_outcome", outcome) or ""
    target = "completed" if operation == "complete" else "cancelled"

    def validate(value):
        if value.get("ok") is False:
            if (
                set(value) == {"ok", "conversation_id", "state", "error"}
                and value.get("conversation_id") == conversation_id
                and value.get("state") == "sending"
                and value.get("error") == "send_in_progress"
            ):
                return {"ok": False, "conversation_id": conversation_id, "state": "sending", "error": "send_in_progress"}
            raise AttentionError(f"bridge_{operation}_invalid")
        allowed = {"ok", "conversation_id", "state", "duplicate"}
        if (
            set(value) not in (allowed - {"duplicate"}, allowed)
            or value.get("ok") is not True
            or value.get("conversation_id") != conversation_id
            or value.get("state") not in {target, "completed", "cancelled", "expired"}
            or ("duplicate" in value and value["duplicate"] is not True)
        ):
            raise AttentionError(f"bridge_{operation}_invalid")
        return dict(value)

    return _call(
        "proactive-conversation", operation,
        ["--conversation-id", conversation_id, "--outcome", outcome], validate,
        runner=runner, returncodes=(0, 2),
    )


def bridge_complete(
    conversation_id: str, outcome: str = "completed",
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    return _bridge_terminal("complete", conversation_id, outcome, runner)


def bridge_cancel(
    conversation_id: str, outcome: str = "cancelled",
    *, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    return _bridge_terminal("cancel", conversation_id, outcome, runner)


def consume_reply_proof(
    conversation_id: str, conversation_ref: str, submission_digest: str, reply_text: str,
    *, timeout: float = TIMEOUT_SECONDS, runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    conversation_id = _id("bridge_conversation_id", conversation_id) or ""
    conversation_ref = _id("conversation_ref", conversation_ref) or ""
    digest_arg = submission_digest.removeprefix("sha256:") if isinstance(submission_digest, str) else ""
    if (
        not HEX64_RE.fullmatch(digest_arg)
        or not isinstance(reply_text, str)
        or len(reply_text) > 4_000
        or not _number(timeout)
        or not 0 < timeout <= 30
    ):
        raise AttentionError("bridge_reply_proof_invalid")
    try:
        reply = reply_text.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise AttentionError("bridge_reply_proof_invalid") from None
    if len(reply) > MAX_REPLY_BYTES:
        raise AttentionError("bridge_reply_proof_invalid")

    def validate(value):
        if (
            set(value) != {"ok", "action", "idempotent", "conversation_id", "state"}
            or value.get("ok") is not True
            or value.get("action") != "consume-reply-proof"
            or type(value.get("idempotent")) is not bool
            or value.get("conversation_id") != conversation_id
            or value.get("state") not in BRIDGE_REPLY_STATES
        ):
            raise AttentionError("bridge_reply_proof_invalid")
        return dict(value)

    return _call(
        "proactive-conversation", "consume-reply-proof",
        ["--conversation-id", conversation_id, "--conversation-ref", conversation_ref,
         "--submission-digest", digest_arg],
        validate, input_data=reply, runner=runner, timeout=timeout,
    )


attention_begin_delivery = begin_delivery
attention_complete = complete
attention_release = release
attention_cancel = cancel
attention_release_visible = release_visible
bridge_consume_reply_proof = consume_reply_proof
