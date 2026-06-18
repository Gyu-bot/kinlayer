# Kinlayer CLI Specification

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `candidate-lifecycle-and-payload.md`, `context-output-contract.md`

---

## 1. Purpose

Kinlayer is CLI-first, but the CLI is not the canonical capability owner. The HTTP API is canonical; the CLI is an API client for setup, debugging, agent-callable workflows, and core local operations.

Implemented MVP CLI scope:

```text
ops + people bootstrap + candidate/correction workflows + context/debug/graph/embedding commands
```

The CLI should be implemented with Typer.

---

## 2. Principles

1. No Web-only state-changing capability.
2. CLI wraps core workflows but does not need polished flags for every advanced edit.
3. Advanced or not-yet-wrapped actions remain reachable through the canonical HTTP API and smoke scripts.
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

## 4. HTTP API Access

There is no generic `kinlayer api` passthrough command in the current MVP CLI.
Advanced API-only operations are exercised through documented HTTP endpoints and smoke scripts.
This keeps the CLI focused on stable agent/debug workflows while preserving the rule that Web UI does not own unique state-changing capabilities.

---

## 5. People / Bootstrap Commands

```bash
kinlayer person create --name "Alex"
kinlayer person list
kinlayer person show <entity_id>
kinlayer person duplicates <entity_id>
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

Advanced edge/observation/fact creation can use the canonical HTTP API in MVP.

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

### `person duplicates`

Runs duplicate detection for a source person and optionally creates a merge candidate through the
canonical API.

Options:

```bash
--limit 5
--create-candidate
--evidence-episode-id <episode_id>
--evidence-excerpt "..."
--evidence-confidence 0.9
--json
```

Expected behavior:

- `--json` returns the API duplicate-candidate response for agents and smoke tests;
- human-readable output shows the recommended action, created candidate if any, and candidate
  target summaries;
- `--create-candidate` requires evidence episode and excerpt flags.

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

Structured profile fact candidate example:

```json
{
  "candidate_type": "profile_field",
  "target_entity_id": "person-123",
  "payload": {
    "entity_id": "person-123",
    "field_path": "profile.email",
    "fact_type": "email",
    "content": "alex@example.com",
    "value": {
      "kind": "work",
      "email": "alex@example.com"
    },
    "claim_type": "fact",
    "sensitivity": "high",
    "ai_use_policy": "ask_before_use"
  },
  "evidence": [
    {
      "episode_id": "episode-123",
      "excerpt": "Alex said alex@example.com is the best work email.",
      "confidence": 0.8
    }
  ],
  "confidence": 0.8,
  "sensitivity": "high",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

```bash
kinlayer candidate submit profile-email-candidate.json --json
kinlayer candidate accept <candidate_id> --json
```

### `candidate list`

Lists candidates.

Options:

```bash
--status pending
--candidate-type observation
--type observation
--target-entity-id <entity_id>
--target <entity_id>
--sensitivity medium
--json
```

### `candidate accept`

Accepts candidate as-is and immediately writes canonical record.

Options:

```bash
--resolution-note "User confirmed this exact merge."
--note "User confirmed this exact merge."
--resolved-by ai_agent
--json
```

Expected behavior:

- set status `accepted`;
- set resolved fields;
- create canonical record;
- set `canonical_record_ref`.

For `merge` candidates, accept atomically merges the source person into the target person and sets
`canonical_record_ref = entities:<target_entity_id>`. Agents may use this command only after
explicit current-turn user confirmation for the exact source-target merge and should set
`--resolved-by ai_agent` plus a confirmation note.

### `candidate show`

Shows a candidate. JSON output returns the full API response.

For `merge` candidates, human-readable output includes source and target context-card summaries,
merge reason, fields to merge, and risk notes before any lifecycle action is taken.

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

## 6.1 Explicit Correction Examples

Explicit user corrections may bypass candidate review only when
`correction_source.user_explicit` is `true`.

Structured profile fact correction example:

```json
{
  "old_record_ref": "entity_facts:old-fact-id",
  "new_record": {
    "record_type": "entity_facts",
    "payload": {
      "entity_id": "person-123",
      "fact_type": "email",
      "content": "alex.new@example.com",
      "value": {
        "kind": "work",
        "email": "alex.new@example.com"
      },
      "claim_type": "fact",
      "sensitivity": "high",
      "ai_use_policy": "ask_before_use"
    }
  },
  "correction_source": {
    "source_type": "agent_conversation",
    "user_explicit": true,
    "excerpt": "Actually, Alex's work email is alex.new@example.com."
  },
  "created_by": "ai_agent"
}
```

```bash
kinlayer correction apply profile-email-correction.json --json
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
--entity-hint <entity_id>  # repeatable
--focal-entity-id <entity_id>
--limit 8
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
--entity-hint <entity_id>  # repeatable
--focal-entity-id <entity_id>
--situation TEXT
--limit 8
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
--depth 1
--json
```

### `debug retrieval`

Returns retrieval score breakdown and policy decisions.

Options:

```bash
--entity-hint <entity_id>
--focal-entity-id <entity_id>
--limit 8
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

These capabilities exist in HTTP API where relevant and are covered by acceptance smoke scripts.
