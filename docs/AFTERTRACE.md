# AFTERTRACE — investigation workspace

For the current merged architecture, live execution, graph semantics and contributor boundaries,
start with [AFTERTRACE_CONTRIBUTOR_REFERENCE.md](AFTERTRACE_CONTRIBUTOR_REFERENCE.md). The dated visual
refinement records below describe earlier passes. The current backend may export an `INCOMPLETE`
answer with explicit `not_certified_because` reasons; that is not certification of `COMPLETE`.

AFTERTRACE is the local React/TypeScript interface for SLAM. It presents supplied evidence,
historical identity relationships, audit-time reconstruction and deterministic planning.

## Run locally

Requirements: Docker Desktop, Node.js 22.12+ (or a compatible supported LTS version), npm.
Development was checked with Node.js 24 and Python 3.11 in Docker.

From the repository root:

```powershell
docker compose --profile web up -d --build aftertrace-api
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev -- --port 5173
```

Open http://127.0.0.1:5173. API documentation is at http://127.0.0.1:8000/docs.
Stop the API with `docker compose --profile web stop aftertrace-api`.
The Vite development proxy keeps browser requests on the frontend origin. The API is bound to
localhost. API keys are never sent to the browser; ordinary demo runs use no model calls.

## Data modes

- **Fictional demo:** three explicitly fictional scenarios: surviving copy, compliant state,
  contradictory observations. Source contents and identities are fictional; Python computes the
  reconstruction and answer for every selected cutoff using the same engine functions as dataset mode.
- **Local dataset:** install participant-facing files under the ignored root `dataset/` directory.
  Select Local dataset in the header. Missing inputs produce an explicit error, with no demo fallback.
  Reload sources after changing files. The reload action performs ingestion; it does not claim to
  have audited all requests or modified any external systems.

The demo is a UI regression corpus, not an evaluation benchmark or a measurement of hidden accuracy.
Only eligible evidence can support audit answers. Later evidence remains inspectable in the timeline.
Export in the folio is a **single-case CSV extract**, not the full 518-row submission.

## Visual direction and interactions

The investigation is organized as eight evidence chapters and a ninth intelligence console.
Instrument Serif, Geist and Geist Mono are self-hosted through font packages. Colour expresses evidence
states; icons and written labels carry the same meaning. Geometry uses SVG and CSS so no WebGL or GPU
feature is required. Expensive scene modules load on demand.

| Scene | Composition and working interactions |
| --- | --- |
| Portal | Editorial headline and source orbit, corpus-derived counts, case entry |
| Source nebula | Radial source register, actual parser states, format filter, source inspection |
| Identity constellation | Draggable identifiers, pan/zoom/reset, selectable source-backed edges, history/candidate filters, relationship focus, cutoff control |
| Forensic desk | Source explorer, FTS5 query, paper source extract, view-only trace highlights, provenance |
| Time machine | System lanes, selected observations, comparison, zoom, pointer/keyboard audit boundary, backend state recomputation |
| Decision chamber | Three selectable glass surfaces reflecting actual policy associations, evidence conditions and deterministic results |
| Audit folio | Printable archival report, blocked-state handling, findings and proposed actions, validated case export |
| Experiment observatory | Actual corpus diagnostics, downloadable diagnostic report, explicitly unmeasured evaluation fields |
| Intelligence console | Imported analysis with 14 patterns, nine register entries and a 22-system graph; separate current-case view; forecasts, estimator, retention explorer, reversible graph scenarios and Python export |

Presentation mode supports next/previous, timed playback, pause/resume and exit. Source inspection
remains available during presentation. Ctrl/Cmd+K opens chapter navigation. Reduced-motion preferences
disable transitions. Mobile navigation moves to the bottom; inspectors flow below spatial scenes.

## API and ownership

`code/slam/web/api.py` exposes the local API; `service.py` builds read models; `demo.py` owns only the
fictional corpus; `models.py` validates the case response with Pydantic. `frontend/src/types.ts` defines
the corresponding UI types and `api.ts` handles requests, cancellation and explicit errors.

| Route | Function |
| --- | --- |
| GET /api/health | API readiness and dataset availability |
| GET /api/cases?mode=demo\|dataset | Case list |
| GET /api/cases/{id}?mode=...&cutoff=... | Reconstruct and plan at a timezone-aware cutoff |
| GET /api/cases/{id}/search?q=...&mode=... | Literal-token FTS5 evidence retrieval |
| GET /api/evidence/{id}?case_id=...&mode=... | Original/structured content, hash and extraction locations |
| GET /api/evidence/{id}/raw?case_id=...&mode=... | Original source or faithful structured row |
| POST /api/runs?mode=... | Re-ingest configured local sources and return actual counts/timing |
| GET /api/cases/{id}/export?mode=...&cutoff=... | Strict single-case CSV; blocked cases return 409 |

The current integration merges `origin/dev` at `b4382c9`, including newer ownership/attribution,
reconstruction, full-bundle planning, CLI and provider work. Read models distinguish proof eligibility
from validity intervals. Planning remains Python-owned; live execution uses the full-bundle pipeline
functions and does not animate a separate frontend decision process.

## Checks

```powershell
docker compose run --rm slam-dev pytest -q
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
cd frontend
npm run build
npm run format:check
npx playwright install chromium
npm run test:e2e
```

Start the API before browser tests. Browser tests cover provenance, filters, node drag/zoom, cutoff
reconstruction, conflicting evidence, source search, CSV download, mobile layout, presentation and
missing-dataset behaviour. Screenshots are written to ignored `artifacts/aftertrace/`.
The console export test also uses `python` on PATH to validate generated Python literals with the
standard-library AST parser; it does not execute exported code or require local NetworkX.

## Ghost Data Console integration — 2026-11-05

Open **Intelligence console** from the ninth navigation item or the portal. The supplied HTML was
reimplemented as native React components, sharing AFTERTRACE typography, materials and navigation.
No attachment scripts, external font links or iframe are executed. The console loads as a separate
chunk and remains mounted after first use, preserving scenarios while moving between chapters.

**Imported console snapshot** reproduces the supplied aggregate analysis. Its provenance record keeps
the original filename and SHA-256. Counts, forecasts, confidence labels, policy associations and
observed/inferred graph flags are supplied claims, not independently verified dataset computations.
Original evidence files, activity rows and the referenced build script were absent from the attachment.
Citation inspection shows exactly which aggregate entries reference an ID and explains when the
original source cannot be opened. Imported analysis never enters reconstruction or planning.

**Current investigation** derives its view from the selected case response and audit cutoff. Its
findings, policies, resource systems and engine risk edges remain tied to actual backend results;
citations open the existing evidence drawer. Monthly operations, comparative replica-table rows,
retain-until dates and corpus-wide identity-change counts are not exposed by this case response, so
the corresponding panels state that they are unavailable. No imported value fills those gaps.

All three views include accessible tabs, keyboard controls, explicit empty states and reduced-motion
support. The error-pattern view preserves the catalogue, monthly projections, system/month heatmap,
operation estimator, system ranking and replica-drift register. The retention view preserves the
conflict register, severity/category filters, adjustable age lens, retention-year chart, superseded
identifier summary and legal/finance hold rows, with the full supplied policy reference.

The estimator uses `(failures + 10 × operation-class rate) / (sample + 10)`. Its displayed Wilson 95%
interval describes the original observed sample; it is not an interval on the smoothed estimate.
The forecast bands and regression statistics are supplied by the HTML; their coverage and predictive
performance have not been validated. Supplied narratives about causality or policy violations are
marked as interpretations requiring review.

Graph simulation supports directed predecessor/successor and ancestor/descendant queries, pan/zoom,
neighborhood focus, inferred-link visibility, system search and policy filters, selection, removal
previews, link detachment, undo/reset, conflict summaries, change history and NetworkX Python export.
Strongly connected components provide deterministic downstream ordering; cycles are flagged instead
of being presented as a valid real remediation order. Cascades remove only newly orphaned DELETE
copies; RETAIN and REDACT associations do not cascade. Deliberately removing a RETAIN node displays
a scenario retention conflict. Editing the graph never proves record deletion or disabled flows.

Scenarios are temporary browser memory. They survive chapter/tab navigation, reset when their analysis
source or current-case cutoff changes, and disappear on page reload. Exported Python reconstructs the
scenario with all attributes; it performs no deletion of external data. See
[CONSOLE_INTEGRATION.md](CONSOLE_INTEGRATION.md) for the feature mapping and verification boundaries.

## Presentation refinement — 2026-11-05

The presentation layer now has a more legible metadata scale, improved smoked-glass surfaces and
archival paper, refined node/prism materials, numbered chapter navigation, and interruptible native
chapter transitions with a direct reduced-motion fallback. Retry, loading, search-empty, source-empty,
and connection-error states are explicit and accessible. Styling lives in `frontend/src/refinements.css`;
presentation-state components live in `frontend/src/Presentation.tsx`.

All 13 browser tests passed across the original investigation interactions and added checks for actual
response loading, retry recovery, empty evidence, failed parsing, laptop/mobile overflow, interrupted
navigation, reduced motion, focus handling and WebGL-disabled operation. All 449 Python tests passed
(30 skipped). Production build and source formatting passed. A before/after SHA-256 comparison confirms
that all Python source files were unchanged during this visual-refinement pass. Synthetic UI error/empty
fixtures exist only inside the browser tests; they are not production data providers.

Refined screenshots are in ignored `artifacts/aftertrace/refined/`. This pass refines the current SVG/HTML
presentation; it does not claim that Blender or WebGL scene assets have been implemented.

Initial implementation verification on 2026-11-05: 449 Python tests passed, 30 skipped; all six original browser interaction tests
passed. Production frontend build, source formatting, Ruff and mypy (54 Python source files) passed.
An upstream Starlette test-client deprecation and Lucide client-directive build notices remain
non-failing tooling warnings. Screenshots include desktop scenes and a 390px mobile layout.

## Current limits

The participant dataset was absent during this implementation; live corpus accuracy and full submission
export have not been established. Conditional policies still require grounded applicability from
reconstruction and otherwise block certification. The current planner verifier is deterministic model
and citation validation; it is not a separate external-system verification service. The web interface
does not execute remediation. Evaluation experiments and self-healing cycles are not fabricated; the
observatory currently displays diagnostics and empty evaluation fields. No simulated SSE progress or
pretend PARSED→VALIDATED→INDEXED transitions are shown. Source selection uses the configured local
dataset rather than unrestricted browser filesystem uploads.
