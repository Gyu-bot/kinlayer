# Install / rollback — PCR 0.15.0

Canonical source is this repository's `integrations/hermes/` subtree. Keep the
actual Hermes plugin/skill locations unchanged. Install only a reviewed immutable
commit. The local stateful package is managed as an exact copied tree; do not use a
whole-repository plugin install that would copy backend application code.

## Preconditions

1. Inventory effective enabled profiles, real package links, router enabled/dry-run
   settings and current package hashes. Do not enable disabled profiles as a test.
2. Check nonterminal writer/compatibility work before replacing its code. Preserve
   all profile-local state, pending/deferred journals, request bodies and receipts.
3. Pin source and run the native synthetic suite with the installed host interpreter
   and matching existing dependency selection. Use `-B`; prohibit outbound sockets.
   Do not bootstrap a temporary runtime or provision packages just for tests.
4. Review host-specific changed files and all public-source additions. Historical
   test prose and deployment-specific cron adapters are deliberately not published.

## Managed set

- Replace the complete `personal-context-router/` plugin package from source,
  excluding bytecode/runtime data. Back up the prior whole package first.
- For `kinlayer-local`, replace exactly the Markdown paths present under
  `skills/kinlayer-local/`, not the whole installed directory. The host's existing
  `scripts/` subtree is an explicit unmanaged extension: preserve and hash it, and
  never publish deployment-bound job IDs or change its schedule/entrypoints.
- Keep all SOUL files, private personal-context policies, configuration, credentials,
  conversations, memory data and runtime state unchanged.
- Inactive legacy Discord reconciliation has no public default destination: route
  configuration plus matching operator-approved destination pins is required before
  any future activation. This deployment does not enable/migrate that lane.

## Backup / installation

Save a timestamped backup, deterministic relative-path SHA-256 manifest and tree
hash for old plugin, old skill, candidate and installed managed files. Reject
unexpected symlinks or runtime files in the source set. Verify installed managed
files exactly match the reviewed candidate and unmanaged extensions are unchanged.
Use the current host's supported managed-plugin activation route. A disk write is
not proof that a running gateway or existing chat has adopted the code.

## Activation / verification

With explicit narrow live-activation approval, use native plugin rediscovery or a
supported scoped service restart only when idle/safe. Never circumvent an in-process
restart refusal through another shell/AppleScript/launchd workaround. Inventory
actual serving gateway/dashboard lanes and each affected profile independently.
Verify registry version/tool visibility and call `kinlayer_identity` with
`action=status` through the existing Bot Chat native runtime route. This probe does
not query Kinlayer or create/write synthetic personal facts. Disabled router profiles
must stay disabled and return their disabled state. Do not create/reset chats.
Report installed, enabled, freshly imported, long-lived loaded, existing-session
adopted and harmless end-to-end probe as separate facts. A real activation or route
wall keeps the task open, not "done".

## Rollback

Restore only the backed-up managed code/docs after rechecking live ownership, then
use the same approved supported activation boundary. Never roll back the writer's
journal, state, receipts, pending/deferred claims, configuration, credentials or
person data. A code rollback cannot undo acknowledged backend writes; this task's
live probe is no-write. Keep the backup through acceptance and the operator's
rollback/debugging window; expiry is not automatic deletion permission.
