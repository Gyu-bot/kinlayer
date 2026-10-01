# Frontend replacement design QA

**final result: passed**

2026-10-01, active frontend project. The approved target is the supplied Korean mockup with the
user-approved save-first adjustments. This is design acceptance of the replacement, not a claim of
pixel-identical data, completed production deployment or validation on every browser.

## Comparison evidence and normalization

Reference truth: `../frontend_v2/README.md`, `DESIGN.md`, audited source `styles.css` and
`../frontend_v2/evidence/21-people-desktop.png` through `28-reviews-mobile.png`.
Implementation: local `http://127.0.0.1:5173`, real API on 8785 with a disposable fictional database;
captures and combined comparison inputs are in `../docs/verification/frontend-v2/`.

Requested CSS viewport: 1440×1000 desktop, 390×844 mobile, DPR 1. The browser exporter produces
1425×990 for scrolling desktop views, 1440×1000 for the graph, and 375×812 for scrolling mobile views.
Source and implementation PNG dimensions are identical for every pair; comparison assembly did
not resize either side. These export dimensions are distinct from CSS viewport and DOM measurements.
Each montage adds a 32px label strip outside the screenshot content.

The actual source and replacement were opened together in these combined inputs, not judged from
separate images or code alone:

- [People desktop](../docs/verification/frontend-v2/comparison-people-desktop.png),
  [mobile](../docs/verification/frontend-v2/comparison-people-mobile.png): list mode, all people,
  Minji selected. Server ordering/timestamps differ from the mock's invented recent-reference times.
- [Person desktop](../docs/verification/frontend-v2/comparison-person-desktop.png),
  [mobile](../docs/verification/frontend-v2/comparison-person-mobile.png): Minji overview.
- [Graph desktop](../docs/verification/frontend-v2/comparison-graph-desktop.png),
  [mobile](../docs/verification/frontend-v2/comparison-graph-mobile.png): actual self at center,
  Minji selected, all direct relations, 100% zoom. Node order follows actual API results.
- [Changes desktop](../docs/verification/frontend-v2/comparison-changes-desktop.png),
  [mobile](../docs/verification/frontend-v2/comparison-changes-mobile.png): source review composition
  versus approved changes composition. Both show a selected row and old/new/source detail; the old
  approval action/state has intentionally been replaced with persisted history.
- [People detail crop](../docs/verification/frontend-v2/comparison-people-detail.png) and
  [Person detail crop](../docs/verification/frontend-v2/comparison-person-detail.png) were inspected
  to compare readable typography, icons, tab spacing, cards and controls at source scale.

## Findings and corrections

- **P2, resolved — mobile changes detail pushed below 20 rows.**
  [Initial](../docs/verification/frontend-v2/changes-mobile-initial.png) had an unbounded queue.
  The queue now scrolls within 360px on narrow layouts, preserving its heading and pager, with detail
  immediately below. [Final](../docs/verification/frontend-v2/changes-mobile.png) and the combined
  source comparison were inspected after the fix.
- **P2, resolved — overview hierarchy lost the compact profile block.**
  [Initial](../docs/verification/frontend-v2/person-desktop-initial.png) mixed all memory kinds.
  The overview now separates compact structured facts from observation context, with full-profile
  and full-memory links. [Final](../docs/verification/frontend-v2/person-desktop.png) and the focused
  source comparison restore the intended two-column hierarchy.
- **P2, resolved — keyboard focus after closing the editor.**
  Browser verification found Escape returning focus to the document body. Dialog lifecycle cleanup
  now closes before removal and restores the opener. A fresh Enter → Escape check at 320px returned
  focus to “기억 추가”; the [form](../docs/verification/frontend-v2/memory-editor-mobile-320.png)
  keeps its action footer visible without horizontal overflow.

No remaining actionable P0/P1/P2 was found in the final comparisons. The original audit's fixes
remain in the imported source; additional data/contract regressions are covered in the verification
record and are not counted as visual-QA iterations.

## Required fidelity surfaces

| Surface | Final assessment |
| --- | --- |
| Fonts and typography | Original system/SF text and display fallback stacks, 14px body, 32px desktop heading, 600 heading weight and 1.75 body line height retained. Korean wrapping, tab labels and focused crop hierarchy checked. No substituted web font. |
| Spacing and layout | Original 212px desktop sidebar, neutral header, 12px card radii, list-plus-inspector and radial graph composition retained. Additional navigation and forms use the same controls. Mobile stacks cards and exposes persistent four-item bottom navigation. |
| Colors and tokens | Original OKLCH foreground/background/border/accent/state tokens copied from the supplied stylesheet; selected rows, blue actions and quiet surfaces remain consistent. Inferred/unknown are provenance labels, not green truth/approval badges. |
| Image quality and assets | Original supplied logo and icon vector paths reused; no screenshot-backed UI or invented raster placeholders. Graph circles/lines are interactive data marks. Name avatars are the same intentional source convention. Crops show crisp original icon and text rendering. |
| Copy and content | Korean UI retained. Approved changes remove confirmed/policy/approval language, add memory/history/source controls, and show missing values honestly. Future or uncertain employer wording remains an observation, partial birthday has no invented year. |

## Intentional differences and limits

The user approved the audit proposals: review becomes changes; reported/inferred/unknown replace
confirmation/policy; actual self and all ontology relations replace hardcoded categories; remembered
claims and source links come from the server. Therefore exact row order, counts, author/time and
panel lengths differ. The graph inspector displays the selected relation's exact evidence rather
than a fabricated person summary. These are accepted behavior changes, not hidden fidelity misses.

Desktop/mobile source comparisons and all 24 route/width DOM checks passed. Small phone graph
labels are supported by zoom and a full relationship list. Optional P3 follow-up is tuning the
phone graph heading/action spacing after real-device use. No open product choice blocks this build.
Full assistive-technology certification, other engines and real-device keyboard appearance were
not assessed. Production checks remain separate.

## Implementation checklist

- [x] Import and preserve the source design; replace the active frontend.
- [x] Keep typography, tokens, original icons and responsive compositions.
- [x] Capture and compare matching desktop/mobile source states, with explicit approved differences.
- [x] Fix the overview, mobile queue and dialog focus; inspect revised evidence.
- [x] Verify real API writes, history/source retention, regression tests and production build.
- [x] Keep the fictional local preview available and document deployment boundaries.
