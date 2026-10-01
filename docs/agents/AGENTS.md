# Agent Docs Knowledge

## OVERVIEW

Operational guidance for AI agents, skills, plugins, MCP adapters, and runtime hooks.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Write instructions | `agent-write-instruction-pack.md` | Required before memory writes and corrections |
| Integration planning | `agent-integration-notes.md` | Adapter/runtime boundaries and examples |
| API details | `../specs/api-spec.md` | Endpoint contract |
| Candidate payloads | `../specs/candidate-lifecycle-and-payload.md` | Legacy API compatibility only |
| Ontology boundary | `../specs/ontology-design.md` | Edge vs observation rules |
| Active schema plan | `../plans/save-first-memory-schema.md` | Immediate writes and live conversion |

## CONVENTIONS

- Agents interpret current-turn user-authored text; Kinlayer validates and atomically stores
  canonical memory, evidence, and change history.
- Kinlayer core does not run an LLM for post-turn extraction.
- New memories use `POST /api/memories` immediately with one claim, explicit basis and source.
  Clear user corrections use correct/retract/reattribute; there is no pre-save approval queue.
- Evidence must be user-authored and bounded. Assistant text, tool output,
  retrieved context, prompts, logs, summaries, and prior memory are not evidence.
- Fetch ontology values or use the current registry before controlled fields.
- Prefer maintained `uv run kinlayer ... --json` commands and smoke scripts for
  deterministic read/debug access instead of ad-hoc HTTP snippets.

## ANTI-PATTERNS

- Inventing `relation_type`, `observation_type`, `fact_type`, or basis values.
- Creating new people from pronoun-only references.
- Writing public figures, fictional examples, generic groups, bots, or models as
  relationship memory.
- Turning reply strategy, caution, preference, or emotional context into edges.
