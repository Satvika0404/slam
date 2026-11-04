---
owner: lalith
workstream: Contracts, runtime, evaluation, Docker
status: READY_FOR_INTEGRATION
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: 0bbee13
merge_after: none
last_updated: 2026-11-05
---

# Lalith - contracts, runtime, evaluation, Docker

<!--
Pre-filled by the integrator from git history and team_handoff/04_LALITH_RUNTIME_EVALUATION_INTEGRATION.md.
Lalith: correct anything that is wrong and keep this current in every PR from branch `lalith`.
-->

## Delivers

- Foundation baseline, authored by Lalith: commits `c0523a0`, `0e27272`, and `0bbee13`
  ("Expand ingestion contracts and image provider"). The contract 1.1.0 update is local until the
  current changes are published. `main` has not received the foundation.
- Contract models and generated schema (`code/slam/contracts.py`, `contracts/`), `ModelProvider`
  with fake and OpenAI providers (`code/slam/runtime/`), cache keys, usage metering, `Settings`,
  Docker/Compose, `uv.lock`, and `run_cases` in `runtime/orchestrator.py`.
- Evaluation primitives are now on `lalith`: output contract validator and challenge scorer
  (`code/slam/evaluation/`, re-exported under `code/evaluation/`) with focused tests under
  `tests/evaluation/`.
- Evidence-pattern diagnostics return deterministic structured findings with stable IDs and
  detection-rule versions for comparable-scope/time conflicts, interval-overlapping identity
  collisions, provenance/source-accounting gaps, post-cutoff evidence, duplicate content/facts, and
  recreation paths/cycles/unknown endpoints. Replica, system, scope, and temporal differences stay
  distinct.
- Directly affected cases/resources, explicit-graph reachability, and evidence-coverage gaps are
  reported separately with assumptions and unknowns. Diagnostics remain advisory and do not mutate
  evidence, identity, policy, or deletion status; no certification gate was added.
- Each run writes deterministic `evaluation/data_quality_report.json` and
  `evaluation/data_quality_report.md` next to the output directory and includes the report paths
  and finding count in the CLI summary. Synthetic examples live in
  `tests/evaluation/examples/data_quality_report.{json,md}`.
- Added `CaseContext.policy_rules` and `evidence_captured_at` in contract 1.1.0 to settle planner input,
  participant-visible citation IDs, and audit-time eligibility. Decisions are recorded in
  `DEPENDENCY_MATRIX.md` and `CONTRACT_CHANGELOG.md`.
- `run_cases` now ingests once, processes requests in stable case order, isolates case-level exceptions,
  and returns blocked (non-exportable) answers for failures instead of terminating the full batch.
- Output validation now supports per-case capture-time maps and audit cutoffs, rejecting citations that
  are missing or later than that case's `audit_at`.
- Still open: full-dataset output/package checks, integration of the two latest Satvika commits,
  and final end-to-end evaluation against participant-facing data.

## Cross-owner edits

- `code/slam/pipeline.py` — integration-owned run entrypoint; captures contexts and writes the
  diagnostics reports as part of every run. The integrator should review this wiring during branch
  integration.

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Ashish, Manya, Satvika | Review latest owner branches and pass owned checks | Integration protocol in `SHARED_BUILD_CONTRACT.md` | Ashish ingestion is in the dev baseline; Manya reconstruction is in the dev baseline; Satvika has `c0ad323` and `888f197` ahead of `origin/dev`, pending review/integration |
| Satvika | Integrate planning fixes after review | Latest planning branch commits are not in this diagnostics branch | OPEN; diagnostics do not depend on planner behavior |

## Provides to others

| To | What | Where | They must honour |
|---|---|---|---|
| Everyone | Contract 1.1.0 and its schema hash | `code/slam/contracts.py`, `contracts/SCHEMA_SHA256` | Changes need your approval, a `CONTRACT_CHANGELOG.md` entry and notice to all four. |
| Ashish, Manya | `ModelProvider` (structured output, image input, usage), fake provider | `code/slam/runtime/` | No tools, no write access, no authority over identity, policy or status |
| Everyone | `build_model_cache_key`, `Settings`, Docker image, locked dependencies | `runtime/cache.py`, `config.py`, `Dockerfile`, `uv.lock` | Dependency changes go through you only |
| Integrator | `run_cases` and the validators/scorers once written | `runtime/orchestrator.py`, `code/evaluation/` | The orchestrator refuses to fabricate results for unresolved cases |

## Contract and dependency requests

None open from this workstream. Open requests from others are tracked in `CONTRACT_CHANGELOG.md`
(Ashish: allow a failed `SourceRecord` for rejected manifest rows).

## Verification

- `docker compose build` — passed.
- `docker compose run --rm slam-dev pytest -q tests/evaluation` — 21 passed.
- `docker compose run --rm slam-dev pytest -q tests/contracts tests/evaluation tests/reconstruction` —
  131 passed.
- `docker compose run --rm slam-dev pytest -q` — 515 passed, 34 skipped.
- `docker compose run --rm slam-dev ruff check code tests` — passed.
- `docker compose run --rm slam-dev mypy code/slam code/main.py` — passed (51 source files).
- Synthetic planted-positive oracle: precision 1.000, recall 1.000, false positives 0. One small
  fixture run measured 2.017 ms runtime and 52,149 peak traced bytes; this is a unit-fixture
  measurement, not a throughput or real-dataset claim.
- `python scripts/delivery_check.py ci --base origin/dev --branch lalith` — passed with 0 errors and 0 warnings.

## Known limits

The scorer requires a reference CSV and does not imply hidden-answer access. Conflict detection uses
exact effective-time equality and the scope fields present in observations; unknown time/scope
semantics can be missed. Historical identity intervals are inferred from change timestamps and the
current snapshot's `updated_at`; ambiguous bounds remain a limitation. Reachability includes only
explicit active graph edges, and case attribution requires supplied contexts. Findings and coverage
are diagnostic, not probabilities. Synthetic metrics are small-fixture results; no real-dataset
performance claim is made. Real-API behaviour has never been measured.

## Integration notes

- This working tree is one commit ahead of `origin/dev` and 14 commits ahead of `origin/lalith`;
  the diagnostics commit is not yet pushed because GitHub authentication is unavailable in this
  checkout.
- Integrate the Manya branch only after they merge this shared contract and update their delivery hash.
- `main` has no `contracts/`; decide when `dev` is promoted to `main`.
- Hotspot files you own that others will edit: `tests/contracts/test_owned_boundaries.py`,
  `pyproject.toml`, `uv.lock`, `README.md`, `code/main.py`.
- `origin/satvika` contains two commits not yet in `origin/dev`; these diagnostics were developed
  against latest `origin/dev` and do not depend on planner code. Re-run full offline checks after
  ordered integration of the remaining owner branches.
