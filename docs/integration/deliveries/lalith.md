---
owner: lalith
workstream: Contracts, runtime, evaluation, Docker
status: IN_PROGRESS
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: 0bbee13
merge_after: none
last_updated: 2026-11-04
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
- Data-quality diagnostics and evidence coverage estimates are implemented in
  `code/slam/evaluation/data_quality.py`. Coverage values are explicit checklist fractions, not
  probabilities of answer correctness. Diagnostics do not mutate decisions.
- Added `CaseContext.policy_rules` and `evidence_captured_at` in contract 1.1.0 to settle planner input,
  participant-visible citation IDs, and audit-time eligibility. Decisions are recorded in
  `DEPENDENCY_MATRIX.md` and `CONTRACT_CHANGELOG.md`.
- `run_cases` now ingests once, processes requests in stable case order, isolates case-level exceptions,
  and returns blocked (non-exportable) answers for failures instead of terminating the full batch.
- Output validation now supports per-case capture-time maps and audit cutoffs, rejecting citations that
  are missing or later than that case's `audit_at`.
- The deterministic planning subsystem and strict CSV exporter are now implemented under
  `code/slam/planning/`: rule selection, conservative uncertainty handling, findings, ordered
  remediation, verification, answer validation, and required-case-set export.
- Planning tests cover non-deletion, delete/redact/retain decisions, eligible evidence, ambiguous rules,
  active-flow and restore ordering, downstream-copy ordering, and exporter row-set/format safeguards.
- Still open: full `main.py --dataset` wiring, run-level usage/evaluation reports, packaging checks,
  Manya's population of the 1.1.0 context fields, integration review, and final end-to-end evaluation
  against participant data. Conditional policy rules without an upstream `applicable_rule_id` block
  certification because `ResourceState` does not carry the source attributes needed to evaluate them.

## Cross-owner edits

- `code/slam/planning/__init__.py`, `code/slam/planning/api.py`, `code/slam/planning/export.py`,
  `code/slam/planning/validation.py`, `tests/planning/test_export.py`, and
  `tests/planning/test_policy_plan.py` are Satvika-owned. Lalith implemented the deterministic policy
  planner, validation and CSV export at the user's request because those pieces were still blocking the
  assembled product. Satvika should review/adopt this work before integration.

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Ashish, Manya, Satvika | Rebase to contract 1.1.0 and pass owned checks | Integration protocol in `SHARED_BUILD_CONTRACT.md` | Ashish implementation available on `origin/ashish`; Manya implementation on `origin/manya` (`152b0a2`) pending 1.1.0 update/integration; Satvika implementation not present on `origin/satvika` (`346e811`) |
| Manya, Satvika | Fixtures under `tests/fixtures/<area>/` | The evaluation harness needs independent expected results | OPEN |
| Satvika / Lalith | Review and adopt planner/export implementation now present on `lalith` | `code/slam/planning/` | OPEN; original Satvika branch still contains only its validator slice |
| Manya, Satvika | Contract 1.1.0 adoption and updated delivery notes | The shared hash changed for planning/reconstruction inputs | OPEN; notify and integrate after their branches update |

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

Docker checks for this increment: `pytest -q tests/evaluation` (12 passed),
`ruff check code tests scripts` (passed), and `mypy code/slam code/main.py` (43 source files passed).
The full repository test suite must still be run after teammate integration.

## Known limits

The scorer requires a reference CSV and does not imply hidden-answer access. Data-quality patterns
are diagnostics for exact-time/resource contradictions and identifier collisions; they do not
resolve those conflicts. Case coverage is a transparent heuristic checklist, not calibrated
confidence. Real-API behaviour has never been measured.

## Integration notes

- This working tree is two commits ahead of `origin/dev`; its 1.1.0 contract is local until a PR merges.
- Integrate the Manya branch only after they merge this shared contract and update their delivery hash.
- `main` has no `contracts/`; decide when `dev` is promoted to `main`.
- Hotspot files you own that others will edit: `tests/contracts/test_owned_boundaries.py`,
  `pyproject.toml`, `uv.lock`, `README.md`, `code/main.py`.
