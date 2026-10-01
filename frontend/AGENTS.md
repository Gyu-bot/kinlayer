# Frontend Knowledge

## OVERVIEW

React/Vite Web control plane for inspecting and correcting Kinlayer context. The
2026-10-01 user-approved replacement uses the imported `../frontend_v2/` design
and Korean UI; the active implementation is `src/v2/`, not the static mockup.

## STRUCTURE

```text
frontend/
├── src/App.tsx       # route matching, navigation and compatibility addresses
├── src/v2/          # replacement screens, shell, memory editor and read contracts
├── src/api/          # typed API client and token handling
├── src/types/        # retained supporting API types; v2/data.ts is the memory contract
├── src/styles.css    # app styling
└── package.json      # npm scripts
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Add/change route | `src/App.tsx`, `src/v2/Shell.tsx` | Primary people/memories/graph/changes; secondary search/settings/legacy |
| Memory/source/history | `src/v2/MemoryEditor.tsx`, `Memories.tsx`, `Person.tsx` | Exact record refs, actual sources and API-only memory changes |
| API calls | `src/api/client.ts`, `src/v2/data.ts` | Canonical request/token handling and read resources |
| Type shape | `src/v2/data.ts`, supporting `src/types/` | Mirror current backend schemas, not old policy fields |
| Tests/build | `src/*.test.tsx`, `src/api/*.test.ts`, `src/v2/*.test.tsx`, `package.json` | Vitest + TypeScript build |
| Manual QA | `../docs/verification/frontend-v2/README.md`, `../scripts/serve-frontend-demo.py` | Browser evidence and disposable non-production API; original checklist remains historical context |

## CONVENTIONS

- No Web-only state-changing capability. Add or adjust the backend API first.
- Normalize local browser targets to explicit `http://...` URLs.
- Vite dev/preview uses `0.0.0.0:5173`; Docker exposes Web on `5173`.
- API defaults come from the current browser host plus `:8765` unless
  `VITE_KINLAYER_API_URL` is set.
- Local API token is user-entered in Settings; secret values are not re-displayed.
- Only that user token belongs in localStorage; people, memories, evidence and
  changes are API state. `frontend_v2` demo storage is reference-only.
- Create/correct/retract/reattribute memory through `POST /api/memories` after
  checking `system/config.memory_write` contract v2. Identity/name/alias actions
  use entity/alias APIs. Do not restore legacy fact/edge/observation mutation paths.
- Preserve claim basis, uncertainty, partial dates, participant roles, independent
  source/event/validity timestamps and exact old refs. Failed writes retain drafts
  and reuse a request ID only when the body is unchanged, including on LAN HTTP.
- Heavy admin/review details should stay secondary by default when possible.
- Historical candidate/agent operations are read-only; no approval or AI-use-policy
  controls. Embedding configuration readiness and indexed-record readiness differ.
- `VITE_KINLAYER_PREVIEW_LABEL` explicitly marks disposable fixture sessions; normal
  production builds do not set a demo label or point to the fixture API.

## ANTI-PATTERNS

- Surfacing raw IDs as primary UI copy when a name/context label exists.
- Adding state transitions that do not exist in backend routes.
- Declaring ontology labels or edge values in UI without reading the API/registry.
- Reporting UI work complete without a browser or equivalent visual check when feasible.

## COMMANDS

```bash
npm test
npm run build
npm run dev
npm run preview
```
