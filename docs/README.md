# Kinlayer Docs

This directory keeps project documentation that should not live at the repository root.

## Active Docs

- `specs/prd.md`: product requirements and principles.
- `specs/api-spec.md`: HTTP API contract.
- `specs/data-model.md`: canonical data model.
- `specs/cli-spec.md`: CLI contract.
- `specs/web-ui-spec.md`: Web UI scope.
- `specs/acceptance-scenarios.md`: MVP acceptance scenarios.
- `specs/context-output-contract.md`: retrieval output and Context Pack contract.
- `specs/candidate-lifecycle-and-payload.md`: legacy candidate API compatibility rules.
- `specs/ontology-design.md`: ontology registry and relationship boundary design.
- `plans/save-first-memory-schema.md`: current immediate-write/schema/live-conversion contract.
- `plans/frontend-rebuild.md`: planned frontend replacement; implementation deferred.
- `plans/relationship-curation-cycle.md`: previous curation requirements and compatibility history.
- `plans/relationship-reconciliation-cycle.md`: previous reconciliation requirements and compatibility history.
- `kinlayer-roadmap.md`: Korean user-facing roadmap for directing implementation.
- `agents/agent-integration-notes.md`: agent integration and post-turn boundary notes.
- `agents/kinlayer-client-helper.md`: deterministic read-only helper commands and configuration.
- `agents/agent-write-instruction-pack.md`: copy/paste-ready write guidance for agents, skills, plugins, MCP adapters, and runtime hooks.

Agent write boundary summary: agents split human-source context into atomic claims and submit
`POST /api/memories`. Kinlayer immediately validates and stores canonical records, source evidence
and change history. Corrections, retractions and reattributions follow the same contract. No human
approval queue or stored AI-use policy is required. Kinlayer core performs no LLM extraction.

## Archived Docs

- `archive/planning/handoff.md`: superseded implementation handoff prompt.
- `archive/planning/initial-implementation-plan.md`: superseded initial implementation plan.
- `archive/planning/interview-ledger.md`: historical interview and decision ledger.
- `archive/planning/implementation-plan-2026-06-27.md`: archived root task plan.

Archived docs are excluded from current SSOT even when their own headers claim an
active status.

## Root Docs

The repository root intentionally keeps only the high-signal entry points:

- `README.md`: product overview, setup, and local operation.
- `AGENTS.md`: local agent operating instructions.

Active implementation planning lives under `plans/`. The current plan is
`plans/save-first-memory-schema.md`.
