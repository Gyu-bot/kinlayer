from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import hermes_home


KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential)\s*[:=]\s*['\"]?[^\\s,'\"]+"
)
SECRET_LIKE_VALUE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|credential)(?:[_-][a-z0-9]+){1,}\b"
)


def redact(text: str, limit: int = 120) -> str:
    value = KEY_VALUE_SECRET_RE.sub(r"\1=[REDACTED]", text or "")
    value = SECRET_LIKE_VALUE_RE.sub("[REDACTED]", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def decision_log_path() -> Path:
    return hermes_home() / "logs" / "context-router.jsonl"


def append_decision(event: dict[str, Any]) -> None:
    path = decision_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def tail_log(lines: int = 5) -> list[str]:
    path = decision_log_path()
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
