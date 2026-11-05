# AFTERTRACE — contributor reference

Latest increment: [connected records and reliability panels](AFTERTRACE_CONNECTED_WORKFLOW.md).
The existing SVG graph now includes row nodes whose removal follows verified SQL deletion.
SQLite mapping, typed requests and bounded recovery/sync experiments share the same input/run.

The default product now uses the four-step [one-dataset workflow](AFTERTRACE_WORKFLOW.md), including
isolated SQLite remediation with fresh read-back verification. That document supersedes the
ten-chapter navigation below; those chapters remain a development archive for renderer checks.
Original audit decisions/CSV and working-copy execution results remain separate.

Updated 5 November 2026. This is the shared implementation reference for the frontend, backend run
visualisation and graphs. It describes implemented code and its limits, not guaranteed accuracy or
production readiness. Read root `AGENTS.md` and the ownership/delivery notes before editing.

## Product and truth boundary

AFTERTRACE is SLAM's evidence-focused deletion-audit workspace. The engine identifies the subject,
finds current/historical identifiers and relevant copies, reconstructs state at `audit_at`, applies
policy, analyses recreation paths and produces an evidence-backed answer with ordered steps.
The frontend exposes that work; it does not independently decide deletion status.

| State | Meaning |
| --- | --- |
| Execution finished | Processing finished; it does not establish that deletion is complete. |
| `COMPLETE` | The engine established the required compliant state. |
| `INCOMPLETE` | Violations remain or the engine cannot certify completion. Inspect the uncertainty reasons. |
| `NOT_APPLICABLE` | The request does not authorize deletion. |
| No status / blocked | No exportable answer was established. Never substitute `COMPLETE`. |

The current full-bundle planner can return `INCOMPLETE` with `trace.not_certified_because` while
allowing an incomplete result to be exported. This is different from `ready_for_export=false`.
Execution success, export readiness and deletion completeness must remain separate UI concepts.
No frontend interaction executes external record deletion, connector shutdown or restore blocking.

## Integration baseline and technologies

Frontend work was preserved in `4359a8f`, then merged with GitHub `dev` at `b4382c9`, incorporating
newer CLI, ownership/account linking, provider, reports and tests. Use the latest `dev` containing
this reference. The shared contract stays **1.1.0**; web metadata does not change its schema hash.

| Layer | Technology / source |
| --- | --- |
| Interface | React, TypeScript, Vite; exact versions in `frontend/package-lock.json` |
| Identity renderer | Existing HTML button nodes over SVG paths, same IDs and original anchors |
| Original HTML renderer | Existing plain-JavaScript `DiGraph`, node-link JSON and SVG generation |
| Other scenes | HTML/CSS/SVG; no WebGL requirement |
| API | FastAPI and Pydantic web read models |
| Ingestion | Python loaders/parsers, PDF/image/OCR support, SQLite/FTS5 ledger and cache |
| Identity/state | Current and historical identity resolution, ownership closure, cutoff reconstruction |
| Dependency graph | NetworkX; flows, restore paths, ownership and cycles |
| Policy/output | Deterministic Python planning, validation and exact CSV serialization |
| Models | Existing server provider factory and metering; OpenAI/Groq where configured |
| Live transport | POST response streamed as server-sent events, consumed with Fetch |
| Checks | pytest, Ruff, mypy, Playwright; locked Python packages in `uv.lock` |

Do not install a replacement graph library as a styling shortcut. Do not independently upgrade
dependencies on each teammate's machine. The graph/live workspace uses Manrope, Inter and IBM Plex
Mono, all self-hosted, with cloud white/slate/blue/teal/amber/coral/grey materials. Other earlier
chapters retain their existing art direction.

## Actual backend pipeline

The CLI is `code/main.py`; composition is `code/slam/pipeline.py`. The live adapter is
`code/slam/web/live.py`, using the same underlying functions with real execution checkpoints.

| Phase | Code | Actual output shown |
| --- | --- | --- |
| Read/extract | `ingestion.ingest`, loaders and parsers | Source IDs/hashes, parser states, observations, issues and cache hits |
| Learn attribution | `reconstruction.linking.fit(bundle, cohort)` | Ownership index and validated timing groups |
| Interpret request | `request_intent.interpret_request` | Actual intent and deterministic/model basis |
| Resolve identity | `identity.resolve_identity` | Subject, current/historical links and proof |
| Link resources | `ownership.owned_by`, attribution results | Explicit/closure ownership, inferred resources and review candidates |
| Reconstruct state | Timeline, absence and retention helpers | Eligible/later observations and resource states |
| Analyse graph | `graph.build_dependency_graph` | Actual flow/restore links, coverage issues and cycles |
| Apply policy | `planning.engine.plan_case(context, bundle)` | Findings, remediation, verification and uncertainty reasons |
| Validate | Pydantic, `validate_answer`, CSV exporter | Final answer, readiness and output rows |

The frozen `planning.plan(context)` remains a conservative context-only compatibility entry point.
The CLI and live UI use `plan_case(context, bundle)`, which can inspect record exposure. Do not swap
these entry points silently; their input context and uncertainty handling differ.

L1/L2 ownership and L3 timing attribution do not merge identities. Timing-derived associations carry
review requirements. They must not become exact verified links merely because a timing group exists.
Selected dataset runs still fit attribution on the known request cohort, as the CLI does.

Demo mode loads the existing fictional corpus and runs the real engine. It does not pretend to OCR
participant files. Dataset mode actually invokes ingestion. Neither mode reads organizer-only truth.

## Live execution protocol

`POST /api/runs/stream` accepts:

```json
{"mode":"demo","case_id":"demo_024","scope":"case","cutoff":null,"use_model":false,"max_model_calls":4}
```

`scope` is `case` or `all`. Full runs use each request's original cutoff; overriding it for `all`
is rejected. Responses are `text/event-stream` frames with `event: execution` and JSON `data`.

| Event | Meaning |
| --- | --- |
| `run.started` | Run ID, mode/scope, actual provider choice and no-external-mutation boundary |
| `source.completed` | Actual parser/cache result and source counts |
| `stage.started` / `stage.completed` | Enter/leave an actual backend operation |
| `stage.skipped` | Work did not run, e.g. deletion graph for a non-deletion request |
| `case.started` / `case.completed` / `case.failed` | Case execution lifecycle, separate from audit status |
| `model.started` / `model.completed` / `model.failed` / `model.blocked` | Real calls, returned metadata, failures and limits |
| `run.completed` | Processed/blocked counts, actual answers, measured usage and CSV if permitted |
| `run.failed` | No completed execution is assumed |

Frames carry sequence, UTC event time, measured elapsed milliseconds and case ID when known.
Identity/timeline/graph/validation completion can attach a read-model snapshot. Preview answers are
unexportable until actual planning and validation finish. Presenting a snapshot does not rerun policy.

Validation also emits the exact server-generated single-case CSV. Opening that run's folio preserves
its validated export bytes instead of rerunning an ambiguous request without its model proposal.
Evidence inspection carries the executed case snapshot, including during a batch run.

`runtime/events.py` uses a context-local observer. `ingest`, `reconstruct` and `plan` keep their frozen
signatures. With no observer, telemetry has no decision effect. No prompt contents or keys enter events.

The frontend follows real events, not timers or simulated percentages. Fast deterministic stages may
finish within one browser frame. Selecting an executed stage inspects its recorded snapshot, not a new
computation. The browser retains the latest 1,000 journal events and current-case stage snapshots.
The server uses a bounded 128-item queue and one active run per API process. Disconnecting requests
cancellation at a checkpoint; an in-flight synchronous provider call may finish. No terminal result
is invented after a dropped connection. Process restarts lose in-memory runs.

## Models and API keys

Keys stay in the server environment or ignored `.env`. `GET /api/runtime` exposes readiness and
provider/model name, never keys. The UI's model option is opt-in and disabled for incomplete server
configuration. Existing provider-factory and metering controls are reused, including Groq key handling.

Models assist image extraction and ambiguous-request interpretation. They do not own policy, identity
truth, graph ordering, deletion status or export readiness, and receive no write tools. A clear request
can need zero calls even with a configured model. Display that actual outcome.

Use `.env.example` for provider/model/key settings. Set `SLAM_API_MAX_CALLS` and applicable token/cost
settings. The UI's call ceiling only lowers the server ceiling. Logical calls, retries, returned
tokens and request IDs are reported when available. Unknown usage stays unknown. Offline tests do not
establish real provider performance or paid-run cost. Do not display prompts, secrets or thought text.

## Frontend chapters

| Chapter | Purpose |
| --- | --- |
| Portal | Investigation entry and actual read-model counts |
| Source Nebula | Manifest and parser states |
| Identity Constellation | Backend identities, relationships, validity and proof |
| Forensic Desk | FTS5 search and original sources |
| Time Machine | Cutoff reconstruction and ineligible later evidence |
| Decision Chamber | Actual policy/evidence/verification stages |
| Audit Folio | Actual steps, uncertainty reasons, print and permitted CSV |
| Experiment Observatory | Diagnostics; unmeasured experiments remain unmeasured |
| Intelligence Console | Explicit imported analysis or separate current-case data |
| Live Backend Execution | Real phase stream, graph snapshots, model activity and final output |

## Relationship semantics and graph preservation

Existing fields stay compatible: `id`, `source`, `target`, `relationship`, `state`, `evidence_ids`,
`valid_from`, `valid_to`. Optional web metadata adds verification, direction, source details, systems,
event time, lifecycle event and conflicting evidence. The shared engine contract is unchanged.

| Supplied data | Appearance |
| --- | --- |
| Exact, eligible active relationship | Solid teal, verified |
| Explicit confirmed/corroborated active association without review requirement | Solid blue |
| Candidate/review required or unverified | Dashed amber |
| Explicit relationship conflict / conflicting proof | Coral, inspect its citations |
| Reliable validity end at/before cutoff | Muted grey ENDED edge and removal marker |
| Explicit evidenced removal/deletion event | Grey REMOVED/DELETED relationship with actual timestamp/proof |
| Later start or only later evidence | Excluded from cutoff view |
| Missing edge | No deletion conclusion |

The current identity engine supplies validity ends, so the web adapter emits **ENDED**, not DELETED.
It does not emit entity-deletion events or invent per-link conflicts from global resource conflicts.
Optional lifecycle UI is tested with explicit test-only fixtures; a real producer must supply actual
event type/time/citations before those states can appear live. Entity deletion is separate.

Current mode excludes ended links; history retains them with provenance. Exact search, type/status/
system filters, node/edge selection, endpoint/neighbourhood focus, Escape, pan/zoom/fit/reset,
expansion/collapse, path focus and evidence inspection use the existing renderer. Original eight
anchors remain; extra positions are deterministic and larger graphs initially render 40 nodes.
Invalid endpoints/timestamps are diagnosed, not silently drawn. Missing metadata is not invented.

The original supplied HTML is `docs/reference/ghost-data-console.original.html`; its enhanced copy
is `frontend/public/reference/ghost-data-console.html`. Original `DiGraph`, node-link JSON, SVG
generation, IDs, selection/removal handlers, undo and snippet export remain. Open it from Intelligence
Console → System graph → Open preserved original HTML graph.

Edit `frontend/public/reference/graph-enhancements.js` / `.css`, then run
`python frontend/scripts/prepare-original-graph.py` before building. Original graph mutations are
local scenarios. Historical scenario mode says REMOVED IN SCENARIO, without an invented observed
timestamp. `first`/`last` event windows are not validity intervals or proof of active verification.

Imported counts/forecasts remain supplied aggregates. The original attachment hash is recorded in
`frontend/src/console/provenance.json`; its raw evidence/build script was not attached. SLAM never
uses that imported JSON for predictions. Current-case mode does not borrow imported numbers to fill
missing monthly, replica or retention statistics.

## Setup, tests and integration

```powershell
# repository root
docker compose --profile web up -d --build aftertrace-api
cd frontend
npm ci
npm run dev -- --port 5173
```

Open `http://127.0.0.1:5173`; API docs: `http://127.0.0.1:8000/docs`. Participant inputs belong only
under ignored `dataset/`. Demo/tests require no key. The API binds to localhost and is not an
authenticated public deployment.

```powershell
# repository root
docker compose run --rm slam-dev pytest -q
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
cd frontend
npm run build
npm run format:check
npx playwright install chromium
npm run test:e2e
```

Run frontend suites sequentially when sharing `test-results/`. Python-export tests use `python` on
PATH for standard-library AST validation, not execution of exported code. Screenshots are ignored
under `artifacts/aftertrace/`. Do not commit datasets, caches, secrets, backup ZIPs or private logs.

`ownership.toml` and delivery notes are authoritative. Before independent work, fetch `origin`, switch
to your own branch and merge the latest `dev`; use the shared locks and tests.

| Owner | Continue here / review |
| --- | --- |
| Ashish | Ingestion/parsers/OCR/ledger; review source-completed telemetry and source accounting |
| Manya | Identity, ownership, attribution, temporal state and graph; review observer checkpoints and actual lifecycle metadata |
| Satvika | Policy/validation/export; review conservative compatibility API versus full-bundle planning before consolidation |
| Lalith | Contracts/runtime/model metering, frontend/web, Docker and evaluation infrastructure |
| Integrator | Cross-owner seams, reports, packaging, merged checks and participant-data validation |

Declare cross-owner edits in delivery notes. Shared-contract changes require the contract changelog
and approval workflow. This reference does not imply every contributor has reviewed/adopted the edits.

## Limits and verification record

The participant dataset is absent here. A fresh full 518-case run, sample accuracy, full-dataset
latency/cost and live-provider behaviour cannot be claimed from demos. Existing reports record earlier
runs, not measurements of this UI integration. External remediation, external-system verification,
autonomous self-healing/promotions, unrestricted uploads, durable multi-user jobs and public auth are
not implemented. Explicit relationship/entity deletion producers are still a backend data requirement.

Verification on 5 November 2026: the merged Python suite passed 625 tests with 34 skipped; the final
changed web subset passed 16 tests. The frontend suite passed 31 checks, including 25 browser flows.
Production build, frontend formatting, Ruff, mypy (64 Python source files) and whitespace checks
passed. These checks establish the tested behaviour, not participant-dataset accuracy or live-model
performance. The delivery note records the scope and cross-owner review requests.
