"""Hermes user plugin entrypoint for post-turn personal-memory triage."""
from __future__ import annotations
import json

from .router.config import apply_plugin_settings, load_router_config
from .router.curation import AUXILIARY_TASK, handle_cli, setup_cli
from .router.hooks import CLASSIFIER_AUXILIARY_TASK, get_router
from .router.reconciliation import (
    StateStore,
    handle_cli as handle_reconciliation_cli,
)
from .router.enrichment import EnrichmentStateStore, handle_cli as handle_enrichment_cli
from .router.identity import handle_cli as handle_identity_cli


_reconciliation_store = StateStore()
_enrichment_store = EnrichmentStateStore()
_plugin_settings = None


def _pre_llm_call(**kwargs):
    return get_router().pre_llm_call(**kwargs)


def _post_llm_call(**kwargs):
    if "HERMES-PCB-CLAIM-V1" in str(kwargs.get("user_message") or ""):
        return None
    return get_router().post_llm_call(**kwargs)


def _transform_llm_output(**kwargs):
    return get_router().transform_llm_output(**kwargs)


def _status_command(raw_args: str = "") -> str:
    return get_router().status(raw_args)


def _identity_tool(params, **kwargs):
    router = get_router()
    config = router._config()
    if not config.enabled or not config.kinlayer.enabled or config.dry_run:
        return json.dumps({"ok": False, "reason": "identity_handoff_disabled", "version": "0.15.0", "backend_queried": False, "writes": 0})
    return json.dumps(router._identity_state.tool(config, params, **kwargs), ensure_ascii=False)


def _identity_middleware(**kwargs):
    router = get_router()
    return router._identity_state.middleware(router._config(), **kwargs)


def register(ctx):
    global _reconciliation_store, _enrichment_store, _plugin_settings
    _plugin_settings = ctx.get_config("runtime_context_router", None)
    _reconciliation_store = StateStore(getattr(ctx, "state", None))
    _enrichment_store = EnrichmentStateStore(getattr(ctx, "state", None))
    try:
        get_router().set_llm(getattr(ctx, "llm", None))
        get_router().set_attention_stores(_reconciliation_store, _enrichment_store)
    except Exception:
        pass
    ctx.register_hook("post_llm_call", _post_llm_call)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("transform_llm_output", _transform_llm_output)
    ctx.register_middleware("tool_execution", _identity_middleware)
    ctx.register_tool(
        name="kinlayer_identity", toolset="kinlayer_identity", handler=_identity_tool,
        schema={"name": "kinlayer_identity", "description":
            "Current-agent Kinlayer identity handoff. lookup returns bounded source-backed candidates, never an identity verdict. "
            "Use your actual conversation to decide a clear name/variant, without ritual confirmation. "
            "decide requires lookup_token, selected candidate_id, supplied evidence_refs (entities:<id> is valid), "
            "exact native context_quotes, excluded_candidate_ids covering other candidates, and your reasoning. "
            "Use unresolved and ask naturally only if genuinely unclear. No person creation, aliases, memory writes or historical replay. "
            "status is a harmless no-backend/no-write native-runtime probe. Never supply session/turn/sender/profile IDs.",
            "parameters": {"type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["lookup", "decide", "unresolved", "status"]},
                    "surface": {"type": "string", "description": "Exact name/reference present in this conversation."},
                    "hint_queries": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
                    "lookup_token": {"type": "string"}, "candidate_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "context_quotes": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "excluded_candidate_ids": {"type": "array", "items": {"type": "string"}},
                    "mention_surfaces": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                        "description": "Explicit same-person spellings/references to authorize, including lookup surface. No automatic writer spelling expansion."},
                    "reason": {"type": "string"}}, "required": ["action"]}},
    )
    ctx.register_auxiliary_task(
        key=AUXILIARY_TASK,
        display_name="Kinlayer periodic curation",
        description="Plan bounded relationship-memory curation runs.",
        defaults={"provider": "auto", "timeout": 60},
    )
    ctx.register_auxiliary_task(
        key=CLASSIFIER_AUXILIARY_TASK,
        display_name="Personal context post-turn classifier",
        description="Classify post-turn personal-memory relevance independently of the conversation model.",
        defaults={"provider": "auto", "timeout": 20},
    )
    ctx.register_cli_command(
        name="context-router",
        help="Run or inspect personal-context router maintenance",
        setup_fn=setup_cli,
        handler_fn=lambda args: (
            handle_identity_cli(args, config=apply_plugin_settings(load_router_config(), ctx.get_config("runtime_context_router", None)))
            if str(getattr(args, "context_router_command", "")) == "identity-resolve"
            else handle_reconciliation_cli(
                args,
                config=apply_plugin_settings(load_router_config(), ctx.get_config("runtime_context_router", None)),
                store=_reconciliation_store,
            )
            if str(getattr(args, "context_router_command", "")).startswith("reconciliation-")
            else handle_enrichment_cli(
                args,
                config=apply_plugin_settings(load_router_config(), ctx.get_config("runtime_context_router", None)),
                store=_enrichment_store,
                reconciliation_store=_reconciliation_store,
            )
            if str(getattr(args, "context_router_command", "")).startswith("enrichment-")
            else handle_cli(
                args,
                config=apply_plugin_settings(load_router_config(), ctx.get_config("runtime_context_router", None)),
                llm=ctx.llm,
            )
        ),
        description="Bounded Kinlayer periodic curation and exact run status.",
    )

    register_command = getattr(ctx, "register_command", None)
    if callable(register_command):
        register_command(
            "pcr-status",
            _status_command,
            description="Show personal context router status.",
        )
        register_command(
            "context-router-status",
            _status_command,
            description="Show personal context router status.",
        )
