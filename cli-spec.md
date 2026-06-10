# Kinlayer CLI Specification

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `candidate-lifecycle-and-payload.md`, `context-output-contract.md`

---

## 1. Purpose

Kinlayer is CLI-first, but the CLI is not the canonical capability owner. The HTTP API is canonical; the CLI is an API client for setup, debugging, agent-callable workflows, and core local operations.

MVP CLI scope:

```text
ops + agent/debug core CLI + raw API/JSON escape hatch
```

The CLI should be implemented with Typer.

---

## 2. Principles

1. No Web-only state-changing capability.
2. CLI wraps core workflows but does not need polished flags for every advanced edit.
3. Advanced or not-yet-wrapped actions must be reachable through raw API passthrough.
4. Commands should support JSON output for agents and tests.
5. Human-readable output is useful by default, but `--json` should be available on core commands.

---

## 3. Ops Commands

```bash
kinlayer init
kinlayer serve
kinlayer migrate
kinlayer status
```

### `kinlayer init`

Initializes local config and ensures default local settings.

Expected behavior:

- create config file if missing;
- prepare default API URL;
- optionally create `.env` sample;
- do not overwrite existing config without confirmation/flag.

### `kinlayer serve`

Starts the local FastAPI server.

Expected options:

```bash
kinlayer serve --host 127.0.0.1 --port 8765
```

Default host should be `127.0.0.1`.

### `kinlayer migrate`

Runs Alembic migrations.

### `kinlayer status`

Checks backend status, DB connectivity, migration status, and configured API URL.

---

## 4. Raw API Escape Hatch

```bash
kinlayer api GET /api/health
kinlayer api POST /api/entities --data entity.json
kinlayer api PATCH /api/observations/<id> --data patch.json
```

Purpose:

- expose all canonical HTTP API capability even when first-class CLI commands do not exist;
- support development, tests, and advanced local operations;
- prevent Web-only functionality.

Expected options:

```bash
--data <file.json>
--json
--pretty
--header KEY=VALUE
```

---

## 5. People / Bootstrap Commands

```bash
kinlayer person create --name "Alex"
kinlayer person list
kinlayer person show <entity_id>
```

### `person create`

Creates a person entity for initial seed/bootstrap.

MVP options:

```bash
--name TEXT
--alias TEXT  # repeatable optional
--note TEXT   # lightweight short note / property
--sensitivity low|medium|high
--ai-use-policy freely_use|cautious_use|ask_before_use|never_surface
--json
```

Advanced edge/observation/fact creation can use Web UI or raw `kinlayer api` in MVP.

### `person list`

Lists person entities with optional search/filter.

Options:

```bash
--query TEXT
--json
```

### `person show`

Shows person detail summary.

Options:

```bash
--json
```

---

## 6. Candidate Commands

```bash
kinlayer candidate submit <candidate.json>
kinlayer candidate list
kinlayer candidate show <candidate_id>
kinlayer candidate accept <candidate_id>
kinlayer candidate edit-accept <candidate_id> <edited-payload.json>
kinlayer candidate reject <candidate_id>
kinlayer candidate archive <candidate_id>
kinlayer candidate clarify <candidate_id> --note "..."
```

### `candidate submit`

Submits a candidate envelope JSON file.

Expected behavior:

- validate common envelope;
- validate typed payload by `candidate_type`;
- create candidate and candidate_evidence rows;
- return candidate id.

### `candidate list`

Lists candidates.

Options:

```bash
--status pending
--type observation
--target <entity_id>
--json
```

### `candidate accept`

Accepts candidate as-is and immediately writes canonical record.

Expected behavior:

- set status `accepted`;
- set resolved fields;
- create canonical record;
- set `canonical_record_ref`.

### `candidate edit-accept`

Accepts candidate using edited payload JSON.

Expected behavior:

- validate edited payload;
- write canonical record from edited payload;
- set status `edited_accepted`.

### `candidate reject`

Rejects candidate.

Options:

```bash
--note TEXT
```

### `candidate archive`

Archives candidate without confirming or rejecting.

### `candidate clarify`

Marks candidate as `needs_clarification`.

Options:

```bash
--note TEXT
```

---

## 7. Context / Retrieval Commands

```bash
kinlayer retrieve "Alex messaged me again"
kinlayer context-card <entity_id>
kinlayer context pack "That person contacted me again"
```

### `retrieve`

Calls retrieval endpoint and returns matched entities, confidence, suggested response policy, and optional debug summary.

Options:

```bash
--max-results 8
--include-pending-recent / --no-include-pending-recent
--debug
--json
```

### `context-card`

Returns Person Context Card for an entity.

Options:

```bash
--json
```

### `context pack`

Returns Context Pack for a user query.

Options:

```bash
--conversation-context <file-or-text>
--include-pending-recent / --no-include-pending-recent
--debug
--json
```

---

## 8. Correction Command

```bash
kinlayer correction apply <correction.json>
```

Used for explicit user corrections detected in an agent conversation.

Expected behavior:

- create correction episode with bounded excerpt/hash;
- supersede/deprecate old canonical record;
- create new canonical record;
- link evidence;
- update retrieval immediately.

Agent-inferred corrections should use candidate submission instead.

---

## 9. Graph / Debug / Embedding Commands

```bash
# Graph / debug
kinlayer graph ego <entity_id>
kinlayer debug retrieval "query..."

# Embeddings
kinlayer embedding status
kinlayer embedding backfill
```

### `graph ego`

Returns person-first 1-hop ego graph data.

Options:

```bash
--relation-type TEXT
--status active
--sensitivity low|medium|high
--json
```

### `debug retrieval`

Returns retrieval score breakdown and policy decisions.

Options:

```bash
--include-blocked
--include-superseded
--json
```

---

## 10. Non-goals for MVP CLI

MVP CLI does not need polished first-class commands for every advanced edit:

```text
edge create/edit
observation create/edit
entity_fact create/edit
ontology registry editing
episode browsing
connector management
import management
```

These capabilities should exist in HTTP API where relevant and remain reachable through `kinlayer api`.
