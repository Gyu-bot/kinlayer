# Kinlayer CLI Specification

## Save-first memory command

```bash
uv run kinlayer memory apply /path/to/memory-request.json --json
```

The positional JSON file contains the exact [agent memory envelope](../agents/agent-write-instruction-pack.md).
The CLI forwards it to `POST /api/memories` and returns the change receipt. It does not create or
accept a candidate. Use the same file/request ID after a transport failure. Existing candidate,
curation and legacy correction commands below remain compatibility operations.

> **2026-10-01 boundary:** The default product flow is now
> [save first, correct during conversation](../plans/save-first-memory-schema.md).
> Candidate/curation examples below remain compatibility scenarios. The current frontend is
> intentionally retained; its replacement is [planned separately](../plans/frontend-rebuild.md).
> Existing approval/policy surfaces are not requirements for new memory writes.


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

`kinlayer material-import --file manifest.json --json` validates a bounded, explicitly
authorized V1/V2 source manifest without persistent writes. Add `--submit` only to save
canonical memories immediately; V2 creates no candidates. The command validates either envelope
locally and verifies receipt readback including canonical refs/request hash; unsupported versions
never downgrade. It uses the separate
`KINLAYER_MATERIAL_IMPORT_TOKEN`, never automatic post-turn evidence. See
[authorized material imports](authorized-material-imports.md) for scope and activation.

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

Prepares the protected self entity through the canonical API.

Current behavior:

- POST `person` self entity to `/api/entities` with `system_role = self`;
- when self already exists, read it back with `GET /api/entities?system_role=self&limit=1`;
- support `--self-name` and `--json`;
- do not create or overwrite local config files;
- report that config defaults are documented in `.env.example`.

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

Checks backend health via the API and reports configured API URL, database health,
and embedding status.

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
--ai-use-policy freely_use|cautious_use|ask_before_use|never_surface
--json
```

Advanced edge/observation/fact creation can use the canonical HTTP API in MVP.

Structured profile fact writes are supported when the selected `fact_type` is registry-backed.
The current structured validation set is `legal_name`, `birth_date`, `phone`, `email`, `address`,
`organization`, and `role`. These values use the same content validation rules as the HTTP API.

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
  "suggested_action": "review",
  "created_by": "ai_agent",
  "supersedes_record_ref": "entity_facts:general-fact-id"
}
```

```bash
kinlayer candidate submit profile-email-candidate.json --json
kinlayer candidate accept <candidate_id> --json
```

When `supersedes_record_ref` is present on a `profile_field` candidate, it must reference an active
`entity_facts:<id>` on the same entity. Accept/edit-accept promotes that source fact into the
structured replacement, copies provenance, marks the source fact `superseded`, and sets the
candidate `canonical_record_ref` to the replacement fact.

### `candidate list`

Lists candidates.

Options:

```bash
--status pending
--candidate-type observation
--type observation
--target-entity-id <entity_id>
--target <entity_id>
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

## 6.1 Fact Promotion Command

```bash
kinlayer fact promote <fact_id> --fact-type email --content alex@example.com --field-path profile.email --json
```

Purpose: promote an active general profile fact into a structured profile fact through the canonical
`POST /api/entity-facts/{id}/promote` endpoint.

Options:

```bash
--fact-type legal_name|birth_date|phone|email|address|organization|role
--content TEXT
--field-path TEXT
--ai-use-policy freely_use|cautious_use|ask_before_use|never_surface
--json
```

Expected behavior:

- fetch the source fact to derive `entity_id`;
- submit the promotion request to the API;
- emit full JSON when `--json` is set;
- otherwise print `entity_facts:<source> -> entity_facts:<replacement>`.

Validation and errors are owned by the API. Invalid structured content returns `validation_error`.
Inactive/stale source facts return `conflict`.

## 6.2 Explicit Correction Examples

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
## Curation CLI

```text
kinlayer curation prepare --limit 50 --json
kinlayer curation plan-file PLAN.json --mode shadow --json
kinlayer curation execute RUN_ID --json
kinlayer curation resume RUN_ID --json
kinlayer curation show RUN_ID --json
```

These commands reuse the canonical API and existing URL/token settings. The server mode is
authoritative: `resume` may non-destructively recover persisted `pending|planning` runs in either
enabled mode, but apply-run execution/reconciliation still requires configured server mode
`apply`. Context card/pack commands accept `--include-provisional`.
