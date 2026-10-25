from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


LOW_SIGNAL_EXACT = {
    "",
    "응",
    "ㅇㅇ",
    "ㅋㅋ",
    "ok",
    "okay",
    "ㅇㅋ",
}


DEFAULT_DIMENSIONS = {
    "requires_personalization": 0.0,
    "involves_specific_person": 0.0,
    "interprets_interpersonal_context": 0.0,
    "asks_for_strategy_or_wording": 0.0,
    "may_create_durable_user_context": 0.0,
    "uses_external_conversation_source": 0.0,
    "needs_current_live_state": 0.0,
    "needs_current_public_fact": 0.0,
    "generic_technical_or_factual": 0.0,
}


class DimensionClassifier(Protocol):
    def __call__(self, user_message: str) -> "DimensionResult | Mapping[str, Any]":
        ...


@dataclass
class DimensionResult:
    dimensions: dict[str, float] = field(default_factory=dict)
    domains: dict[str, float] = field(default_factory=dict)
    tool_needs: dict[str, float] = field(default_factory=dict)
    subjects: list[str] = field(default_factory=list)
    low_signal_skip: bool = False
    hard_skip_reason: str = ""
    extraction_reason: str = "classifier_unavailable"
    classifier_available: bool = False


def is_low_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", (text or "").strip().lower())
    return compact in LOW_SIGNAL_EXACT


def _hard_skip_reason(text: str) -> str:
    stripped = (text or "").strip()
    lowered = stripped.lower()
    if lowered.startswith("[system note:"):
        return "system_note"
    if lowered.startswith("<system-note") or lowered.startswith("<system_note"):
        return "system_note"
    return ""


def extract_dimensions(
    user_message: str,
    classifier: DimensionClassifier | Callable[[str], DimensionResult | Mapping[str, Any]] | None = None,
) -> DimensionResult:
    text = user_message or ""
    hard_skip_reason = _hard_skip_reason(text)
    if hard_skip_reason:
        return DimensionResult(
            dimensions=dict(DEFAULT_DIMENSIONS),
            low_signal_skip=True,
            hard_skip_reason=hard_skip_reason,
            extraction_reason=hard_skip_reason,
        )
    if is_low_signal(text):
        return DimensionResult(
            dimensions=dict(DEFAULT_DIMENSIONS),
            low_signal_skip=True,
            hard_skip_reason="low_signal_exact",
            extraction_reason="low_signal_exact",
        )
    if classifier is None:
        return DimensionResult(
            dimensions=dict(DEFAULT_DIMENSIONS),
            domains={},
            tool_needs={},
            extraction_reason="classifier_unavailable",
            classifier_available=False,
        )

    try:
        return _coerce_classifier_result(classifier(text))
    except Exception:
        return DimensionResult(
            dimensions=dict(DEFAULT_DIMENSIONS),
            domains={},
            tool_needs={},
            extraction_reason="classifier_error",
            classifier_available=False,
        )


def _coerce_classifier_result(raw: DimensionResult | Mapping[str, Any]) -> DimensionResult:
    if isinstance(raw, DimensionResult):
        raw.classifier_available = True
        if not raw.extraction_reason:
            raw.extraction_reason = "classifier"
        return raw
    return DimensionResult(
        dimensions=_coerce_scores(raw.get("dimensions"), defaults=DEFAULT_DIMENSIONS),
        domains=_coerce_scores(raw.get("domains")),
        tool_needs=_coerce_scores(raw.get("tool_needs")),
        subjects=[str(item).strip() for item in raw.get("subjects", []) if str(item).strip()] if isinstance(raw.get("subjects"), list) else [],
        low_signal_skip=bool(raw.get("low_signal_skip", False)),
        hard_skip_reason=str(raw.get("hard_skip_reason") or ""),
        extraction_reason=str(raw.get("extraction_reason") or "classifier"),
        classifier_available=True,
    )


def _coerce_scores(raw: Any, defaults: Mapping[str, float] | None = None) -> dict[str, float]:
    scores = dict(defaults or {})
    if not isinstance(raw, Mapping):
        return scores
    for key, value in raw.items():
        try:
            scores[str(key)] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return scores
