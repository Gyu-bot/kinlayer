# Current-agent identity handoff — PCR 0.15.0

## Authority

The CURRENT conversational agent is the semantic person-identity decider. Kinlayer
supplies at most eight candidate cards with source-backed, basis-qualified hints.
No auxiliary identity planner/decider or name/display equality gate overrides that
reasoning. Name-form stripping is only candidate discovery, never authorization.
Unfamiliar or variant names can use at most two exact native-context search hints.
The main agent considers competing candidates and explicitly names excluded ones.
If genuinely uncertain it may ask one natural question itself. Neither an offline
lookup nor missing/invalid decision demands a user confirmation. Output transforms
never append questions and old pending notices do not impose a confirmation ritual.

## Native channel

1. `pre_llm_call` admits a genuine current human turn and records its native
   profile, backend, session, sender and turn, plus identity-only native context.
   Synthetic/delegated/private bridge turns do not admit this lane.
2. The model calls the registered `kinlayer_identity` tool. Its schema accepts
   decision content, NOT session/turn/sender/profile/backend coordinates.
3. Native `tool_execution` middleware binds the trusted runtime session/turn and
   requires a tool-call ID. The handler also checks the dispatch session. Missing
   middleware fails closed even though host middleware errors are fail-open.
4. `lookup` returns bounded candidates and an opaque token scoped to that exact
   native frame. `decide` requires an existing selected candidate, valid supplied
   evidence refs (`entities:<id>` is valid existence evidence), exact native-context
   quotes, explicit excluded alternatives and the current agent's reasoning.
   `mention_surfaces` explicitly lists additional same-person spellings; the writer
   never expands spellings automatically. A conflict latches until the turn ends.
   `unresolved` revokes that surface. `status` performs no backend I/O or writes.
5. A successful decision rechecks the entire candidate/evidence snapshot. The
   native post hook closes the frame and signs its results with a process-local
   HMAC bound to profile/backend/session/sender/turn and current human text. The
   automatic writer validates this proof and rechecks selected active card/evidence
   before a new write. A forged/missing/stale/cross-scope result is unresolved.

No public CLI sets native decisions. `identity-resolve` is read-only discovery.
All third-party natural references, including `본인`, need current-agent judgment;
only reserved internal narrator token `self` resolves protected self metadata.
The distinction does not establish the speaker of a quoted first-person claim.

## Evidence and state

Identity context may come from actual native user/assistant conversation history;
assistant/tool/summary text is NEVER a new claim source. New ordinary memory claims
must independently pass current genuine human source/subject/ontology validation.
The established source window is 4,000 characters; the existing full-human identity
hash continues to distinguish truncated inputs. No entire transcript is persisted.
The auxiliary post-turn classifier still extracts claims; it no longer decides the
person identity. One post-turn writer owns persistence. Its accepted extraction,
request bodies, receipts and outcomes retain once-only/idempotency semantics.

Frames are process-local, bounded to 128, expire after one hour and close at post.
No prior-turn decision is an automatic next-turn authorization. Repeat the handoff,
not the user question, when conversational context already clearly identifies them.
Background work captures the admitting context AND an explicit native home override
so another profile/environment cannot redirect its journal or backend work.

Old `identity_pending`, `identity_deferred`, clearances and request/outcome history
are preserved. New decisions never clear, reinterpret or blindly replay old claims.
A separately authorized historical recovery is not part of this integration.
No failed lookup creates people, aliases or merges.

## Verification

`scripts/test_main_agent_identity.py` uses the actual host PluginContext hook/tool
registration, ToolRegistry dispatch, tool-execution middleware, pre/post hook
invocation and post-turn writer, against disposable synthetic backend/journal state.
It covers variant/unfamiliar names, conflicting alternatives, missing/forged tokens,
source/ref/quote integrity, scope/sender/turn/profile/backend isolation, staleness,
changed referents, retry/duplicate protection, old journal preservation and async
profile pinning. It does not prove live model understanding or gateway adoption.
Existing Bot Chat runtime probes must establish installed, loaded, tool-visible and
actual harmless tool execution separately. Never publish synthetic person facts to
a real backend as a smoke test.
