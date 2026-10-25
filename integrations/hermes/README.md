# Hermes integration

This subtree owns the `personal-context-router` plugin and the managed Markdown
files of the `kinlayer-local` companion skill. It is an adapter, not backend code.
The plugin API needs Hermes' native tool-execution middleware with trusted
session/turn/tool-call IDs. No Hermes core patch is included.

## Ownership and publication

- `personal-context-router/` is the complete managed plugin tree.
- `skills/kinlayer-local/` owns only its listed Markdown files. Existing host-only
  `scripts/` cron adapters are explicitly outside this source/install set and must
  remain untouched. They contain deployment-bound job identity, not portable code.
- Configuration, credentials, person data, conversations, journals, state, caches,
  backups and unprovenanced historical test examples are not source artifacts.
- New tests use invented project colleagues and disposable wire-shaped fake state.
  They test trust boundaries, not semantic model accuracy or a live backend.

Legacy hardcoded Discord destination pins have no portable default. The inactive
compatibility lane requires explicit `guild_id`/`channel_id` AND matching
`approved_guild_id`/`approved_channel_id`, one owner and a valid parent route before
it can activate. Publication is not permission to enable it or migrate a live route.
The existing technical `knowledge/gyurin` namespace and policy skill identifiers
are retained compatibility identifiers, never embedded person records or consent.

See [installation](personal-context-router/INSTALL.md) and
[identity contract](personal-context-router/docs/identity-guard.md).
