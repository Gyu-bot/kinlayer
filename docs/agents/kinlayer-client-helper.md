# Kinlayer read-only client helper

`scripts/kinlayer_client.py` is the repository-owned, standard-library-only helper for deterministic
agent reads. It has no candidate actions, corrections, or other write commands. `retrieve` and
`pack` use POST because their API contracts accept JSON request bodies, but those endpoints are
read-only.

## Configuration

The API base URL is selected in this order:

1. `KINLAYER_API_BASE_URL`;
2. the JSON string returned by
   `hermes config get runtime_context_router.kinlayer.base_url --json`, when the `hermes` command is
   available and returns promptly;
3. `http://127.0.0.1:8765`.

An explicitly set but invalid `KINLAYER_API_BASE_URL` fails closed. A missing, slow, malformed, or
invalid Hermes-derived value is treated as unavailable and falls back to the documented local URL.

Only `http` and `https` URLs without credentials, queries, fragments, or unescaped whitespace are
accepted. When `KINLAYER_API_TOKEN` is set, the helper sends it using the existing
`Authorization: Bearer <token>` convention. Errors never include the token or resolved base URL.

## Output and exits

Commands emit one compact JSON object by default. Pass `--raw` before or after the command to emit
the exact API response instead. Argument failures emit JSON and exit `2`; connection, HTTP, URL, and
response-decoding failures emit JSON and exit `1`. A degraded `health` result also exits `1`.

## Commands

```text
health
version
schema-summary
ontology
entities [--query TEXT] [--entity-type TYPE] [--status STATUS]
         [--system-role ROLE] [--limit N] [--offset N]
context-card --entity-id ID [--include-provisional]
observations [--subject-entity-id ID] [--related-entity-id ID]
             [--observation-type TYPE] [--status STATUS] [--claim-type TYPE]
             [--limit N] [--offset N]
candidates [--status STATUS] [--candidate-type TYPE] [--target-entity-id ID]
           [--limit N] [--offset N]
candidate --id ID
retrieve --query TEXT [--hint TEXT ...] [--focal-entity-id ID]
         [--include-debug] [--limit N]
pack --query TEXT [--hint TEXT ...] [--focal-entity-id ID] [--situation TEXT]
     [--include-provisional] [--include-debug] [--limit N]
```

Examples:

```bash
python3 scripts/kinlayer_client.py health
python3 scripts/kinlayer_client.py entities --query "Jordan" --limit 10
python3 scripts/kinlayer_client.py context-card --entity-id person_123
python3 scripts/kinlayer_client.py pack --query "Draft a reply" --hint Jordan --raw
```

## Ontology output for agents

Run `python3 scripts/kinlayer_client.py ontology` at session start and before using an unknown
controlled type. The command fetches the live API every time; it keeps no persistent cache and
contains no relationship-value enum. The output preserves:

- `version`: the server ontology version (`relationship-v1` for the relationship revision);
- `values` and `counts`: the existing compact indexes, now also including claim bases and
  participant roles;
- `definitions`: complete server registry rows, including edge labels, inverse labels, direction,
  descriptions, examples, allowed property schema, support/write status, replacement hints, and
  future server metadata. For relationships, read `definitions.edge_types`.

`values.edge_types` also contains readable historical types. New writes must use a definition
whose `write_supported` is true; presence in `values` or `active: true` alone is insufficient.
Do not derive direction from a translated label. Read the definition and keep its from/to roles.
`replacement_type` is a source-dependent migration hint, not an automatic rewrite instruction.
The helper leaves absent metadata absent and an absent version null; it does not claim that an
older server implements the new write contract.

Adapters that cache output must scope it by API instance and version, refetch each session,
invalidate definitions on a version change, and refresh after an unknown-type or ontology
validation failure. A rejected write is not permission to invent a type or change the source's
meaning. The full [agent write contract](agent-write-instruction-pack.md#ontology-discovery-and-cache-rules)
defines refresh and retry behavior.

Updating this repository helper and documentation does not update an installed external agent,
its skill copy, or an already running session. Those consumers must receive the revised contract
and fetch the live registry after deployment; no automatic notification is performed here.
