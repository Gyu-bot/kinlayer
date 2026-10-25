from __future__ import annotations

import atexit
import json
import hashlib
import queue
import threading
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .config import RouterConfig, load_router_config
from .cultural import normalize_cultural_item
from .dimensions import DimensionClassifier, DimensionResult, extract_dimensions
from .logging import append_decision, redact, tail_log
from .manifest import ManifestLoader
from .policy import PolicyDecision, evaluate_policies
from .post_turn import process_post_turn, _source_occurred_at, _memory_journal, _memory_turn_identity, _canonical_json, _classification_relationship_ontology
from .read import build_personal_context
from .attention import AttentionError, attention_signal
from .enrichment import EnrichmentStateStore, attention_signal_matches as enrichment_attention_matches
from .reconciliation import StateStore, attention_signal_matches as reconciliation_attention_matches


CLASSIFIER_AUXILIARY_TASK = "personal_context_router_classifier"


_POST_TURN_QUEUE_SIZE = 64
_POST_TURN_ATEXIT_TIMEOUT = 1.0
_POST_TURN_STOP = object()
_RECENT_TURN_LIMIT = 1024


def _private_identity_route(config: RouterConfig) -> bool:
    """PCB-only routes must never gain generic person prefetch or extraction."""
    protected = {
        str(value) for value in (
            config.kinlayer.reconciliation.channel_id,
            config.kinlayer.enrichment.channel_id,
        ) if value
    }
    if not protected:
        return False
    try:
        from gateway.session_context import get_session_env
        if get_session_env("HERMES_SESSION_PLATFORM", "") != "discord":
            return False
        route = {
            get_session_env(key, "") for key in (
                "HERMES_SESSION_CHAT_ID", "HERMES_SESSION_THREAD_ID",
                "HERMES_SESSION_PARENT_CHAT_ID",
            )
        }
        return bool(protected & route)
    except ImportError:
        return False  # Standalone local CLI has no Gateway channel.


class PersonalContextRouter:
    """Native identity clarification and post-turn source-only personal memory."""

    def __init__(
        self,
        config_loader: Callable[[], RouterConfig] | None = None,
        manifest_loader: ManifestLoader | None = None,
        dimension_classifier: DimensionClassifier | None = None,
        plugin_llm: Any | None = None,
        hindsight_config_loader: Callable[[], dict[str, Any]] | None = None,
        http_transport: Callable[[str, dict[str, Any], dict[str, str], float], Any] | None = None,
        secret_loader: Callable[[str], str] | None = None,
        synchronous_post_turn: bool = False,
        queue_size: int = _POST_TURN_QUEUE_SIZE,
    ) -> None:
        self._config_loader = config_loader
        self._manifest_loader = manifest_loader or ManifestLoader()
        self._dimension_classifier = dimension_classifier
        self._plugin_llm = plugin_llm
        from .identity import NativeIdentityState
        self._identity_state = NativeIdentityState()
        self._hindsight_config_loader = hindsight_config_loader
        self._http_transport = http_transport
        self._secret_loader = secret_loader
        self._synchronous_post_turn = synchronous_post_turn
        self._post_turn_queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, queue_size))
        self._worker_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._deferred_telemetry_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._stop_enqueued = False
        self._pending_turn_keys: set[tuple[str, str]] = set()
        self._in_flight_turn_keys: set[tuple[str, str]] = set()
        self._completed_turn_keys: deque[tuple[str, str]] = deque()
        self._completed_turn_key_set: set[tuple[str, str]] = set()
        self._deferred_telemetry: deque[dict[str, Any]] = deque(maxlen=64)
        self._reconciliation_store: StateStore | None = None
        self._enrichment_store: EnrichmentStateStore | None = None
        self._attention_runner: Any = None

    def set_llm(self, plugin_llm: Any | None) -> None:
        self._plugin_llm = plugin_llm

    def set_attention_stores(self, reconciliation_store: StateStore, enrichment_store: EnrichmentStateStore, runner: Any = None) -> None:
        self._reconciliation_store = reconciliation_store
        self._enrichment_store = enrichment_store
        self._attention_runner = runner

    def _signal_attention(self, config: RouterConfig, identities: Any, trusted_source: bool) -> str:
        if not trusted_source:
            return "untrusted_source"
        if self._reconciliation_store is None or self._enrichment_store is None:
            return "no_match"
        if not isinstance(identities, list):
            return "no_exact_identity"
        allowed_types = {"alias", "profile_field", "relationship_edge", "observation"}
        identity_ids = {
            str(value)
            for identity in identities
            if isinstance(identity, Mapping) and identity.get("candidate_type") in allowed_types
            for value in identity.get("ids", [])
            if isinstance(value, str) and value
        }
        if not identity_ids:
            return "no_exact_identity"
        matches = [
            *reconciliation_attention_matches(self._reconciliation_store, identity_ids),
            *enrichment_attention_matches(self._enrichment_store, identity_ids, config.kinlayer.enrichment),
        ]
        unique = {}
        for match in matches:
            route = match["route"]
            key = (
                str(match["producer"]),
                str(route.get("platform") or "").lower(),
                str(route.get("scope_id") or ""),
                str(route.get("channel_id") or ""),
                str(route.get("thread_id") or ""),
                str(route.get("owner_id") or ""),
                str(match["context_tag"]),
            )
            unique.setdefault(key, match)
        if not unique:
            return "no_match"
        succeeded = 0
        for key in sorted(unique):
            match = unique[key]
            try:
                attention_signal(match["route"], match["producer"], match["context_tag"], runner=self._attention_runner)
                succeeded += 1
            except (AttentionError, OSError, RuntimeError, ValueError):
                pass
        if succeeded == len(unique):
            return "signaled" if succeeded == 1 else "signaled_multiple"
        return "partial_failed" if succeeded else "failed"

    def _config(self) -> RouterConfig:
        if self._config_loader is not None:
            return self._config_loader()
        return load_router_config()

    def pre_llm_call(self, **kwargs: Any):
        """Open a current-agent native identity frame; no auxiliary decider."""
        from .identity import pending_context
        if (kwargs.get("verified_reconciliation_reply") or kwargs.get("skip_post_turn_extraction")
                or "HERMES-PCB-CLAIM-V1" in str(kwargs.get("user_message") or "")
                or _non_user_turn_reason(kwargs) or _synthetic_user_message_reason(str(kwargs.get("user_message") or ""))):
            return None
        config = self._config()
        if not config.enabled or not config.kinlayer.enabled or _private_identity_route(config):
            return None
        if config.dry_run:
            return None
        from .identity import _scope
        scope = _scope(config, kwargs)
        return self._identity_state.pre(config, self._plugin_llm, kwargs) or pending_context(
            config, str(kwargs.get("session_id") or ""), scope[3] if scope else None)

    def transform_llm_output(self, **kwargs: Any):
        """Deterministic, rate-limited identity question for genuine ambiguity only."""
        try:
            config = self._config()
            if (not config.enabled or not config.kinlayer.enabled or config.dry_run
                    or _private_identity_route(config)):
                return None
            return self._identity_state.transform(config, kwargs)
        except Exception:
            return None

    def personal_context(self, args: Any) -> str:
        try:
            config = self._config()
            if not config.enabled:
                return _empty_personal_context("router_disabled")
            bundle = self._manifest_loader.load_if_changed(config)
            return build_personal_context(
                args,
                bundle=bundle,
                hindsight_active=config.memory_provider.casefold() == "hindsight",
                hindsight_config_loader=self._hindsight_config_loader,
                http_transport=self._http_transport,
                secret_loader=self._secret_loader,
            )
        except Exception as exc:
            return _empty_personal_context(f"personal_context_failed:{type(exc).__name__}")

    def post_llm_call(self, **kwargs: Any):
        start = time.monotonic()
        turn_id = str(kwargs.get("turn_id") or "")
        session_id = str(kwargs.get("session_id") or "")
        user_message = str(kwargs.get("user_message") or "")
        try:
            config = self._config()
            if not config.enabled:
                return None

            if kwargs.get("verified_reconciliation_reply") or kwargs.get("skip_post_turn_extraction") or _private_identity_route(config):
                return None

            synthetic_reason = _non_user_turn_reason(kwargs) or _synthetic_user_message_reason(user_message)
            if synthetic_reason:
                if config.debug.log_decisions:
                    self._append_telemetry(
                        {
                            "event": "post_turn",
                            "mode": "post_turn_memory_triage",
                            "turn_id": turn_id,
                            "session_id": session_id,
                            "task_id": str(kwargs.get("task_id") or ""),
                            "result": {"action": "ignored", "reason": synthetic_reason},
                            "latency_ms": _elapsed_ms(start),
                            "perf": {"total_ms": _elapsed_ms(start)},
                            "llm_usage": _extract_llm_usage(kwargs),
                        }
                    )
                return None

            snapshot = _snapshot_post_turn_kwargs(
                kwargs, user_message,
                trusted_signal_source=_trusted_signal_source(config, kwargs, user_message),
            )
            # Only this router's exact native pre-turn can attach identity results.
            # Caller-supplied history/IDs are not copied into the worker snapshot.
            snapshot.update(self._identity_state.post(config, self._plugin_llm, kwargs))
            from contextvars import copy_context
            from hermes_constants import set_hermes_home_override
            from .config import hermes_home
            context = copy_context()
            context.run(set_hermes_home_override, hermes_home())
            job = (config, snapshot, context)
            if self._synchronous_post_turn:
                reason = ""
                with self._worker_lock:
                    if self._closed:
                        return None
                    turn_key = _post_turn_key(job[1])
                    if self._turn_known_locked(turn_key):
                        reason = "duplicate_turn"
                    elif turn_key:
                        self._in_flight_turn_keys.add(turn_key)
                if reason:
                    self._queue_telemetry(reason)
                    return None
                outcome = "completed"
                try:
                    outcome = self._run_post_turn(job)
                finally:
                    with self._worker_lock:
                        self._finish_turn_locked(turn_key, outcome)
            else:
                self._enqueue_post_turn(job)
            return None
        except Exception as exc:
            self._defer_telemetry(
                {
                    "event": "error",
                    "hook": "post_llm_call",
                    "error": type(exc).__name__,
                    "latency_ms": _elapsed_ms(start),
                }
            )
            return None

    def _run_post_turn(self, job: tuple) -> str:
        # Background jobs must retain the admitting profile, not process HERMES_HOME.
        if len(job) == 3:
            return job[2].run(self._run_post_turn_scoped, job[:2])
        return self._run_post_turn_scoped(job)

    def _run_post_turn_scoped(self, job: tuple[RouterConfig, dict[str, Any]]) -> str:
        config, kwargs = job
        start = time.monotonic()
        perf: dict[str, int] = {}
        turn_id = str(kwargs.get("turn_id") or "")
        session_id = str(kwargs.get("session_id") or "")
        user_message = str(kwargs.get("user_message") or "")
        dimensions: DimensionResult | None = None
        decision: PolicyDecision | None = None
        result: dict[str, Any] = {"action": "ignored", "reason": "not_started"}
        persistence_may_have_begun = False
        try:
            deferred = {}  # Old deferred claims are history, never semantic-decision replay.
            if deferred:
                perf["deferred_identity_ms"] = _elapsed_ms(start)
            stage_start = time.monotonic()
            bundle = self._manifest_loader.load_if_changed(config)
            perf["manifest_load_ms"] = _elapsed_ms(stage_start)
            if bundle.error:
                result = {"action": "ignored", "reason": "manifest_error", "error": bundle.error}
            else:
                stage_start = time.monotonic()
                dimensions, llm_decision_patch = self._accepted_post_turn_extraction(config, kwargs, bundle)
                perf["dimension_extract_ms"] = _elapsed_ms(stage_start)

                if dimensions.low_signal_skip:
                    result = {
                        "action": "ignored",
                        "reason": dimensions.hard_skip_reason or dimensions.extraction_reason,
                    }
                elif not dimensions.classifier_available:
                    result = {"action": "ignored", "reason": dimensions.extraction_reason}
                else:
                    stage_start = time.monotonic()
                    decision = evaluate_policies(bundle, dimensions)
                    self._apply_llm_decision_patch(decision, llm_decision_patch)
                    perf["policy_eval_ms"] = _elapsed_ms(stage_start)
                    persistence_may_have_begun = True
                    result = process_post_turn(config, bundle, decision, telemetry=perf, plugin_llm=self._plugin_llm, **kwargs)
                    identities = result.pop("_attention_identity", None)
                    if identities:
                        result["attention_signal"] = self._signal_attention(
                            config, identities, bool(kwargs.get("trusted_signal_source"))
                        )

            if deferred:
                result["deferred_identity"] = deferred
            if config.debug.log_decisions:
                perf["total_ms"] = _elapsed_ms(start)
                payload: dict[str, Any] = {
                    "event": "post_turn",
                    "mode": "post_turn_memory_triage",
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "task_id": str(kwargs.get("task_id") or ""),
                    "result": result,
                    "latency_ms": _elapsed_ms(start),
                    "perf": perf,
                    "llm_usage": dict(kwargs.get("llm_usage") or {"available": False}),
                }
                if dimensions is not None:
                    payload["dimensions"] = dimensions.dimensions
                    payload["domains"] = dimensions.domains
                    payload["tool_needs"] = dimensions.tool_needs
                    payload["classifier_available"] = dimensions.classifier_available
                    payload["extraction_reason"] = dimensions.extraction_reason
                if decision is not None:
                    payload["selected_sources"] = decision.selected_sources
                    payload["post_turn_candidate"] = decision.post_turn_target
                    payload["raw_transcript_storage"] = decision.raw_transcript_storage
                    if decision.cultural_item:
                        payload["cultural_item"] = decision.cultural_item
                    if decision.kinlayer_memories:
                        payload["kinlayer_memory_count"] = len(decision.kinlayer_memories)
                self._append_telemetry(payload)
        except Exception as exc:
            self._append_telemetry(
                {
                    "event": "error",
                    "hook": "post_llm_call_worker",
                    "error": type(exc).__name__,
                    "outcome_class": (
                        "at_most_once_completed"
                        if persistence_may_have_begun
                        else "retryable_pre_persistence"
                    ),
                    "latency_ms": _elapsed_ms(start),
                    "perf": {"total_ms": _elapsed_ms(start), **perf},
                }
            )
            return "completed" if persistence_may_have_begun else "retryable_pre_persistence"
        return "completed"

    def _resolve_deferred_identity(self, config: RouterConfig, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Apply the user's answer to an earlier identity question, independent of
        whether this short reply itself contains anything worth remembering."""
        confirmed, discard = kwargs.get("_identity_confirmed") or {}, kwargs.get("_identity_discard") or []
        scope = kwargs.get("_identity_scope")
        if not scope or not (confirmed or discard):
            return {}
        from .post_turn import discard_deferred_claims, replay_confirmed_claims
        outcome: dict[str, Any] = {}
        try:
            if discard:
                outcome["discarded"] = sum(discard_deferred_claims(config, scope, s) for s in discard)
            if confirmed:
                outcome["replayed"] = replay_confirmed_claims(config, scope, confirmed, self._plugin_llm)
        except Exception as exc:
            outcome["error"] = type(exc).__name__
        return outcome

    def _enqueue_post_turn(self, job: tuple) -> None:
        reason = ""
        with self._worker_lock:
            if self._closed:
                return
            turn_key = _post_turn_key(job[1])
            if self._turn_known_locked(turn_key):
                reason = "duplicate_turn"
            else:
                if not self._ensure_worker_locked():
                    return
                try:
                    self._post_turn_queue.put_nowait(job)
                    if turn_key:
                        self._pending_turn_keys.add(turn_key)
                except queue.Full:
                    reason = "queue_full"
        if reason:
            self._queue_telemetry(reason)

    def _ensure_worker_locked(self) -> bool:
        if self._worker is not None and self._worker.is_alive():
            return True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="personal-context-router-post-turn",
            daemon=True,
        )
        try:
            self._worker.start()
        except Exception as exc:
            self._worker = None
            self._append_telemetry(
                {
                    "event": "error",
                    "hook": "post_llm_call_worker_start",
                    "status": "failed",
                    "outcome_class": "retryable_pre_persistence",
                    "error": type(exc).__name__,
                }
            )
            return False
        return True

    def _turn_known_locked(self, turn_key: tuple[str, str] | None) -> bool:
        return bool(
            turn_key
            and (
                turn_key in self._pending_turn_keys
                or turn_key in self._in_flight_turn_keys
                or turn_key in self._completed_turn_key_set
            )
        )

    def _finish_turn_locked(self, turn_key: tuple[str, str] | None, outcome: str) -> None:
        if not turn_key:
            return
        self._pending_turn_keys.discard(turn_key)
        self._in_flight_turn_keys.discard(turn_key)
        if outcome == "retryable_pre_persistence":
            return
        if len(self._completed_turn_keys) >= _RECENT_TURN_LIMIT:
            self._completed_turn_key_set.discard(self._completed_turn_keys.popleft())
        self._completed_turn_keys.append(turn_key)
        self._completed_turn_key_set.add(turn_key)

    def _worker_loop(self) -> None:
        while True:
            self._drain_deferred_telemetry()
            try:
                job = self._post_turn_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            turn_key = None
            outcome = "completed"
            try:
                if job is _POST_TURN_STOP:
                    self._drain_deferred_telemetry()
                    return
                turn_key = _post_turn_key(job[1])
                with self._worker_lock:
                    self._pending_turn_keys.discard(turn_key)
                    if turn_key:
                        self._in_flight_turn_keys.add(turn_key)
                outcome = self._run_post_turn(job)
            except Exception as exc:
                outcome = "completed"
                self._append_telemetry(
                    {
                        "event": "error",
                        "hook": "post_llm_call_worker",
                        "error": type(exc).__name__,
                        "outcome_class": "at_most_once_completed",
                    }
                )
            finally:
                if job is not _POST_TURN_STOP:
                    with self._worker_lock:
                        self._finish_turn_locked(turn_key, outcome)
                self._drain_deferred_telemetry()
                self._post_turn_queue.task_done()

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait boundedly for all accepted post-turn work to finish."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._post_turn_queue.all_tasks_done:
            while self._post_turn_queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._post_turn_queue.all_tasks_done.wait(remaining)
        return True

    def shutdown(self, timeout: float = 1.0) -> bool:
        """Stop accepting work, drain within *timeout*, then stop the daemon worker."""
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            acquired = self._shutdown_lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        except Exception:
            acquired = False
        if not acquired:
            self._queue_telemetry("shutdown_timeout", synchronous=True)
            return False
        try:
            with self._worker_lock:
                if self._closed and (self._worker is None or not self._worker.is_alive()):
                    return True
                self._closed = True
                worker = self._worker
            if not self.flush(max(0.0, deadline - time.monotonic())):
                self._queue_telemetry("shutdown_timeout", synchronous=True)
                return False
            if worker is None:
                return True
            if not worker.is_alive():
                with self._worker_lock:
                    self._worker = None
                return True
            if not self._stop_enqueued:
                try:
                    self._post_turn_queue.put_nowait(_POST_TURN_STOP)
                    self._stop_enqueued = True
                except queue.Full:
                    self._queue_telemetry("stop_enqueue_failure", synchronous=True)
                    return False
            worker.join(max(0.0, deadline - time.monotonic()))
            if worker.is_alive():
                self._queue_telemetry("worker_join_timeout", synchronous=True)
                return False
            with self._worker_lock:
                self._worker = None
            return True
        finally:
            self._shutdown_lock.release()

    def _queue_telemetry(self, reason: str, *, synchronous: bool = False) -> None:
        payload = {
            "event": "queue",
            "hook": "post_llm_call",
            "status": "timeout" if reason in {
                "shutdown_timeout", "stop_enqueue_failure", "worker_join_timeout"
            } else "dropped",
            "reason": reason,
            "pending": self._post_turn_queue.qsize(),
            "capacity": self._post_turn_queue.maxsize,
        }
        (self._append_telemetry if synchronous else self._defer_telemetry)(payload)

    def _defer_telemetry(self, payload: dict[str, Any]) -> None:
        try:
            with self._deferred_telemetry_lock:
                self._deferred_telemetry.append(payload)
            with self._worker_lock:
                if not self._closed:
                    self._ensure_worker_locked()
        except Exception:
            pass

    def _drain_deferred_telemetry(self) -> None:
        while True:
            with self._deferred_telemetry_lock:
                if not self._deferred_telemetry:
                    return
                payload = self._deferred_telemetry.popleft()
            self._append_telemetry(payload)

    def _append_telemetry(self, payload: dict[str, Any]) -> None:
        try:
            with self._log_lock:
                append_decision(payload)
        except Exception:
            pass

    def _accepted_post_turn_extraction(self, config, kwargs, bundle):
        # Accept once before any writes; a restart must not ask the LLM to
        # paraphrase/reorder operations that may already have committed.
        from dataclasses import asdict
        def extract():
            return self._extract_post_turn_dimensions(
                config=config, user_message=kwargs["user_message"],
                prior_user_tail=str(kwargs.get("prior_user_tail") or ""), bundle=bundle,
                source_occurred_at=_source_occurred_at(kwargs, kwargs["user_message"]))
        if config.dry_run or not config.kinlayer.enabled:
            return extract()
        key = _memory_turn_identity(config, kwargs, kwargs["user_message"])
        with _memory_journal(config) as db:
            row = db.execute("SELECT snapshot FROM extractions WHERE turn_key = ?", (key,)).fetchone()
            if row:
                snapshot = json.loads(row[0])
            else:
                dimensions, patch = extract()
                if not dimensions.classifier_available:
                    return dimensions, patch
                patch = dict(patch)
                if isinstance(patch.get("kinlayer_memories"), list):
                    patch["kinlayer_memories"] = [_sanitize_memory_claim(item) if isinstance(item, Mapping) else {}
                                                  for item in patch["kinlayer_memories"][:9]]
                snapshot = {"dimensions": asdict(dimensions), "patch": patch,
                            "source_time": _source_occurred_at(kwargs, kwargs["user_message"])}
                db.execute("INSERT INTO extractions VALUES (?, ?)", (key, _canonical_json(snapshot)))
                db.commit()
        kwargs["_memory_turn_key"] = key
        kwargs["_memory_source_time"] = snapshot["source_time"]
        return DimensionResult(**snapshot["dimensions"]), snapshot["patch"]

    def _extract_post_turn_dimensions(
        self,
        *,
        config: RouterConfig,
        user_message: str,
        prior_user_tail: str,
        bundle,
        source_occurred_at: str | None = None,
    ) -> tuple[DimensionResult, dict[str, Any]]:
        if self._dimension_classifier is not None:
            try:
                raw = self._dimension_classifier(user_message)
            except Exception:
                return DimensionResult(extraction_reason="classifier_error"), {}
            dimensions = extract_dimensions(user_message, lambda _message: raw)
            patch = _decision_patch(raw) if isinstance(raw, Mapping) else {}
            return dimensions, patch
        if self._plugin_llm is None:
            return extract_dimensions(user_message, None), {}
        if not user_message.strip():
            return extract_dimensions(user_message, None), {}
        if len(user_message.strip()) <= 3:
            return extract_dimensions(user_message, None), {}
        try:
            result = self._plugin_llm.complete_structured(
                task=CLASSIFIER_AUXILIARY_TASK,
                instructions=_classification_instructions(bundle, _classification_relationship_ontology(config)),
                input=[
                    {
                        "type": "text",
                        "text": _classification_input(
                            user_message,
                            prior_user_tail,
                            bundle,
                            source_occurred_at,
                        ),
                    }
                ],
                json_mode=True,
                schema_name="personal_context_post_turn_memory_triage",
                temperature=0,
                max_tokens=max(1, int(config.classifier.max_tokens or 4_000)),
                timeout=float(config.classifier.timeout or 20.0),
                provider=(config.classifier.provider or None),
                model=(config.classifier.model or None),
                purpose="personal_context_post_turn_memory_triage",
            )
            parsed = result.parsed if isinstance(result.parsed, dict) else _json_object(result.text)
            if not isinstance(parsed, dict):
                return DimensionResult(extraction_reason="llm_classifier_parse_error"), {}
            dimensions = DimensionResult(
                dimensions=_coerce_scores(parsed.get("dimensions")),
                domains=_coerce_scores(parsed.get("domains")),
                tool_needs=_coerce_scores(parsed.get("tool_needs")),
                low_signal_skip=not bool(parsed.get("should_record", False)),
                hard_skip_reason="not_memory_relevant" if not bool(parsed.get("should_record", False)) else "",
                extraction_reason="plugin_llm_post_turn_classifier",
                classifier_available=True,
            )
            patch = _decision_patch(parsed)
            return dimensions, patch
        except Exception:
            return DimensionResult(extraction_reason="llm_classifier_error"), {}

    def _apply_llm_decision_patch(self, decision: PolicyDecision, patch: dict[str, Any]) -> None:
        target = str(patch.get("post_turn_target") or "").strip()
        active_domain_names = {
            str(domain.get("name") or "").strip()
            for domain in decision.active_domains
            if isinstance(domain, Mapping)
        }
        if target and target in active_domain_names:
            decision.post_turn_target = target
        summary = redact(str(patch.get("evidence_summary") or ""), 600).strip()
        if summary:
            decision.evidence_summary = summary
        derived = patch.get("derived_memory")
        if isinstance(derived, list):
            decision.derived_memory = [
                sanitized
                for item in derived[:12]
                if (sanitized := redact(str(item), 400).strip())
            ]
        subjects = patch.get("subjects")
        if isinstance(subjects, list):
            decision.subjects = [
                sanitized
                for item in subjects[:16]
                if (sanitized := redact(str(item), 160).strip())
            ]
        try:
            confidence = float(patch.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None:
            decision.confidence = max(0.0, min(1.0, confidence))
        decision.cultural_item = _sanitize_cultural_item(
            normalize_cultural_item(patch.get("cultural_item"))
        )
        memories = patch.get("kinlayer_memories")
        if isinstance(memories, list):
            # Keep source_quote untouched until its current-user substring check.
            # Do not silently drop excess claims and report a complete save.
            decision.kinlayer_memories = [
                _sanitize_memory_claim(item) if isinstance(item, Mapping) else {}
                for item in memories[:9]
            ]

    def status(self, raw_args: str = "") -> str:
        config = self._config()
        lines = [
            "personal-context-router",
            "mode: post_turn_memory_triage",
            f"enabled: {config.enabled}",
            f"dry_run: {config.dry_run}",
            f"policy_skill: {config.policy_skill}",
            f"log: {Path.home() / '.hermes' / 'logs' / 'context-router.jsonl'}",
        ]
        tail = tail_log(5)
        if tail:
            lines.append("last decisions:")
            lines.extend(f"- {line}" for line in tail)
        return "\n".join(lines)


_CULTURAL_FIELD_LIMITS = {
    "item_title": 200,
    "item_aliases": 120,
    "medium": 40,
    "season_or_version": 120,
    "edition_or_dlc": 120,
    "platform": 80,
    "experience_state": 80,
    "reaction": 300,
    "reaction_reason": 600,
    "comparison_target": 200,
    "mentioned_characters_or_roles": 160,
    "resolution_status": 40,
    "resolution_source": 40,
}


def _sanitize_cultural_item(item: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in item.items():
        if key == "resolution_confidence":
            sanitized[key] = value
            continue
        limit = _CULTURAL_FIELD_LIMITS.get(key, 300)
        if isinstance(value, list):
            clean_values = [
                clean
                for candidate in value[:8]
                if (clean := redact(str(candidate), limit).strip())
            ]
            if clean_values:
                sanitized[key] = clean_values
            continue
        clean = redact(str(value), limit).strip()
        if clean:
            sanitized[key] = clean
    return sanitized


_MEMORY_CLAIM_FIELDS = {
    "action", "record_type", "subject", "new_subject", "from_subject", "to_subject",
    "relation_type", "claim_text", "fact_type", "content", "value", "observation_type",
    "occurred_at", "valid_from", "valid_to", "related", "claim_basis", "confidence",
    "source_quote", "target_hint", "directed", "reason", "properties",
    "perspective_subject", "relationship_axis", "relationship_value",
}


def _sanitize_memory_claim(raw: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key in _MEMORY_CLAIM_FIELDS:
        value = raw.get(key)
        if isinstance(value, str):
            # Content/value mismatch must fail rather than be silently rewritten.
            result[key] = value[:4001]
        elif isinstance(value, (dict, list, bool, int, float)) or (key in raw and value is None):
            result[key] = value
    return result


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _empty_personal_context(uncertainty: str) -> str:
    return json.dumps(
        {
            "selected_sources": [],
            "context": [],
            "next_lookups": [],
            "uncertainties": [uncertainty],
            "latency_ms": 0,
            "hindsight": {"requested": False, "status": "not_requested", "count": 0},
        },
        sort_keys=True,
    )


_SYNTHETIC_MESSAGE_PREFIXES = (
    "Review the conversation above and update the skill library.",
    "Review the conversation above and consider saving to memory if appropriate.",
    "[IMPORTANT: The user has invoked",
    "[IMPORTANT: The \"",
    "[IMPORTANT: You are running as a scheduled cron job.",
    "[IMPORTANT: Background process",
    "[ASYNC TASK COMPLETE",
    "[ASYNC DELEGATION BATCH COMPLETE",
    "[Background process",
    "[CONTEXT COMPACTION",
    "[System note:",
)


def _non_user_turn_reason(kwargs: Mapping[str, Any]) -> str:
    """Reject generated execution turns using provenance Hermes already exposes."""
    platform = str(kwargs.get("platform") or "").strip().lower()
    if platform in {"subagent", "cron"}:
        return f"non_user_platform:{platform}"

    session_id = str(kwargs.get("session_id") or "").strip().lower()
    if session_id.startswith("cron_"):
        return "non_user_session:cron"

    task_id = str(kwargs.get("task_id") or "").strip().lower()
    if task_id.startswith("sa-"):
        return "delegated_agent_turn"
    return ""


def _synthetic_user_message_reason(user_message: str) -> str:
    """Return a no-write reason for system/synthetic prompts.

    The post-turn auditor may be invoked for gateway/system prompts or internal
    follow-up tasks. Those are not current-turn user-authored evidence and must
    never become personal-context records.
    """
    text = (user_message or "").lstrip()
    if not text:
        return "empty_user_message"
    if any(text.startswith(prefix) for prefix in _SYNTHETIC_MESSAGE_PREFIXES):
        return "synthetic_or_internal_prompt"
    # Skill autoload wrappers sometimes arrive with the Discord speaker prefix
    # preserved, e.g. "[sender] [IMPORTANT: ...]". Strip exactly one leading
    # bracketed speaker label and re-check.
    if text.startswith("["):
        end = text.find("]")
        if 0 < end <= 40:
            body = text[end + 1 :].lstrip()
            if any(body.startswith(prefix) for prefix in _SYNTHETIC_MESSAGE_PREFIXES):
                return "synthetic_or_internal_prompt"
    return ""


def _extract_llm_usage(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("usage", "llm_usage", "response_usage", "model_usage"):
        usage = kwargs.get(key)
        if not isinstance(usage, dict):
            continue
        safe_usage = _safe_usage_fields(usage)
        _normalize_token_aliases(safe_usage)
        if safe_usage:
            return {"available": True, **safe_usage}
    return {"available": False}


_SAFE_USAGE_FIELDS = {
    "prompt_tokens",
    "input_tokens",
    "completion_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cost",
    "cost_usd",
    "latency_ms",
    "duration_ms",
    "requests",
}

_SAFE_TOKEN_DETAIL_FIELDS = {
    "accepted_prediction_tokens",
    "audio_tokens",
    "cached_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "reasoning_tokens",
    "rejected_prediction_tokens",
}


def _safe_usage_fields(usage: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for index, (key, value) in enumerate(usage.items()):
        if index >= 64:
            break
        field = str(key)
        if len(field) > 64:
            continue
        normalized = field.lower()
        if normalized in _SAFE_USAGE_FIELDS and _is_safe_usage_number(value):
            safe[field] = value
        elif _is_safe_token_details(field, value):
            safe[field] = dict(list(value.items())[:32])
    return safe


def _normalize_token_aliases(usage: dict[str, Any]) -> None:
    if "prompt_tokens" not in usage:
        prompt_tokens = _usage_int(usage.get("input_tokens"))
        if prompt_tokens is not None:
            usage["prompt_tokens"] = prompt_tokens
    if "completion_tokens" not in usage:
        completion_tokens = _usage_int(usage.get("output_tokens"))
        if completion_tokens is not None:
            usage["completion_tokens"] = completion_tokens
    if "total_tokens" not in usage:
        prompt_tokens = _usage_int(usage.get("prompt_tokens"))
        completion_tokens = _usage_int(usage.get("completion_tokens"))
        if prompt_tokens is not None and completion_tokens is not None:
            usage["total_tokens"] = prompt_tokens + completion_tokens


def _is_safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_safe_usage_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_safe_token_details(field: str, value: Any) -> bool:
    normalized = field.lower()
    if (
        "token" not in normalized
        or "detail" not in normalized
        or not isinstance(value, dict)
        or len(value) > 32
    ):
        return False
    for detail_key, detail_value in value.items():
        if (
            str(detail_key).lower() not in _SAFE_TOKEN_DETAIL_FIELDS
            or not _is_safe_usage_number(detail_value)
        ):
            return False
    return True


def _usage_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _coerce_scores(raw: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            result[str(key)] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return result


def _decision_patch(parsed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "post_turn_target": parsed.get("post_turn_target"),
        "evidence_summary": parsed.get("evidence_summary"),
        "derived_memory": parsed.get("derived_memory"),
        "subjects": parsed.get("subjects"),
        "confidence": parsed.get("confidence"),
        "cultural_item": parsed.get("cultural_item"),
        "kinlayer_memories": parsed.get("kinlayer_memories"),
    }


def _classification_instructions(bundle, relationship_ontology=None) -> str:
    domains = _domain_names(bundle)
    return (
        "You are a post-turn personal-context memory triage classifier. Classify whether this completed turn "
        "contains reusable personal context for gyurin. This is after the assistant answer; "
        "never suggest changing the current answer. Evidence scope is STRICTLY the current user message; "
        "do not use assistant text, tool output, retrieved context, injected memory, skill text, or conversation history as evidence. "
        "Store no raw transcript. Return only JSON. "
        "Use task intent and semantic ownership policy, not keyword hits or topic-specific exception lists. "
        "Be conservative: record only durable or reusable "
        "evidence that can improve future personalized answers. Valid domains: "
        + ", ".join(domains)
        + ". JSON fields: should_record boolean; post_turn_target string domain name; "
        "confidence number 0..1; subjects string array; evidence_summary string distilled summary; "
        "derived_memory string array; kinlayer_memories array of at most 8 independently correctable claims (empty when none); "
        "optional cultural_item object for a concrete cultural item experience; "
        "dimensions object with scores for requires_personalization, involves_specific_person, "
        "interprets_interpersonal_context, asks_for_strategy_or_wording, may_create_durable_user_context, "
        "uses_external_conversation_source, generic_technical_or_factual; domains object scoring valid domains; "
        "tool_needs object. For relationship/person memory, put only real "
        "user-relationship people in subjects. Exclude fictional/public/hypothetical people, generic groups, "
        "AI/persona/bots, the user/self, pets, events/meetups, support-network abstractions, and pronoun-only "
        "mentions without same-message identifying detail. Do not derive people from regex or Korean particles like 와/과. "
        "For Kinlayer-bound person memory, save first: output kinlayer_memories, one independently correctable claim per entry. "
        "Split profession/job, work schedule, appointment, feeling, and inference into separate claims even in one sentence. "
        "Each entry has action create|correct|retract|reattribute, record_type observations|entity_facts|entity_edges, "
        "subject (context owner; self allowed), new_subject for reattribute, from_subject/to_subject for edges, "
        "relation_type and claim_text for edges; fact_type, content and structured value for facts; "
        "observation_type and content for observations; related:[{subject,role}] for observation participants; "
        "claim_basis reported|inferred|unknown and confidence 0..1 ALWAYS; source_quote an EXACT substring of the current user message. "
        "Non-create requires target_hint describing exactly which existing claim is meant, optionally {text, record_type, fact_type|observation_type|relation_type} "
        "with the OLD kind/subtype when changing it. Correct may convert a legacy fact into an observation for the same person. Never invent record IDs. A correction changes content while retaining target identity. "
        "Reattribute changes target identity but retains record kind; subject identifies the OLD context owner, new_subject the replacement "
        "owner (for edges, from_subject/to_subject give the NEW endpoints). Retract has no replacement. Other replacements are FULL "
        "records supported by the current user message, not partial patches or copied context-card evidence. "
        "Use entity_edges only for explicit structural relationships; omit directed unless explicit. Meetings/preferences/feelings/"
        "cautions/context/reply strategy belong in observations, never inferred relationship edges. Observation topics include preference, "
        "communication_preference, relationship_pattern, user_feeling, caution, care_point, recent_interaction, follow_up_context, stable_fact; "
        "unsupported ontology values will be skipped, never guessed or remapped. Do not output claim_type, ai_use_policy, "
        "confirmation_status, sensitivity, suggested_action or candidate fields. Stable supported text facts (job, role, organization, "
        "legal_name, email, phone, address, external_handle, location_hint) use value:{text:...} with text EXACTLY equal to content. "
        "Never use memo, important_context, relationship_note or contact_note fact types: use observations. Birthday/birth_date use "
        "value with ONLY known year/month/day plus precision year|month|day; content YYYY, YYYY-MM, YYYY-MM-DD. Only birthday "
        "may omit the year, with content --MM or --MM-DD. Never invent a year or first day. "
        "For corrections omit unchanged optional fields; null explicitly clears a known timestamp, related:[] clears links, "
        "and properties:{} clears edge properties. Nonempty related edits replace only their named roles; other roles are retained. "
        "Never output null or [] merely because the correction omits an existing value. "
        "Roles are subject|related|mentioned|speaker|target|about|experiencer. For the USER's feeling about X use subject X and "
        "related:[{subject:self,role:experiencer}]. Context owner is not automatically speaker or experiencer. "
        "reported means the human source states the claim (not verified truth); inferred means qualified agent inference from that "
        "human source; unknown means historical basis unknown. Keep uncertainty in content. "
        "Optional occurred_at is the actual described observation EVENT; valid_from/valid_to are applicability, not correction/storage "
        "time. Source statement time is separate. Use timestamps ONLY when known with explicit timezone; resolve relative dates ONLY "
        "from the supplied known message timestamp or leading Hermes timestamp, never today's date or an invented midnight/date. "
        "Unknown times are omitted and relative wording can remain in content. Do not copy source time into event or validity. "
        "Determine the contextual owner/subject before choosing a domain: distinguish gyurin/user-level facts from facts about other people. "
        "If the durable fact is about another real person, keep that person as the subject and route by ownership; if it is about gyurin's "
        "own preference, behavior, boundary, or stable pattern, profile or gyurin-level domains may be appropriate."
        " For a cultural item experience, return cultural_item with exactly these generic fields when applicable: "
        "item_title, item_aliases, medium, season_or_version, edition_or_dlc, platform, experience_state, reaction, "
        "reaction_reason, comparison_target, mentioned_characters_or_roles, resolution_status, "
        "resolution_source, resolution_confidence. This covers films, drama seasons, games/demos/DLC/platform "
        "editions, books/web novels/manga/anime, music, and YouTube/content without title-specific rules. "
        "For a game demo, DLC, expansion, or platform edition, always use medium=game and put the variant in "
        "season_or_version, edition_or_dlc, platform, or experience_state; demo/DLC/platform are never medium values. "
        "All experience_state, reaction, reaction_reason, comparison_target, and mentioned-character/role claims "
        "must be supported only by the current user message. A bounded prior-user context block, when present, "
        "may be used only to fill item identity fields and resolution metadata. It must never contribute a "
        "preference, reaction, reason, experience state, or comparison. Set resolution_status to explicit_current "
        "when the current user message identifies the item, resolved_prior_user when only the prior-user block "
        "resolves it, unresolved when identity is ambiguous, generic when only a generic referent exists, or "
        "not_applicable for a non-item cultural criterion. Set resolution_source to current_user_message, "
        "prior_user_message, or none. Never copy or summarize the raw prior context into output. "
        "Public actors, creators, and fictional characters/roles belong only in mentioned_characters_or_roles "
        "or comparison_target; never put them in subjects or Kinlayer fields. Pure factual questions with no "
        "user-authored experience or preference claim should return should_record false."
        " Relationship ontology below is server schema context, NEVER human evidence. Choose new or reattributed "
        "edges only from definitions with write_supported:true and support_level:supported. Use their description, "
        "direction, labels, examples and property schema; do not guess a type from the wording of its name. "
        "Labels identify source and target roles respectively. Omit directed to use the server definition. "
        "A legacy readable type may identify an exact existing record for correction/retraction, but a legacy "
        "correction must retain its type, endpoints, direction and properties. Replacement hints do not authorize "
        "automatic conversion. In particular, dating_interest must not be blindly mapped to situationship or a feeling. "
        "A source-described situationship is symmetric without proving mutual attraction or formal partnership. "
        "Do not infer a relationship from an app match or introduction; record supported acquaintance origin only "
        "with a separately supported relationship or as context. Do not create appointment/meeting tracking. "
        "If available:false, no relationship definitions are available: omit entity_edges claims rather than invent "
        "or use remembered types. Unrelated non-edge extraction retains its own contract. "
        "The relationship_profile registry below independently defines four self-perspective axes. "
        "For an explicit current USER assessment of another real person, use record_type:observations, "
        "observation_type:relationship_assessment, subject:the target, perspective_subject:self, "
        "relationship_axis and relationship_value from the supplied axis definitions, claim_basis:reported. "
        "Use one claim per explicitly stated axis. For a new current statement use action:create: the adapter "
        "reads the current axis and corrects its exact record if one exists. For explicit reset/unset of one "
        "axis use action:retract with that axis and perspective, omit relationship_value. Do not guess target_hint "
        "across axes. Never use an enum called unknown/unset: absence is not the lowest value. "
        "ALL four axes require explicit human statements, not inference. Never derive closeness, importance or "
        "disconnection from interaction frequency, missing logs, family or relationship type; never turn another "
        "person's feelings into the user's assessment. 'Rare contact but very important to me' states independent "
        "frequency and importance, not low closeness or disconnection. Do not add related participants, future "
        "timestamps or valid_to. Uncertain interpretations remain ordinary observations. "
        "If relationship_profile or its version/axis definitions are missing, omit relationship_assessment claims; "
        "do not fall back to invented axes/values or encode these structured choices in an edge. "
        + "\n[Fresh relationship registry]\n"
        + json.dumps(relationship_ontology or {"available": False}, ensure_ascii=False, separators=(",", ":"))
    )


def _classification_input(
    user_message: str,
    prior_user_tail: str,
    bundle,
    source_occurred_at: str | None = None,
) -> str:
    lines = [
        "[Current user-authored message: sole claim evidence]",
        user_message[:4000],
        "",
        "[Evidence boundary]",
        "Use ONLY the current user-authored message above for claims, reactions, reasons, experience state, comparisons, subjects, and derived memory.",
        "Never use assistant text, tool output, retrieved context, injected memory, skill text, or prior conversation as preference evidence.",
    ]
    if source_occurred_at:
        lines.extend(["", "[Known source statement timestamp; not event/validity time]", source_occurred_at])
    if prior_user_tail:
        lines.extend(
            [
                "",
                "[Bounded prior user-authored context: referent resolution only]",
                prior_user_tail,
                "Use this block only to resolve cultural item identity. Persist only resolution_source and resolution_confidence, never this raw context.",
            ]
        )
    lines.extend(
        [
            "",
            "[Known domains]",
            json.dumps(_domain_names(bundle), ensure_ascii=False),
        ]
    )
    return "\n".join(lines)


def _domain_names(bundle) -> list[str]:
    domains = bundle.domain_map.get("domains", {}) if isinstance(bundle.domain_map, dict) else {}
    if isinstance(domains, dict) and domains:
        return [str(name) for name in domains.keys()]
    return ["relationships", "cultural_taste", "finance_context", "home_infrastructure", "profile"]


def _prior_user_resolution_tail(history: Any, current_user_message: str = "") -> str:
    if not isinstance(history, list):
        return ""
    lines: list[str] = []
    current = (current_user_message or "").strip()
    skipped_current_turn = False
    for msg in reversed(history):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().casefold()
        if role != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text or _synthetic_user_message_reason(text):
            continue
        # post_llm_call receives the completed transcript, whose most recent
        # genuine user row is the current turn. Skip that row even when a
        # platform wrapper makes it differ slightly from original_user_message.
        if not skipped_current_turn:
            skipped_current_turn = True
            continue
        if text == current:
            continue
        lines.append(f"- {_clip(redact(text, 360), 360)}")
        if len(lines) >= 3:
            break
    lines.reverse()
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n...[truncated]"


def _trusted_signal_source(config: RouterConfig, kwargs: Mapping[str, Any], user_message: str) -> bool:
    if str(kwargs.get("platform") or "").strip().lower() != "discord" or "HERMES-PCB-CLAIM-V1" in user_message:
        return False
    owners = {
        str(owner_ids[0])
        for owner_ids in (
            config.kinlayer.reconciliation.owner_ids,
            config.kinlayer.enrichment.owner_ids,
        )
        if len(owner_ids) == 1
    }
    if len(owners) != 1:
        return False
    try:
        from gateway.session_context import get_session_env

        return get_session_env("HERMES_SESSION_USER_ID", "") == next(iter(owners))
    except Exception:
        return False


def _snapshot_post_turn_kwargs(
    kwargs: Mapping[str, Any], user_message: str, *, trusted_signal_source: bool = False
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "turn_id": redact(str(kwargs.get("turn_id") or ""), 160),
        "session_id": redact(str(kwargs.get("session_id") or ""), 160),
        "task_id": redact(str(kwargs.get("task_id") or ""), 160),
        "user_message": user_message[:4000],
        "_human_message_identity": hashlib.sha256(_canonical_json({
            "session": str(kwargs.get("session_id") or ""), "turn": str(kwargs.get("turn_id") or ""),
            "human_message": user_message,
        }).encode()).hexdigest(),
        "prior_user_tail": _prior_user_resolution_tail(
            kwargs.get("conversation_history"), user_message
        ),
        "llm_usage": _extract_llm_usage(kwargs),
        "trusted_signal_source": bool(trusted_signal_source),
    }
    for key in ("occurred_at", "message_timestamp", "created_at", "ts", "timestamp"):
        value = kwargs.get(key)
        if _is_safe_scalar(value) and value not in (None, ""):
            snapshot[key] = redact(str(value), 100)
    timestamp = _source_occurred_at(dict(kwargs), user_message)
    if timestamp:
        snapshot["message_timestamp"] = timestamp
    return snapshot


def _post_turn_key(snapshot: Mapping[str, Any]) -> tuple[str, str] | None:
    turn_id = str(snapshot.get("turn_id") or "")
    if not turn_id:
        return None
    # Preserve the hook's per-turn admission guard for every domain. The durable
    # Kinlayer journal separately binds full human-message/backend/profile identity.
    return str(snapshot.get("session_id") or ""), turn_id


_ROUTER = PersonalContextRouter()
atexit.register(_ROUTER.shutdown, _POST_TURN_ATEXIT_TIMEOUT)


def get_router() -> PersonalContextRouter:
    return _ROUTER
