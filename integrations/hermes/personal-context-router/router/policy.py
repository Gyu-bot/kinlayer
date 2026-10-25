from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from typing import Any

from .dimensions import DimensionResult
from .manifest import ManifestBundle


OPS = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
}


@dataclass
class PolicyDecision:
    active_policies: list[dict[str, Any]] = field(default_factory=list)
    active_domains: list[dict[str, Any]] = field(default_factory=list)
    selected_sources: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    post_turn_target: str = ""
    raw_transcript_storage: str = "forbid"
    evidence_summary: str = ""
    derived_memory: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    confidence: float | None = None
    cultural_item: dict[str, Any] = field(default_factory=dict)
    kinlayer_memories: list[dict[str, Any]] = field(default_factory=list)

    @property
    def should_inject(self) -> bool:
        # Backward-compatible property name for older tests/importers.  The
        # router no longer injects; this now means "has post-turn work".
        return bool(self.active_policies or self.active_domains or self.post_turn_target)


def _value_for_path(dimensions: DimensionResult, path: str) -> Any:
    if path.startswith("dimensions."):
        return dimensions.dimensions.get(path.split(".", 1)[1], 0.0)
    if path.startswith("domains."):
        return dimensions.domains.get(path.split(".", 1)[1], 0.0)
    if path.startswith("tool_needs."):
        return dimensions.tool_needs.get(path.split(".", 1)[1], 0.0)
    return None


def _eval_condition(value: Any, expression: Any) -> bool:
    if isinstance(expression, bool):
        return bool(value) is expression
    if isinstance(expression, (int, float)):
        return value == expression
    text = str(expression).strip()
    match = re.match(r"^(>=|<=|>|<|==)\s*(.+)$", text)
    if not match:
        return str(value) == text
    op, rhs = match.groups()
    try:
        rhs_value: Any = float(rhs)
        lhs_value: Any = float(value or 0)
    except (TypeError, ValueError):
        rhs_value = rhs
        lhs_value = value
    return bool(OPS[op](lhs_value, rhs_value))


def matches_when(when: Any, dimensions: DimensionResult) -> bool:
    if not when:
        return True
    if not isinstance(when, dict):
        return False
    for key, expression in when.items():
        if key == "any":
            if not isinstance(expression, list) or not any(
                matches_when(item, dimensions) for item in expression
            ):
                return False
            continue
        if key == "all":
            if not isinstance(expression, list) or not all(
                matches_when(item, dimensions) for item in expression
            ):
                return False
            continue
        if not _eval_condition(_value_for_path(dimensions, key), expression):
            return False
    return True


def evaluate_policies(bundle: ManifestBundle, dimensions: DimensionResult) -> PolicyDecision:
    decision = PolicyDecision()

    if isinstance(bundle.router, dict):
        _evaluate_policy_group(bundle.router.get("policies"), dimensions, decision, old_style=True)
        _evaluate_policy_group(
            bundle.router.get("post_turn_policies"),
            dimensions,
            decision,
            old_style=False,
        )

    domains = bundle.domain_map.get("domains", {}) if isinstance(bundle.domain_map, dict) else {}
    if isinstance(domains, dict):
        for name, domain in domains.items():
            if not isinstance(domain, dict):
                continue
            if matches_when(domain.get("activate_when"), dimensions):
                active = {"name": name, **domain}
                decision.active_domains.append(active)
                source_path = str(domain.get("curated_file") or domain.get("file") or name)
                decision.selected_sources.append(f"knowledge_file:{source_path}:curated")

    for policy in decision.active_policies:
        for source in policy.get("source_labels", []) or []:
            if isinstance(source, str):
                decision.selected_sources.append(source)

    decision.selected_sources = _dedupe(decision.selected_sources)
    decision.subjects = [str(item).strip() for item in dimensions.subjects if str(item).strip()]
    if not decision.post_turn_target and len(decision.active_domains) == 1:
        decision.post_turn_target = str(decision.active_domains[0].get("name") or "")
    return decision


def _evaluate_policy_group(
    policies: Any,
    dimensions: DimensionResult,
    decision: PolicyDecision,
    *,
    old_style: bool,
) -> None:
    if not isinstance(policies, dict):
        return
    for name, policy in policies.items():
        if not isinstance(policy, dict):
            continue
        if not matches_when(policy.get("when"), dimensions):
            continue
        active = {"name": name, **policy}
        decision.active_policies.append(active)
        for instruction in policy.get("instructions", []) or []:
            if isinstance(instruction, str):
                decision.instructions.append(instruction)

        post_turn = policy.get("post_turn") if isinstance(policy.get("post_turn"), dict) else {}
        target = str(
            policy.get("candidate_target")
            or post_turn.get("candidate_target")
            or policy.get("storage_target")
            or ""
        )
        if target and not decision.post_turn_target:
            decision.post_turn_target = target

        raw_policy = str(
            policy.get("raw_transcript_storage")
            or post_turn.get("raw_transcript_storage")
            or policy.get("raw_storage")
            or ""
        )
        if raw_policy:
            decision.raw_transcript_storage = raw_policy


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped
