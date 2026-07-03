# Frontend Knowledge

## OVERVIEW

React/Vite Web control plane for inspecting and correcting Kinlayer context.

## STRUCTURE

```text
frontend/
├── src/App.tsx       # route shell and navigation
├── src/routes/       # screen components
├── src/api/          # typed API client and token handling
├── src/types/        # frontend API types
├── src/styles.css    # app styling
└── package.json      # npm scripts
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Add/change route | `src/App.tsx`, `src/routes/` | Keep route visible in nav when user-facing |
| API calls | `src/api/client.ts` | Web is a client of the canonical API |
| Type shape | `src/types/` | Mirror backend response contracts |
| Tests/build | `src/*.test.tsx`, `src/api/*.test.ts`, `package.json` | Vitest + TypeScript build |
| Manual QA | `../scripts/web-smoke-checklist.md` | Use browser when feasible |

## CONVENTIONS

- No Web-only state-changing capability. Add or adjust the backend API first.
- Normalize local browser targets to explicit `http://...` URLs.
- Vite dev/preview uses `0.0.0.0:5173`; Docker exposes Web on `5173`.
- API defaults come from the current browser host plus `:8765` unless
  `VITE_KINLAYER_API_URL` is set.
- Local API token is user-entered in Settings; secret values are not re-displayed.
- Heavy admin/review details should stay secondary by default when possible.

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
