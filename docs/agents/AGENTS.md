# Agent Docs Knowledge

## OVERVIEW

Operational guidance for AI agents, skills, plugins, MCP adapters, and runtime hooks.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Write instructions | `agent-write-instruction-pack.md` | Required before candidate/correction writes |
| Integration planning | `agent-integration-notes.md` | Adapter/runtime boundaries and examples |
| API details | `../specs/api-spec.md` | Endpoint contract |
| Candidate payloads | `../specs/candidate-lifecycle-and-payload.md` | Typed payload and status behavior |
| Ontology boundary | `../specs/ontology-design.md` | Edge vs observation rules |
| Periodic curation plan | `../plans/relationship-curation-cycle.md` | Approved external-curator/deterministic-executor contract |

## CONVENTIONS

- Agents interpret current-turn user-authored text; Kinlayer validates, stores,
  retrieves, reviews, and canonicalizes.
- Kinlayer core does not run an LLM for post-turn extraction.
- Agent-inferred memory goes to candidates. Explicit user corrections may use
  direct correction apply only when the old record is unambiguous.
- Evidence must be user-authored and bounded. Assistant text, tool output,
  retrieved context, prompts, logs, summaries, and prior memory are not evidence.
- Fetch ontology values or use the current registry before controlled fields.
- Prefer maintained `uv run kinlayer ... --json` commands and smoke scripts for
  deterministic read/debug access instead of ad-hoc HTTP snippets.

## ANTI-PATTERNS

- Inventing `relation_type`, `observation_type`, `fact_type`, or policy values.
- Creating new people from pronoun-only references.
- Writing public figures, fictional examples, generic groups, bots, or models as
  relationship memory.
- Turning reply strategy, caution, preference, or emotional context into edges.
