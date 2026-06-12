# Kinlayer Agent Integration Notes

- Status: Draft v0.1
- Scope: Future integration with Hermes/Som, other AI agents, skills, plugins/tools, MCP, and memory-provider hooks
- Parent PRD: `../specs/prd.md`

---

## 1. Purpose

Kinlayer MVP should focus on the core product:

- local backend;
- Postgres canonical store;
- HTTP API;
- CLI wrapper;
- minimal Web UI;
- candidate/control loop;
- retrieval and context output contracts.

Deep agent-runtime integrations should not block MVP implementation. They should be treated as follow-up adapter work once the core APIs stabilize.

---

## 2. Integration Principle

Kinlayer should expose stable product APIs first, then layer agent integrations on top.

Recommended sequence:

```text
1. Core HTTP API + CLI
2. Reference skill / instruction pack
3. Native plugin/tool adapter
4. MCP adapter
5. Runtime memory hook / provider-style integration
```

Do not let any single agent runtime shape the core product too early.

---

## 3. Phase 1 — Reference Skill / Instruction Pack

A skill-like integration is the fastest way to dogfood Kinlayer without patching an agent runtime.

Canonical write guidance lives in `agent-write-instruction-pack.md`. Skills, plugins, MCP adapters,
and runtime hooks should use that pack when deciding how to submit candidates, apply explicit
corrections, select ontology-controlled values, and handle no-write/clarification cases.

Purpose:

- teach the agent when to call Kinlayer;
- define retrieval triggers;
- define how to interpret Person Context Cards and Context Packs;
- define when to submit candidates;
- define when explicit user correction can be applied directly;
- define fallback behavior if Kinlayer is unavailable.

Example responsibilities:

```text
- person/relationship mention → retrieve context
- message drafting / meeting prep / ambiguous pronoun → retrieve context pack
- new detected relationship context → submit candidate
- explicit user correction → apply correction directly
- uncertain inferred correction → submit conflict/supersede candidate
```

Limitation:

- Skills are instructions, not enforced runtime hooks.
- Candidate extraction may be missed if the agent does not follow the skill.
- This is good for dogfood, not final deep integration.

---

## 4. Phase 2 — Native Plugin / Tool Adapter

For Hermes/Som or other tool-capable agents, Kinlayer should expose native tools backed by the local HTTP API.

Possible tool set:

```text
kinlayer_retrieve
kinlayer_get_context_card
kinlayer_get_context_pack
kinlayer_submit_candidate
kinlayer_apply_correction
kinlayer_list_candidates
kinlayer_accept_candidate
kinlayer_reject_candidate
kinlayer_list_agent_write_operations
kinlayer_export_agent_write_operations
```

Benefits:

- structured schema;
- stable tool calls;
- easier candidate/correction submission;
- less dependence on free-form CLI parsing;
- better integration with agent reasoning loops;
- easier postmortem review of what agents attempted to write and what Kinlayer accepted or rejected.

This is the likely best first deep integration for Som after Kinlayer MVP is functional.

Agent write operation export is deliberately narrower than a full audit timeline. It includes AI-agent write attempts and results only: candidate submit/accept/edit-accept and correction apply records, plus bounded refs/excerpts/diagnostics. It excludes retrieval reads, full prompts, raw conversation transcripts, bearer tokens, API keys, and ordinary container logs.

---

## 5. Phase 3 — MCP Adapter

An MCP adapter can expose Kinlayer to MCP-aware agents and tools.

Possible MCP tools:

```text
kinlayer.retrieve
kinlayer.contextCard
kinlayer.contextPack
kinlayer.submitCandidate
kinlayer.applyCorrection
kinlayer.listCandidates
```

MCP is useful for portability, but it should not be the core MVP integration contract. The core should remain HTTP API + CLI.

---

## 6. Phase 4 — Runtime Memory Hook / Provider-Style Integration

A deeper integration could call Kinlayer automatically before and after agent turns.

### Pre-response hook

```text
incoming user message
→ detect relationship/person trigger
→ call Kinlayer retrieve/context pack
→ inject policy-labeled context into agent prompt
```

### Post-turn hook

```text
conversation turn completed
→ extract possible people/relationships/observations/corrections
→ submit candidates or trusted correction apply
```

Benefits:

- less reliance on the agent remembering to call tools;
- more natural memory behavior;
- better candidate accumulation.

Risks:

- over-triggering;
- noisy candidates;
- hidden context use if not surfaced/explainable;
- tighter coupling to a specific agent runtime.

This is later work after the core product and tool integration are stable.

---

## 7. Relationship to `gyurin-personal-context`

For Som/Hermes dogfood, a future Kinlayer skill can replace relationship-state storage currently handled by file-based personal-context flows.

Target split:

```text
gyurin-personal-context / future skill = routing and policy instructions
Kinlayer = canonical relationship context store
Hermes plugin/tools = structured access layer
```

Do not use skills as the canonical relationship database once Kinlayer exists.

---

## 8. MVP Boundary

For the first Kinlayer MVP implemented by Codex/Claude Code, this document is non-blocking reference.

MVP should only include:

- HTTP API stable enough for future adapters;
- CLI wrapper for local use;
- output schemas suitable for tool/plugin/MCP use later.

Skills, Hermes plugins/tools, and runtime hooks are follow-up work after MVP completion.
