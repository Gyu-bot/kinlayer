from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import RouterConfig

try:
    import yaml
except Exception:  # pragma: no cover - depends on Hermes environment
    yaml = None  # type: ignore[assignment]


@dataclass
class ManifestBundle:
    router: dict[str, Any] = field(default_factory=dict)
    domain_map: dict[str, Any] = field(default_factory=dict)
    storage_policy: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)
    mtimes: dict[str, float] = field(default_factory=dict)
    loaded_at: float = 0.0
    error: str = ""


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


class ManifestLoader:
    def __init__(self) -> None:
        self._bundle = ManifestBundle()

    def load_if_changed(self, config: RouterConfig) -> ManifestBundle:
        paths = {
            "router": config.resolve_skill_path(config.manifest_path),
            "domain_map": config.resolve_skill_path(config.domain_map_path),
            "storage_policy": config.resolve_skill_path(config.storage_policy_path),
        }
        mtimes = {
            key: path.stat().st_mtime if path.exists() else -1.0
            for key, path in paths.items()
        }
        if (
            self._bundle.loaded_at
            and self._bundle.paths == paths
            and self._bundle.mtimes == mtimes
        ):
            return self._bundle

        bundle = ManifestBundle(paths=paths, mtimes=mtimes, loaded_at=time.time())
        if yaml is None:
            bundle.error = "pyyaml_unavailable"
            self._bundle = bundle
            return bundle

        try:
            bundle.router = _safe_load_yaml(paths["router"])
            bundle.domain_map = _safe_load_yaml(paths["domain_map"])
            bundle.storage_policy = _safe_load_yaml(paths["storage_policy"])
        except Exception as exc:
            bundle.error = f"manifest_load_error:{type(exc).__name__}"
        self._bundle = bundle
        return bundle
