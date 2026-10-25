from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def hermes_home() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home()


def gyurin_knowledge_root() -> Path:
    return hermes_home() / "knowledge" / "gyurin"


def is_under_gyurin_knowledge_root(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(gyurin_knowledge_root().resolve())
        return True
    except ValueError:
        return False


def _cfg_get(cfg: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    try:
        from hermes_cli.config import cfg_get

        return cfg_get(cfg, *keys, default=default)
    except Exception:
        node: Any = cfg
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


def _load_config_readonly() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        loaded = load_config_readonly()
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


@dataclass
class DebugConfig:
    log_decisions: bool = True
    inject_debug_note: bool = False


@dataclass
class PostTurnConfig:
    auto_write_domain_markdown: bool = True
    auto_write_honcho: bool = False
    raw_transcript_storage: str = "forbid"


@dataclass
class ClassifierConfig:
    provider: str = ""
    model: str = ""
    timeout: float = 20.0
    max_tokens: int = 4_000


@dataclass
class CurationConfig:
    mode: str = "disabled"
    policy_version: str = "curation-policy-v1"
    limit: int = 50
    max_age_days: int = 30
    max_evidence_per_candidate: int = 5
    max_excerpt_chars: int = 500
    max_decisions: int = 50
    api_timeout: float = 5.0
    llm_timeout: float = 60.0
    max_tokens: int = 4_000
    error: str = ""


@dataclass
class ReconciliationConfig:
    mode: str = "disabled"
    guild_id: str = ""
    approved_guild_id: str = ""
    channel_id: str = ""
    approved_channel_id: str = ""
    reconciliation_parent_channel_id: str = "<RECONCILIATION_PARENT_CHANNEL_ID>"
    owner_ids: tuple[str, ...] = ()
    operational_question_limit: int = 12
    hard_question_limit: int = 50
    candidate_limit: int = 200
    canonical_limit: int = 100
    entity_snapshot_limit: int = 1_000
    max_age_days: int = 30
    cooldown_seconds: int = 21_600
    initial_ttl_seconds: int = 86_400
    lease_idle_seconds: int = 1_800
    api_timeout: float = 10.0
    llm_timeout: float = 60.0
    max_tokens: int = 8_000
    max_message_chars: int = 1_900
    error: str = ""


@dataclass
class EnrichmentConfig:
    mode: str = "disabled"
    guild_id: str = ""
    channel_id: str = ""
    parent_channel_id: str = ""
    owner_ids: tuple[str, ...] = ()
    protected_self_entity_id: str = ""
    initial_ttl_seconds: int = 86_400
    lease_idle_seconds: int = 1_800
    api_timeout: float = 10.0
    max_message_chars: int = 180
    global_cooldown_seconds: int = 259_200
    weekly_limit: int = 2
    quiet_start: str = "22:00"
    quiet_end: str = "09:00"
    timezone: str = "Asia/Seoul"
    unknown_suppression_days: int = 90
    later_snooze_days: int = 30
    second_later_snooze_days: int = 180
    error: str = ""


@dataclass
class KinlayerConfig:
    enabled: bool = False
    base_url: str = ""
    timeout: float = 5.0
    curation: CurationConfig = field(default_factory=CurationConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    memory_state_dir: str = ""


@dataclass
class RouterConfig:
    enabled: bool = False
    memory_provider: str = ""
    dry_run: bool = True
    policy_skill: str = "gyurin-personal-context"
    manifest_path: str = "references/router.yaml"
    domain_map_path: str = "references/domain-map.yaml"
    storage_policy_path: str = "references/storage-policy.yaml"
    post_turn: PostTurnConfig = field(default_factory=PostTurnConfig)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    kinlayer: KinlayerConfig = field(default_factory=KinlayerConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    def skill_root(self) -> Path:
        return hermes_home() / "skills" / "productivity" / self.policy_skill

    def resolve_skill_path(self, relative_path: str) -> Path:
        path = Path(relative_path).expanduser()
        if path.is_absolute():
            return path
        return self.skill_root() / path


def load_router_config(
    config_loader: Callable[[], dict[str, Any]] | None = None,
) -> RouterConfig:
    cfg = (config_loader or _load_config_readonly)()
    section = _cfg_get(cfg, "runtime_context_router", default=None)
    if not isinstance(section, dict):
        return RouterConfig()

    return RouterConfig(
        enabled=bool(_cfg_get(cfg, "runtime_context_router", "enabled", default=False)),
        memory_provider=str(_cfg_get(cfg, "memory", "provider", default="") or "").strip(),
        dry_run=bool(_cfg_get(cfg, "runtime_context_router", "dry_run", default=True)),
        policy_skill=str(
            _cfg_get(
                cfg,
                "runtime_context_router",
                "policy_skill",
                default="gyurin-personal-context",
            )
            or "gyurin-personal-context"
        ),
        manifest_path=str(
            _cfg_get(
                cfg,
                "runtime_context_router",
                "manifest_path",
                default="references/router.yaml",
            )
            or "references/router.yaml"
        ),
        domain_map_path=str(
            _cfg_get(
                cfg,
                "runtime_context_router",
                "domain_map_path",
                default="references/domain-map.yaml",
            )
            or "references/domain-map.yaml"
        ),
        storage_policy_path=str(
            _cfg_get(
                cfg,
                "runtime_context_router",
                "storage_policy_path",
                default="references/storage-policy.yaml",
            )
            or "references/storage-policy.yaml"
        ),
        post_turn=PostTurnConfig(
            auto_write_domain_markdown=bool(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "post_turn",
                    "auto_write_domain_markdown",
                    default=True,
                )
            ),
            auto_write_honcho=bool(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "post_turn",
                    "auto_write_honcho",
                    default=False,
                )
            ),
            raw_transcript_storage=str(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "post_turn",
                    "raw_transcript_storage",
                    default="forbid",
                )
                or "forbid"
            ),
        ),
        classifier=ClassifierConfig(
            provider=str(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "classifier",
                    "provider",
                    default="",
                )
                or ""
            ),
            model=str(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "classifier",
                    "model",
                    default="",
                )
                or ""
            ),
            timeout=float(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "classifier",
                    "timeout",
                    default=20.0,
                )
                or 20.0
            ),
            max_tokens=int(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "classifier",
                    "max_tokens",
                    default=4_000,
                )
                or 4_000
            ),
        ),
        kinlayer=KinlayerConfig(
            memory_state_dir=str(_cfg_get(cfg, "runtime_context_router", "kinlayer", "memory_state_dir", default="") or ""),
            enabled=bool(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "kinlayer",
                    "enabled",
                    default=False,
                )
            ),
            base_url=str(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "kinlayer",
                    "base_url",
                    default=os.environ.get("KINLAYER_API_URL", ""),
                )
                or ""
            ).rstrip("/"),
            timeout=float(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "kinlayer",
                    "timeout",
                    default=5.0,
                )
                or 5.0
            ),
            curation=_load_curation_config(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "kinlayer",
                    "curation",
                    default={},
                )
            ),
            reconciliation=_load_reconciliation_config(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "kinlayer",
                    "reconciliation",
                    default={},
                )
            ),
            enrichment=_load_enrichment_config(
                _cfg_get(
                    cfg, "runtime_context_router", "kinlayer", "enrichment", default={}
                )
            ),
        ),
        debug=DebugConfig(
            log_decisions=bool(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "debug",
                    "log_decisions",
                    default=True,
                )
            ),
            inject_debug_note=bool(
                _cfg_get(
                    cfg,
                    "runtime_context_router",
                    "debug",
                    "inject_debug_note",
                    default=False,
                )
            ),
        ),
    )


def apply_plugin_settings(config: RouterConfig, settings: Any) -> RouterConfig:
    """Overlay the plugin-owned Phase 5 settings without changing legacy routing."""
    if not isinstance(settings, dict):
        return config
    kinlayer = settings.get("kinlayer")
    if not isinstance(kinlayer, dict):
        return config
    if "memory_state_dir" in kinlayer:
        config.kinlayer.memory_state_dir = str(kinlayer.get("memory_state_dir") or "").strip()
    if "base_url" in kinlayer:
        config.kinlayer.base_url = str(kinlayer.get("base_url") or "").strip().rstrip("/")
    if "curation" in kinlayer:
        config.kinlayer.curation = _load_curation_config(kinlayer.get("curation"))
    if "reconciliation" in kinlayer:
        config.kinlayer.reconciliation = _load_reconciliation_config(
            kinlayer.get("reconciliation")
        )
    if "enrichment" in kinlayer:
        config.kinlayer.enrichment = _load_enrichment_config(kinlayer.get("enrichment"))
    return config


def _load_curation_config(raw: Any) -> CurationConfig:
    section = raw if isinstance(raw, dict) else {}
    mode = str(section.get("mode") or "disabled").strip().casefold()
    error = "" if mode in {"disabled", "shadow", "apply"} else "invalid_curation_mode"
    if error:
        mode = "disabled"
    policy_version = str(section.get("policy_version") or "curation-policy-v1").strip()
    if not policy_version or len(policy_version) > 120:
        error = error or "invalid_curation_policy_version"
        mode = "disabled"
    return CurationConfig(
        mode=mode,
        policy_version=policy_version,
        limit=_bounded_int(section.get("limit"), 50, 1, 200),
        max_age_days=_bounded_int(section.get("max_age_days"), 30, 1, 365),
        max_evidence_per_candidate=_bounded_int(
            section.get("max_evidence_per_candidate"), 5, 1, 20
        ),
        max_excerpt_chars=_bounded_int(section.get("max_excerpt_chars"), 500, 1, 500),
        max_decisions=_bounded_int(section.get("max_decisions"), 50, 1, 200),
        api_timeout=_bounded_float(section.get("api_timeout"), 5.0, 0.25, 30.0),
        llm_timeout=_bounded_float(section.get("llm_timeout"), 60.0, 1.0, 120.0),
        max_tokens=_bounded_int(section.get("max_tokens"), 4_000, 256, 16_000),
        error=error,
    )


def _load_reconciliation_config(raw: Any) -> ReconciliationConfig:
    section = raw if isinstance(raw, dict) else {}
    mode = str(section.get("mode") or "disabled").strip().casefold()
    error = "" if mode in {"disabled", "enabled"} else "invalid_reconciliation_mode"
    if error:
        mode = "disabled"
    owner_ids_raw = section.get("owner_ids", [])
    if isinstance(owner_ids_raw, (str, int)):
        owner_ids_raw = [owner_ids_raw]
    owner_ids = tuple(
        value
        for value in (str(item).strip() for item in owner_ids_raw if item is not None)
        if value.isdigit() and len(value) <= 32
    )[:20]
    operational = _bounded_int(section.get("operational_question_limit"), 12, 1, 100)
    hard = _bounded_int(section.get("hard_question_limit"), 50, 1, 200)
    if operational > hard:
        operational = hard
    return ReconciliationConfig(
        mode=mode,
        guild_id=str(section.get("guild_id") or "").strip(),
        approved_guild_id=str(section.get("approved_guild_id") or "").strip(),
        channel_id=str(section.get("channel_id") or "").strip(),
        approved_channel_id=str(section.get("approved_channel_id") or "").strip(),
        reconciliation_parent_channel_id=str(
            section.get("reconciliation_parent_channel_id")
            or "<RECONCILIATION_PARENT_CHANNEL_ID>"
        ).strip(),
        owner_ids=owner_ids,
        operational_question_limit=operational,
        hard_question_limit=hard,
        candidate_limit=_bounded_int(section.get("candidate_limit"), 200, 1, 500),
        canonical_limit=_bounded_int(section.get("canonical_limit"), 100, 1, 500),
        entity_snapshot_limit=_bounded_int(
            section.get("entity_snapshot_limit"), 1_000, 200, 5_000
        ),
        max_age_days=_bounded_int(section.get("max_age_days"), 30, 1, 365),
        cooldown_seconds=_bounded_int(section.get("cooldown_seconds"), 21_600, 0, 604_800),
        initial_ttl_seconds=_bounded_int(
            section.get("initial_ttl_seconds"), 86_400, 300, 604_800
        ),
        lease_idle_seconds=_bounded_int(
            section.get("lease_idle_seconds"), 1_800, 1_800, 3_600
        ),
        api_timeout=_bounded_float(section.get("api_timeout"), 10.0, 0.25, 30.0),
        llm_timeout=_bounded_float(section.get("llm_timeout"), 60.0, 1.0, 120.0),
        max_tokens=_bounded_int(section.get("max_tokens"), 8_000, 256, 32_000),
        max_message_chars=_bounded_int(section.get("max_message_chars"), 1_900, 500, 2_000),
        error=error,
    )


def _load_enrichment_config(raw: Any) -> EnrichmentConfig:
    section = raw if isinstance(raw, dict) else {}
    mode = str(section.get("mode") or "disabled").strip().casefold()
    error = "" if mode in {"disabled", "enabled"} else "invalid_enrichment_mode"
    if error:
        mode = "disabled"
    raw_owners = section.get("owner_ids", [])
    if isinstance(raw_owners, (str, int)):
        raw_owners = [raw_owners]
    owners = tuple(str(v).strip() for v in raw_owners if str(v).strip())[:20]
    def exact_int(name: str, default: int, lower: int, upper: int) -> int:
        nonlocal error, mode
        raw_value = section.get(name, default)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
            error = error or f"invalid_enrichment_{name}"
        if not lower <= value <= upper:
            error = error or f"invalid_enrichment_{name}"
            mode = "disabled"
        return value
    def exact_float(name: str, default: float, lower: float, upper: float) -> float:
        nonlocal error, mode
        try:
            value = float(section.get(name, default))
        except (TypeError, ValueError):
            value = default
            error = error or f"invalid_enrichment_{name}"
        if not lower <= value <= upper:
            error = error or f"invalid_enrichment_{name}"
            mode = "disabled"
        return value
    result = EnrichmentConfig(
        mode=mode,
        guild_id=str(section.get("guild_id") or "").strip(),
        channel_id=str(section.get("channel_id") or "").strip(),
        parent_channel_id=str(section.get("parent_channel_id") or "").strip(),
        owner_ids=owners,
        protected_self_entity_id=str(section.get("protected_self_entity_id") or "").strip(),
        initial_ttl_seconds=exact_int("initial_ttl_seconds", 86_400, 300, 604_800),
        lease_idle_seconds=exact_int("lease_idle_seconds", 1_800, 60, 86_400),
        api_timeout=exact_float("api_timeout", 10.0, 0.25, 30.0),
        max_message_chars=exact_int("max_message_chars", 180, 40, 180),
        global_cooldown_seconds=exact_int("global_cooldown_seconds", 259_200, 0, 604_800),
        weekly_limit=exact_int("weekly_limit", 2, 1, 7),
        quiet_start=str(section.get("quiet_start") or "22:00"),
        quiet_end=str(section.get("quiet_end") or "09:00"),
        timezone=str(section.get("timezone") or "Asia/Seoul"),
        unknown_suppression_days=exact_int("unknown_suppression_days", 90, 1, 365),
        later_snooze_days=exact_int("later_snooze_days", 30, 1, 180),
        second_later_snooze_days=exact_int("second_later_snooze_days", 180, 31, 365),
        error=error,
    )
    if result.mode == "enabled":
        numeric = re.compile(r"^[0-9]{1,32}$")
        if not numeric.fullmatch(result.guild_id) or not numeric.fullmatch(result.channel_id) or not numeric.fullmatch(result.parent_channel_id):
            result.error = result.error or "invalid_enrichment_route"
        elif len(result.owner_ids) != 1 or not numeric.fullmatch(result.owner_ids[0]):
            result.error = result.error or "invalid_enrichment_owner"
        elif not re.fullmatch(r"[A-Za-z0-9_.:-]{1,36}", result.protected_self_entity_id):
            result.error = result.error or "invalid_enrichment_protected_self"
        elif result.timezone != "Asia/Seoul" or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", result.quiet_start) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", result.quiet_end):
            result.error = result.error or "invalid_enrichment_quiet_hours"
        if result.error:
            result.mode = "disabled"
    return result


def _bounded_int(value: Any, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def _bounded_float(value: Any, default: float, lower: float, upper: float) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))
