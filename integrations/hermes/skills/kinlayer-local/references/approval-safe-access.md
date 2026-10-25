# Kinlayer approval-safe access

Use this reference when Kinlayer reads/debugging from Hermes keep triggering command approvals, especially in Discord gateway sessions.

## Symptom

Kinlayer API calls work, but each investigation asks the user to approve a command, usually because the agent reaches Kinlayer through one of these shapes:

- `terminal()` with `python3 - <<'PY' ... urllib/request ... PY`
- `terminal()` with `curl`/`http` commands against the Kinlayer base URL
- `execute_code()` with arbitrary Python that can perform subprocess/file/network work
- long inline shell or Python snippets that trip Hermes dangerous-command/Tirith guards

This can happen even when the endpoint is local and trusted.

## Diagnosis

The repeated prompt is usually not a Kinlayer post-turn-hook failure and not necessarily a bad IP address. It is a trust-boundary issue:

- Inspect the deployment's actual approval mode; this package does not prescribe or change it.
- Terminal/execute_code calls are generic execution surfaces, so Hermes guards them broadly.
- Some broad warning classes can be session-approved, but Tirith/security-scan findings are intentionally not permanently allowlisted; `always` is effectively downgraded to session scope for those findings.
- Therefore a new session or a different inline script can re-prompt even after the user approved earlier.

## Preferred fix

Create a dedicated Kinlayer Hermes plugin/tool or MCP-style wrapper instead of calling the API through raw terminal snippets.

Good tool surface examples:

- `kinlayer_health`
- `kinlayer_search_entities`
- `kinlayer_get_context_card`
- `kinlayer_get_observations`
- `kinlayer_memory_history`
- one separate `kinlayer_write_memory(request)` write tool (save-first contract), never mixed into read tools

Implementation principles:

- Read base URL from active Hermes config, e.g. `runtime_context_router.kinlayer.base_url`, or a Kinlayer plugin config key.
- Do not expose the base URL/IP in normal chat output.
- Keep read tools separate from the write tool.
- Read/debug tools never write, accept legacy candidates, or retry writes.
- Return compact JSON summaries by default; only dump raw records when explicitly requested.

This is cleaner than hiding the IP behind a hostname or proxy, because the trust boundary becomes explicit: Kinlayer is a known local service with a constrained tool API, not arbitrary shell/network execution.

## Interim workaround

If a full plugin/tool is not available yet, prefer the repo-owned deterministic helper over ad-hoc inline terminal code:

```text
cd <KINLAYER_CHECKOUT>
KINLAYER_API_BASE_URL="$BASE" python3 scripts/kinlayer_client.py health
KINLAYER_API_BASE_URL="$BASE" python3 scripts/kinlayer_client.py entities --query '<name>' --entity-type person
KINLAYER_API_BASE_URL="$BASE" python3 scripts/kinlayer_client.py context-card --entity-id '<id>'
KINLAYER_API_BASE_URL="$BASE" python3 scripts/kinlayer_client.py retrieve --query '<question>'
```

If a stable path is needed for cron/launchd/hooks later, leave only a thin `~/.hermes/scripts/` wrapper around this helper or a native Hermes tool. Do not duplicate the implementation.

The helper/wrapper should:

- read base URL from config/env internally;
- avoid printing secrets or full base URLs;
- expose narrow subcommands;
- print compact JSON;
- avoid shell pipelines and inline interpreter snippets.

This may still use `terminal()`, so it is not as clean as a Hermes tool, but it reduces command-shape churn and approval false positives.

## What not to do

- Do not set global `/yolo` or `approvals.mode: off` just to make Kinlayer calls convenient. That loosens unrelated filesystem/service/shell protections too.
- Do not rely on hostname aliases or localhost proxies as the primary solution. They may reduce scanner friction, but they do not define a safer capability boundary.
- Do not record the Kinlayer IP/base URL in memory or public issue text.
- Do not conclude “post-turn hook is broken” merely because context cards are missing; first check router logs, the write receipt, and `/api/memory-changes`.

## Answer pattern

When the user asks why Kinlayer calls keep requesting approval:

```text
원인은 IP 자체라기보다 raw terminal/inline Python으로 Kinlayer를 호출해서 generic execution approval path를 타는 거야.
영구 해결은 Kinlayer 전용 Hermes tool/plugin으로 빼는 것.
임시로는 wrapper script + /approve session이 낫고, global yolo/off는 하지 않는 게 맞아.
```
