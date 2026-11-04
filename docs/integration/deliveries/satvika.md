---
owner: satvika
workstream: Policy, decision, ordered steps, CSV export
status: IN_PROGRESS
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: 0d02a57be96b70f055e69e7c0d16adb652b7b882
merge_after: ashish, manya
last_updated: 2026-11-04
---

# Satvika - policy, decision, steps, export

## Delivers

- `validate_answer(answer, *, eligible_evidence_ids=None) -> CaseAnswer` in `code/slam/planning/validation.py` checks contract invariants, evidence on findings and complete-case verifications, future-action citation rules, and optional evidence eligibility. It makes no policy decision.
- Synthetic validator coverage in `tests/planning/test_validation.py` for valid incomplete/complete/non-applicable answers, invalid operation/state pairs, step numbering and phase order, evidence rules, ineligible evidence, and extra fields.
- `plan(context) -> CaseAnswer`, deterministic policy decisions, ordered remediation/verification steps, and `export_output_csv` are present on the current `dev` baseline.
- Unknown, conflicting, uncertain, or uncovered resource state now blocks certification instead of returning an export-ready answer. Empty resource state also blocks certification.

## Cross-owner edits

None.

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Lalith / integrator | Start from `dev` and adopt contract 1.1.0 | Current shared context carries policy rules and timestamped participant-visible citations | MET: `satvika` includes `origin/dev` through `bf40c39` |
| Lalith / integrator | Confirm exporter signature and call site | Needed for shared run wiring | MET in contract 1.1.0 and pipeline |
| Manya | `CaseContext` | Your only input | Not started; build against fixtures of the contract type |
| Ashish | `PolicyRule` rows (15 in the supplied dataset): `rule_id`, `category`, `required_action`, `condition`, `attributes`; ingestion's `observed_state` vocabulary | Planning, not ingestion, maps free-string states to the closed output states (`CONTRACT_DECISIONS.md`) | Merged in `dev` @ `2666ffe`; vocabulary in `INGESTION_PLAN.md` section 3 |
| Ashish | You review ingestion | Cross-review assignment in `SHARED_BUILD_CONTRACT.md` | PARTLY: your comment-only review of PR #3 said "good"; record any findings against `INGESTION_PLAN.md` sections 3 and 5 here |

## Provides to others

| To | What | Where | They must honour |
|---|---|---|---|
| Lalith / orchestrator | `plan(context) -> CaseAnswer`, `validate_answer`, `export_output_csv` | `code/slam/planning/**` | Unknown or conflicted context must remain blocked; exporter rejects answers not ready for export. |

## Contract and dependency requests

None for this slice. Q1 may require a contract change; no contract was edited.

## Verification

Run in Docker on 2026-11-05:

- `docker compose run --rm slam-dev pytest -q tests/contracts tests/planning` — 38 passed.
- `docker compose run --rm slam-dev ruff check code/slam/planning tests/planning` — passed.
- `docker compose run --rm slam-dev mypy code/slam/planning` — passed.
- `docker compose run --rm slam-dev pytest -q tests/contracts tests/planning` — 46 passed after cutoff/certification changes.
- `docker compose run --rm slam-dev ruff check code/slam/planning tests/planning` — passed.
- `docker compose run --rm slam-dev mypy code/slam/planning` — passed.

## Known limits

- The participant dataset, including `deletion_rules.csv`, is absent from this checkout; no real-dataset accuracy claim is made.
- Evidence eligibility in the planning validator is checked when callers provide the eligible citation set; the planner derives eligible citation timestamps from contract 1.1.0 context.

## Integration notes

- Work is on `satvika`, based on current `origin/dev` at `bf40c39`; merge order remains Ashish, Manya, then Satvika.
- No tests outside contract and planning validator suites were run for this slice.
