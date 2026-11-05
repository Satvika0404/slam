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
- This is the first planning slice; policy loading, treatment decisions, plan generation, and CSV export are not implemented yet.

## Cross-owner edits

None.

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Lalith / integrator | Start from `dev` and adopt contract 1.1.0 | The current shared contract includes policy rules and timestamped participant-visible citations in `CaseContext` | Required before implementation/integration; use the current `contracts/SCHEMA_SHA256` |
| Lalith / integrator | Contract 1.1.0 interface and exporter signature | `CaseContext.policy_rules`, `evidence_captured_at`, visible citation IDs, and `export_output_csv(answers, required_case_ids, path) -> None` are now specified | Implement against current contract; reject evidence citations missing from the map or later than `request.audit_at` |
| Manya | `CaseContext` | Your only input | Not started; build against fixtures of the contract type |
| Ashish | `PolicyRule` rows (15 in the supplied dataset): `rule_id`, `category`, `required_action`, `condition`, `attributes`; ingestion's `observed_state` vocabulary | Planning, not ingestion, maps free-string states to the closed output states (`CONTRACT_DECISIONS.md`) | Merged in `dev` @ `2666ffe`; vocabulary in `INGESTION_PLAN.md` section 3 |
| Ashish | You review ingestion | Cross-review assignment in `SHARED_BUILD_CONTRACT.md` | PARTLY: your comment-only review of PR #3 said "good"; record any findings against `INGESTION_PLAN.md` sections 3 and 5 here |

## Provides to others

| To | What | Where | They must honour |
|---|---|---|---|
| Lalith / orchestrator | `validate_answer` | `code/slam/planning/validation.py` | This validates a single answer; it does not decide status or replace `CaseAnswer` contract validation. Pass eligible evidence IDs when known. |

## Contract and dependency requests

None for this slice. Q1 may require a contract change; no contract was edited.

## Verification

Run in Docker on 2026-11-04:

- `docker compose run --rm slam-dev pytest -q tests/contracts tests/planning` — 38 passed.
- `docker compose run --rm slam-dev ruff check code/slam/planning tests/planning` — passed.
- `docker compose run --rm slam-dev mypy code/slam/planning` — passed.

## Known limits

- This validator does not implement the Judge–Evidence–Verify policy engine or export.
- Evidence eligibility is checked only when the caller supplies `eligible_evidence_ids`; resolution of the citation/eligibility contract remains open.
- `deletion_rules.csv` is absent from this checkout. Production policy behavior must wait for the participant rule data and Q1 resolution.

## Integration notes

- Work is on `satvika`, based on `origin/dev` at `0d02a57`; it must not be merged until Ashish and Manya are integrated, per `merge_after`.
- No tests outside contract and planning validator suites were run for this slice.
