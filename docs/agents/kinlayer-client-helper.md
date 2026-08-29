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
         [--sensitivity LEVEL] [--system-role ROLE] [--limit N] [--offset N]
context-card --entity-id ID [--include-provisional]
observations [--subject-entity-id ID] [--related-entity-id ID]
             [--observation-type TYPE] [--status STATUS] [--claim-type TYPE]
             [--limit N] [--offset N]
candidates [--status STATUS] [--candidate-type TYPE] [--target-entity-id ID]
           [--sensitivity LEVEL] [--limit N] [--offset N]
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
