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
- `plans/frontend-rebuild.md`: approved frontend replacement (implemented in `frontend/src/v2/`) and UI01–UI09.
- `plans/relationship-ontology.md`: `relationship-v1` types and relationship profile axes (implemented, live).
- `plans/runtime-correctness.md`: **next implementation scope: RC-A** — Self, state-transition, FK and canonical identity fixes; later common-writer and retrieval stages.
- `plans/record-lifecycle-contract.md`: shared planned contract for cross-kind lineage, immutable originals, evidence, validity and compatibility.
- `plans/data-model-integrity.md`: planned model/ontology integrity redesign; common writer/lineage precedes canonical constraints.
- `plans/embedding-auto-index.md`: automatic observation embedding after writes, recovery and token preservation; query-side retrieval is owned by runtime correctness.
- `plans/observation-ontology-v1.md`: following plan — observation vocabulary, participant roles, assertion mode, date precision and record conversion.
- `specs/authorized-material-imports.md`: separately authorized material import contract.
- `specs/sensitivity-retirement.md`: retired sensitivity metadata compatibility contract.
- `verification/frontend-v2/README.md`: frontend replacement verification evidence.
- `verification/schema-logic-review-2026-10-22.md`: source/schema/plan review findings, synthetic reproductions and live-verification limits.
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

Active implementation planning lives under `plans/`. The current write contract is
`plans/save-first-memory-schema.md`; the next implementation scope is RC-A in
`plans/runtime-correctness.md`. Follow `kinlayer-roadmap.md` for dependencies and order.
New target contracts remain planned until their implementation and deployment are verified separately.
