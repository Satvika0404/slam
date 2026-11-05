# Ghost Data Console → AFTERTRACE

The supplied `Ghost Data Console (Copy).html` is integrated as the ninth chapter. It is a native
React/TypeScript feature, not a screenshot or embedded copy of the original page.

## Coverage

| Supplied console capability | AFTERTRACE implementation |
| --- | --- |
| Three accessible section tabs | Error patterns, Retention conflicts, System graph; arrow/Home/End navigation |
| Evidence window and counts | Analysis source selector, explicit snapshot/case provenance and source record |
| Outcome KPIs and monthly projection | Four metric strips, inspectable observed/forecast SVG chart and method note |
| Pattern catalogue | All 14 entries, group/search filters, expandable notes, statistics and citations |
| System/month heatmap | Original counts and denominators; samples below five remain unscored |
| Operation/system predictor | Adjustable selectors, class-shrunk estimate and separate observed Wilson interval |
| System risk ranking | All supplied system rows with rates, samples and next-month ranges |
| SQL replica drift | All 14 comparison rows; citation inspector; snapshot counts remain distinct from unique records |
| Retention conflict register | All nine entries, independent severity/category filters and source interpretations |
| Ageing explorer | 30–240-day slider with 30-day bands; clearly an exploratory assumption |
| Retention-year chart | Supplied security, legal and finance-register series |
| Superseded identifiers | All three supplied field summaries; no identity merging based on counts |
| Legal holds | Six finance-register rows and citation; no automatic release or deletion |
| Policy rules | All 15 rules with category, condition and action |
| Directed system map | 22 nodes and 18 original edges, source flags, pan/zoom/reset and neighborhood focus |
| Observed vs inferred links | Dashed inference with source rationale; optional visibility filter |
| System database table | Search and policy filters; select/clear DELETE-policy stores; inspect remaining or removed nodes |
| Graph queries | Predecessors, successors, ancestors, descendants and downstream reach; self excluded even in cycles |
| Detach/cascade simulation | Removal preview, newly orphaned DELETE cascades, cycle and retention warnings |
| Link changes | Local simulated disable/block/detach operations; no external execution |
| Undo and reset | Restores graph and history; scenario persists across chapter and section navigation |
| Open conflicts and action log | Recomputed scenario flags, lost incoming links, retention-node removal and equivalent graph calls |
| NetworkX snippet | Readable Python with all current attributes, clipboard copy and `.py` download |

## Data boundary

`frontend/src/console/snapshot.json` contains only the JSON aggregate extracted from the user-supplied
HTML. `provenance.json` records the original attachment hash. The existing Python engine never reads
these files. No source documents, organizer-only data, raw evaluation labels or new predictions were
added to the engine.

The original document references dataset files and `dashboard/build_data.py`; those raw sources and
the build script were not attached. Imported counts, narratives, confidence labels, inferred links and
forecasts therefore remain supplied analysis. An evidence ID is not treated as verified merely because
it appears in the attachment. The imported citation inspector shows aggregate references and explicitly
states that the original file or activity row cannot be verified there.

The Current investigation option builds a separate read model from SLAM's case API. It does not imply
corpus-wide operation analytics. Its original evidence links use the existing backend drawer. Missing
history, retention dates, comparative tables or forecast inputs stay missing.

## Implementation

| File | Responsibility |
| --- | --- |
| `frontend/src/scenes/Console.tsx` | Source selection, accessible tabs, provenance and imported citation inspection |
| `frontend/src/console/Patterns.tsx` | Catalogue, trend, matrix, estimate, ranking and drift |
| `frontend/src/console/Retention.tsx` | Register, age lens, holds, dates, identifiers and policy reference |
| `frontend/src/console/SystemGraph.tsx` | Interactive directed map, reversible scenarios, conflicts and export |
| `frontend/src/console/model.ts` | Cycle-safe traversal, SCC ordering, cascade boundaries, Wilson interval, literal-only Python export and current-case adapter |
| `frontend/src/console/console.css` | Scoped visual system, responsive layouts and reduced motion |
| `frontend/e2e/console.spec.ts` | Pure algorithm checks and integrated browser coverage |

Run `npm run test:e2e` from `frontend` with the local API running. `python` on PATH is used only for
independent AST validation of exported literals. Browser coverage includes imported/current sources,
evidence inspection, filtering, estimates, retention assumptions, reversible graph changes, previews,
chapter persistence, keyboard control, missing dataset, and 360/390/768/1440px layouts. Screenshots are
written to ignored `artifacts/aftertrace/console/`.

Integration verification on 2026-11-05: all 22 frontend checks passed (three pure graph/export checks
and 19 browser flows), and 449 Python tests passed with 30 skipped. Production build, formatting and
`git diff --check` passed. The imported JSON was compared against the original HTML and its SHA-256
was verified. No Python audit-engine files were changed during this integration.
