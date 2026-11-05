---
owner: lalith
workstream: Contracts, runtime, evaluation, Docker
status: READY_FOR_INTEGRATION
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: 80f8a59
merge_after: none
last_updated: 2026-11-05
---

# Lalith — AFTERTRACE, runtime and integration delivery

## Delivers

- Headline-feature dashboard increment: the Intelligence Console now opens with two explicit,
  first-class experiences named **Self-Healing Agent** and **Pattern Recognition Engine**. Each
  card reports current-run measurements and links to inspectable evidence. Recovery shows
  detect/recover/retry/validate state and never claims a repair without validation. Pattern
  recognition shows validated model count, grounded training pairs, case links and abstentions;
  the detailed view retains candidates and supporting activity IDs.
- Combined-dashboard increment: AFTERTRACE remains the authoritative single-request execution
  surface, while the newer insight console remains available for deep cohort analysis. The
  Intelligence Console now embeds its strongest non-duplicated capabilities: five-fold
  out-of-fold LightGBM failure-risk triage, DBSCAN recurring-failure signatures and NetworkX
  recreation paths. `docs/AFTERTRACE_DASHBOARD_INTEGRATION.md` records the selection and truth
  boundaries. Small runs explicitly refuse model scoring instead of displaying unstable metrics.
- Connected increment: `docs/AFTERTRACE_CONNECTED_WORKFLOW.md` documents explicit SQLite table mapping,
  typed requests, the existing graph extended with record nodes, verified deletion animations,
  source evidence chains, historical replay and current-run recovery/pattern/sync panels.
- Merged the newer `origin/lalith` reliability/evaluation work into the current pipeline at 80f8a59.
  Bounded recovery and evidence diagnostics now have measured UI paths; production promotion remains
  an explicit review boundary. Working code was checkpointed at 526e78f before the user's later
  instruction to defer further pushes until the complete combined result is verified.
- Current increment: `docs/AFTERTRACE_WORKFLOW.md` specifies the four-step, one-input workflow:
  Dataset -> Audit -> Intelligence Console -> Final report. The old chapters are a development
  archive; no demo/imported-analysis selector appears in the default product.
- `code/slam/web/workflow.py` pins input bytes, runs the actual keyless pipeline once and scopes
  cases/evidence/CSV to that run. ZIP input validates paths/limits and never replaces source files.
- `code/slam/web/remediation.py` performs real SQL DELETE/UPDATE only in isolated per-request
  SQLite copies. It checks authorization, evidence, retention, control ordering, committed read-back,
  idempotence and fresh policy verification; it keeps the original audit immutable.
- The preserved SystemGraph now follows actual working-copy record counts and receipt-backed ended
  control links. Before/latest/per-receipt exploration is explicitly recorded playback. No source
  relationship is called deleted merely because it disappears from a view.

- Canonical reference: `docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md`, linked from README. It records the
  actual architecture, event protocol, graph semantics, API/model boundaries, setup, ownership and limits.
- Four-step default React/TypeScript AFTERTRACE interface, archived chapters and FastAPI layer under `frontend/**` and
  `code/slam/web/**`. Identity, source, timeline, decision and folio views inspect real backend data.
- Original HTML graph preserved under `docs/reference/`; the enhanced original keeps its DiGraph,
  SVG renderer, node-link JSON, IDs, handlers, undo and scenario semantics. Identity Constellation
  retains HTML nodes/SVG edges and original anchors, adding light styling, filters, provenance,
  lifecycle states, precise focus, history and progressive expansion.
- Actual SSE execution of ingestion, attribution learning, intent, identity, ownership, timeline,
  dependency graph, full-bundle policy planning and validation. Events carry real timing, snapshots,
  source/model activity and validated outputs; there are no timer-driven fake phases.
- Existing provider factory/metering supports the configured OpenAI/Groq path. Keys stay server-side,
  calls remain opt-in and capped, and deterministic runs correctly report zero calls when applicable.
- The latest GitHub dev baseline at b4382c9 was merged, retaining newer CLI, linking, provider and report
  work. The frozen context-only planner compatibility implementation is preserved alongside the newer
  full-bundle plan_case path used by CLI/live execution. The reference explains their difference.
- Shared contract version/hash remain unchanged. Added web read-model metadata is separate.

## Cross-owner edits

- `code/slam/insight/**`, `tests/insight/**`, `dashboard/**` and console launch scripts
  (integration): merged from `origin/dev` without weakening their triage/simulation boundaries;
  the primary workflow consumes only a read-only result endpoint.
- `code/slam/pipeline.py` (integration): merged existing Lalith diagnostics/context collection while
  retaining attribution/cohort behaviour. This shared delivery note records the change for its owner.
- `code/slam/ingestion/api.py` (Ashish): opt-in source-completed telemetry, no signature or decision change.
- `code/slam/reconstruction/api.py` (Manya): opt-in checkpoints around actual operations, preserving the
  frozen interface and newer ownership/linking behaviour. Other reconstruction modules/tests are
  retained from the merged teammate baseline.
- `code/slam/planning/api.py`, `code/slam/planning/export.py`, `tests/planning/test_export.py`,
  `tests/planning/test_policy_plan.py` (Satvika): retain context-only safety/compatibility checks and
  export rejection guards. Full-bundle plan_case and newer validation stay intact. Review the two
  entry points before any consolidation.
- `code/slam/planning/__init__.py` (Satvika): re-export the existing validator, validation error and
  CSV exporter for the web adapter; no implementation or shared-contract change.
- `.gitignore` (integration): exclude frontend dependencies, builds, test artifacts and local backup
  archives from commits. Existing dataset and credential exclusions remain in place.
- `docs/integration/ownership.toml` (integration): assigns new frontend/web paths to Lalith.
- `tests/contracts/test_owned_boundaries.py`: resolved against the newer shared baseline; frozen
  ingest/reconstruct/plan signatures remain checked.
- This pushed reference is the shared announcement requested by the user. No private messages were sent.

## Requires from others

| From | Item | Status |
| --- | --- | --- |
| Ashish | Review source telemetry and exercise real participant sources | Review requested through this reference; no ordinary offline-test blocker |
| Manya | Review checkpoint placement, actual per-link lifecycle/conflict metadata and attribution UI | Current validity ends are shown honestly; explicit deletion producers remain a data requirement |
| Satvika | Review context-only/full-bundle API distinction and uncertainty/export semantics | Current engine INCOMPLETE results and uncertainty reasons remain visible |
| Integrator | Review sample failures, measure optional live provider, and run final submission checks | Fresh keyless 518-case and 32-sample runs are measured; hidden accuracy and live-provider performance remain unverified |

## Provides to others

| Item | Location / rule |
| --- | --- |
| Current implementation map | `docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md` |
| Current workflow API | `/api/workflow/input`, `/runs`, run-scoped evidence and `/sandboxes`; exact routes in `docs/AFTERTRACE_WORKFLOW.md` |
| Archived live API | `POST /api/runs/stream`, `GET /api/runtime`; retained for compatibility and regression checks |
| Graph metadata | Existing IDs and optional web metadata; do not infer deletion from absence or global conflicts |
| Model integration | Existing provider factory/metering; keys never go to browser/event payloads |
| Shared contract | 1.1.0 / unchanged hash; use the contract changelog for actual boundary changes |

## Contract and dependency requests

No shared-contract change. This increment adds the locked FastAPI web dependency and Node frontend
package lock, including self-hosted Manrope/Inter/IBM Plex Mono fonts. Docker Compose gains the local
web profile and forwards existing provider/call/token/cost settings. Use uv.lock and package-lock.json;
no Ollama, model weights or GPU dependency is introduced.

## Verification

Headline-feature dashboard increment: the complete browser regression passes all 40 tests after
an uncontended rerun; the changed workflow/connected slice passes all 9 tests. The web backend
passes 35 tests, the production TypeScript build passes, and all frontend source and browser tests
pass Prettier validation. A live 518-request local audit visibly reported 11 validated timing
models learned from 901 grounded pairs; the normal dataset correctly reported that no parser
recovery was required.

Combined-dashboard increment: the web/insight Python slice passes 66 tests with one skipped;
Ruff and strict mypy pass. The frontend production build and Prettier check pass, and the full
browser suite passes all 40 tests across the connected workflow, analytical console, graph,
live-backend, responsive and accessibility paths. Docker Compose configuration validates. The
full Python regression suite passes 722 tests with 19 skipped (one dependency deprecation
warning).

Connected increment: full Python suite 683 passed / 18 skipped; after adding further negative cases,
the final web subset passed 32 tests. Full browser suite: 37 passed, followed by six passing changed
workflow tests. Build, formatting, Ruff and mypy (75 files) passed. The browser checks exercise a
connected snapshot with two actual DELETE actions and a retained record: the complete request graph
is visible first, precisely two record nodes disappear after verification, retained/system nodes
remain, and history restores the removed nodes. Actual sync worker branches measured 0 -> 1 rows
when enabled and 0 -> 0 when disabled. Recovery passed all six gates and blocked conflicting input.
Ambiguous subject identities, access requests and malformed/duplicate recovery rows are rejected.

Earlier workflow baseline verification:

Full Python suite with participant-data tests enabled: 649 passed, 18 skipped. Final web subset:
24 passed. Frontend suite: 36 passed, including the real ZIP -> audit -> SQLite execution -> proof ->
report flow, original graph regressions, stale input protection, refresh restore, recorded replay,
non-reduced/reduced motion and 390/768/1024/1440 layouts. Final workflow subset rerun: five passed.
Production build, frontend formatting, Ruff, mypy (66 Python source files)
and whitespace checks pass.

The new workflow API audited all 518 official requests from 94 evidence files with no execution
errors and 8,328 actual events. Its original CSV is byte-identical to the earlier CLI run. Executed
case_33's two planned actions and case_54's four actions (including a flow control) in isolated
copies, obtaining COMPLETE read-back verification for those materialized scopes. Original CSV and
all 103 official input files remain unchanged. Zero API calls. The earlier 11/32 exact sample result
is not improved or concealed by these UI/execution changes.

## Known limits

No live API-provider or hidden-answer accuracy claim is made. Full-dataset predictions and
repeatability were measured; canonical correctness for the 518 hidden-answer cases is unknown.
Imported statistics/forecasts remain in the development archive; they are not shown as current
workflow measurements. Identity validity ends establish ENDED, not entity DELETED. Working-copy
record deletion and ended control links use actual SQLite read-back receipts within that scope.
The web API is local and unauthenticated, with in-memory one-run-per-process execution. No external
remediation, autonomous self-healing/promotions or durable multi-user job system is provided.

## Integration notes

- Shared baseline merged through 0bee04b from origin/dev. Current frontend/graph checkpoints are based on that
  actual backend rather than the older local stub.
- Fetch and merge latest dev into individual feature branches before independent work. No force push,
  branch deletion or private teammate notification is part of this delivery.
- Do not swap plan(context) and plan_case(context,bundle) silently or hide not_certified_because reasons.
- Preserve server-generated run CSV bytes when opening a run folio; do not recompute a model-assisted
  result through a later deterministic GET. Evidence must carry the executed case, especially in batches.
- Hotspots: runtime events/provider factory, reconstruction/api.py, planning APIs/export, App.tsx,
  Docker/locks and this reference. Other owner delivery notes remain authoritative for their work.
