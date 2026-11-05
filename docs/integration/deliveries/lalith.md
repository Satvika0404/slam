---
owner: lalith
workstream: Contracts, runtime, evaluation, Docker
status: READY_FOR_INTEGRATION
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: b4382c9
merge_after: none
last_updated: 2026-11-05
---

# Lalith — AFTERTRACE, runtime and integration delivery

## Delivers

- Canonical reference: `docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md`, linked from README. It records the
  actual architecture, event protocol, graph semantics, API/model boundaries, setup, ownership and limits.
- Ten-chapter React/TypeScript AFTERTRACE interface and FastAPI read layer under `frontend/**` and
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
| Integrator | Run fresh participant-dataset evaluation, live model measurement and submission checks | Not established here because dataset is absent; earlier reports are not new UI-run measurements |

## Provides to others

| Item | Location / rule |
| --- | --- |
| Current implementation map | `docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md` |
| Live API | `POST /api/runs/stream`, `GET /api/runtime`; inspect read models, do not manufacture phase events |
| Graph metadata | Existing IDs and optional web metadata; do not infer deletion from absence or global conflicts |
| Model integration | Existing provider factory/metering; keys never go to browser/event payloads |
| Shared contract | 1.1.0 / unchanged hash; use the contract changelog for actual boundary changes |

## Contract and dependency requests

No shared-contract change. This increment adds the locked FastAPI web dependency and Node frontend
package lock, including self-hosted Manrope/Inter/IBM Plex Mono fonts. Docker Compose gains the local
web profile and forwards existing provider/call/token/cost settings. Use uv.lock and package-lock.json;
no Ollama, model weights or GPU dependency is introduced.

## Verification

Merged full Python suite: 625 passed, 34 skipped. Final changed web subset: 16 passed.
Frontend suite: 31 passed (six pure algorithm/export/stream checks and 25 browser flows).
Production build, frontend formatting, Ruff, mypy (64 Python source files) and git diff --check passed.
Browser coverage includes original graph handlers, status/history fixtures, selection, source proof,
large graphs, mobile/laptop layout, real streaming execution, batch evidence and validated CSV exports.
Screenshots are ignored under artifacts/aftertrace. Non-failing upstream Starlette/Lucide notices remain.

## Known limits

No fresh full 518-case dataset run or live API-provider test is claimed. Dataset accuracy, latency and
cost require measured participant-data runs. Imported console statistics/forecasts remain supplied
analysis; original evidence/build scripts were not attached. Validity ends establish ENDED, not entity
or relationship DELETED. Explicit deletion producers and per-link conflicts require actual evidence.
The web API is local and unauthenticated, with in-memory one-run-per-process execution. No external
remediation, autonomous self-healing/promotions or durable multi-user job system is provided.

## Integration notes

- Shared baseline merged: b4382c9 from origin/dev. Current frontend/graph checkpoints are based on that
  actual backend rather than the older local stub.
- Fetch and merge latest dev into individual feature branches before independent work. No force push,
  branch deletion or private teammate notification is part of this delivery.
- Do not swap plan(context) and plan_case(context,bundle) silently or hide not_certified_because reasons.
- Preserve server-generated run CSV bytes when opening a run folio; do not recompute a model-assisted
  result through a later deterministic GET. Evidence must carry the executed case, especially in batches.
- Hotspots: runtime events/provider factory, reconstruction/api.py, planning APIs/export, App.tsx,
  Docker/locks and this reference. Other owner delivery notes remain authoritative for their work.
