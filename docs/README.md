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
- `specs/candidate-lifecycle-and-payload.md`: candidate lifecycle and payload rules.
- `specs/ontology-design.md`: ontology registry and relationship boundary design.
- `agents/agent-integration-notes.md`: agent integration and post-turn boundary notes.
- `agents/agent-write-instruction-pack.md`: copy/paste-ready write guidance for agents, skills, plugins, MCP adapters, and runtime hooks.

Agent write boundary summary: AI agents interpret current-turn user-authored text and propose
candidates or explicit corrections; Kinlayer validates, stores, retrieves, reviews, and
canonicalizes relationship context. Kinlayer core does not run an LLM for post-turn extraction.

## Archived Docs

- `archive/planning/handoff.md`: superseded implementation handoff prompt.
- `archive/planning/initial-implementation-plan.md`: superseded initial implementation plan.
- `archive/planning/interview-ledger.md`: historical interview and decision ledger.

## Root Docs

The repository root intentionally keeps only the high-signal entry points:

- `README.md`: product overview, setup, and local operation.
- `implementation-plan.md`: active task-indexed execution plan.
- `AGENTS.md`: local agent operating instructions.
