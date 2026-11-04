---
owner: integration
workstream: Integration, seam tests, CI, packaging
status: READY_FOR_INTEGRATION
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: a722cbcca0ee39919effde4bbaa46de460ad4223
merge_after: none
last_updated: 2026-11-05
---

# Integration - mechanism, CI, merge record

<!-- Used by branches named integration/<topic>. The record at the bottom is append-only. -->

## Delivers

**This PR (on top of PR #7, already in `dev`):** the submission package and the records that were still open after PR #7. Nothing in the pipeline's behaviour changes; `output.csv` is byte-identical before and after.
- Reports where the submission rules require them: `code/evaluation/main.py` (`write_reports`; also runnable on its own as `python code/evaluation/main.py --dataset dataset`) writes `evaluation_report.md` and `usage_report.md` to `code/evaluation/` and mirrors both to `evaluation/`. `code/main.py --evaluate` now delegates to it; the duplicate inline writer is removed.
- `scripts/build_submission.py` requires the `code/evaluation/` reports to be inside `code.zip` (self-check fails otherwise); the diagram-conformance test reads the writer's new location.
- `README.md` steps 3 and 4: where the reports land, and how to build and self-check `code.zip`.
- `docs/INTERVIEW_PREP.md`: notes for the AI interview (pitch, architecture table, honest answers to hard questions).
- This note: merge-record rows for PR #4, #5 and #7; Manya's note flipped to `INTEGRATED` (her branch tip `152b0a2` is an ancestor of `dev`). Satvika's and Lalith's notes stay `IN_PROGRESS` on purpose: their newer commits are not in `dev`.

**PR #7 (already in `dev`):** quality pass measured against HackerRank's own 32 published answers.
- Ingestion: bulleted table rows are parsed as rows (explicit `NOT_FOUND`/`SUPPORT_ATTACHMENT` columns were ignored); `uploaded_by` is an owner identifier.
- Reconstruction: dynamic account/resource-to-person linking (`ownership.py`, `linking.py`, `absence.py`; windows and a status/result agreement are learned and held-out validated, nothing dataset-specific); retained records seen before the cutoff in later-exported files become uncited verification-only states; `reconstruct_with_links` added, frozen `reconstruct` unchanged.
- Planner: steps ordered exactly as the problem statement specifies.
- `scripts/build_submission.py` (code.zip + self-check), `scripts/smoke_test.py`, a diagram-conformance test, `docs/integration/RCA_ACCURACY.md`.

Branch `integration/reconstruction`: Manya's reconstruction merged intact (`152b0a2`, her `log.txt` left out), Lalith's evaluation scorer/validator/data-quality (`e3d16b4`) and Satvika's answer validator (`d70892e`) merged unchanged, plus:
- fixes to Manya's code found by running it on the real corpus: intent recall 20/32 -> 32/32 samples (0/518 unclear, 10 non-deletion = exactly the 10 CLASSIFY_REQUEST claims); activity edges no longer invert mitigations (116 flow + 58 restore edges) and 303 plain records no longer read as flows; info-level ingestion notes no longer block certification; identity as of `audit_at`; names no longer attach evidence; injection guard accepts plurals.
- `plan_case(context, bundle)` (policy + ordered steps), `export_output_csv`, `slam.pipeline.run/evaluate_samples`, `code/main.py --dataset dataset [--evaluate]`.
- **Account/resource linking (dynamic, no dataset-specific constants)**: `ownership.py` (L1 explicit owner index + L2 closure), `linking.py` (L3: timing signatures learned per (activity type, target system) from labelled pairs and enabled only after held-out validation with zero wrong), `absence.py` (ABSENT proven by the latest complete snapshot lacking the record); `reconstruct_with_links(request, bundle, link_model)` added, frozen `reconstruct` unchanged; ingestion maps `uploaded_by`. Plan: `docs/integration/ACCOUNT_LINKING_PLAN.md`.
- Contract 1.1.0 adoption (Lalith `fa6076a`): reconstruction fills `policy_rules` and `evidence_captured_at`; `plan(context)` works from the context alone.
- `scripts/smoke_test.py` and `docs/integration/RCA_ACCURACY.md` (root causes of the step-level gap).
- Tests: `tests/reconstruction/test_integration_fixes.py`, `tests/planning/test_engine.py`, `tests/integration/test_pipeline_seam.py`; reports in `evaluation/`.

## Cross-owner edits

Each file below is another owner's or unowned; the owner must confirm.

- `README.md` - Lalith: run steps now name `code/evaluation/` as the report location and add the `code.zip` build step; Lalith to confirm
- `code/main.py` - Lalith: `--evaluate` delegates to `evaluation.main.write_reports` and the docstring names the new report path; Lalith to confirm (his open PR #6 changes the same docstring lines and the printed summary: one trivial hunk, the report path in the docstring)
- `code/evaluation/main.py` - Lalith (`code/evaluation/**`): new report writer; Lalith to confirm
- `code/evaluation/evaluation_report.md` - Lalith: generated report, rewritten by every `--evaluate` run; Lalith to confirm
- `code/evaluation/usage_report.md` - Lalith: generated report, rewritten by every `--evaluate` run; Lalith to confirm
- `docs/integration/deliveries/manya.md` - Manya: only `status` (READY_FOR_INTEGRATION to INTEGRATED, her tip `152b0a2` is in `dev`) and `last_updated`; Manya to confirm
- `evaluation/evaluation_report.md` - unowned: mirror of the generated report
- `evaluation/usage_report.md` - unowned: mirror of the generated report
- `scripts/build_submission.py` - unowned tool: the self-check now requires the `code/evaluation/` reports

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Ashish, Manya, Satvika, Lalith | A current delivery note in every PR from their branch | The gate fails otherwise, and the preflight reads `merge_after`, `built_on` and `Integration notes` from it | Ashish done; others pre-filled |
| Lalith | Approve this mechanism and the two contract-related decisions in `DEPENDENCY_MATRIX.md` | `contracts.py` and `SHARED_BUILD_CONTRACT.md` are his | OPEN |
| Lalith | Confirm the edits to `README.md`, `code/main.py` and `code/evaluation/**`; when merging PR #6 expect one trivial hunk in `code/main.py` (docstring) and 3 real hunks in `code/slam/pipeline.py`: his `answer_cases` calls `reconstruct`, `dev` calls `reconstruct_with_links`. Keep the `link_model` path and add his `contexts` hook, otherwise the learned account linking is silently dropped and the step score falls | He owns those paths; PR #6 also changes them. Trial-merged onto this branch, 2026-11-05 | OPEN |
| Satvika | Reconcile `origin/satvika` (`d1022dc`) with `plan_case` in `code/slam/planning/engine.py`: a trial merge conflicts in `engine.py` (3 hunks) and `tests/planning/test_engine.py` (9 hunks). Her version also blocks certification on uncertain or ineligible-evidence resources, so the COMPLETE count can change | The planner in `dev` is the integrator's stand-in; a merge must be re-measured against the 32 public answers first | OPEN |

## Provides to others

| To | What | Where | They must honour |
|---|---|---|---|
| Everyone | Rules for what a PR must contain | `docs/integration/README.md`, `.github/PULL_REQUEST_TEMPLATE.md` | Update your own note in every PR; declare cross-owner edits |
| Everyone | A local way to run the same gate before pushing | `python scripts/delivery_check.py ci --base origin/dev --head HEAD --branch <you>` | Run it before opening the PR |
| Everyone | A merge order, conflict table and Q1-Q4 decisions | `INTEGRATOR_PLAYBOOK.md`, `DEPENDENCY_MATRIX.md` | Merges happen only through the integrator |

## Contract and dependency requests

None. The checker is standard-library only.

## Verification

Docker (`docker compose run --rm -T slam-dev ...`), 2026-11-05, on this branch: `ruff check code tests scripts` clean; `mypy code/slam code/main.py` no issues in 54 files; `pytest -q` **556 passed, 18 skipped** (git-dependent, no git in image; 4 of the passes are the new `tests/integration/test_report_writer.py`). `python code/main.py --dataset dataset --evaluate`: 518 rows, 0 failures (INCOMPLETE 355, COMPLETE 153, NOT_APPLICABLE 10), accepted by `validate_output_csv`. `python code/evaluation/main.py --dataset dataset` writes both reports on its own (checked: without its `sys.path` bootstrap it fails with `No module named 'slam'`). `python scripts/build_submission.py`: 138 files, self-check OK (no dataset, no archives, no `.env`). `output.csv` has sha256 `55fabff2a919456c9d33604837338165df0f03b4721ff3ab6a7f0a50bb3edb81`, identical to what unmodified `dev` (`a722cbc`) produces, so this PR changes no answer.

Against HackerRank's own `sample_output.csv` (32 cases, official clone): status accuracy 0.906 (29/32), **false COMPLETE 0**, step precision 0.744, recall 0.663, **F1 0.701**, exact cases 11/32, field accuracy 0.771; 161 of 193 expected steps reproduced, evidence id correct on every matched step. HackerRank publishes no answers for the 518, so those cannot be scored.

## Known limits

- 7 hand-made teaching cases (`account_001`..`010`) use a different timing regime with too few labelled pairs to validate; 7 further cases stay ambiguous (request order, case number and activity-id order were tested as tiebreakers and are at chance).
- Support records: HackerRank's DELETE-vs-REDACT choice for 2 cases has no safe general rule; `support_replica` is not aliased to `support_platform`.
- The linker's validated groups were learned on the 518; the 32 public samples are only a proxy and some of their timing patterns differ.
- `usage_report.md` states 0 model calls (true, the pipeline is deterministic); no real API run has been measured.
- See `docs/integration/RCA_ACCURACY.md` for the evidence behind every item.

## Integration notes

Merge record (append-only; newest last). One row per unit merged into `dev` or `main`.

| Date | Unit | Merged commit | Gates run | Result | Notes |
|---|---|---|---|---|---|
| 2026-11-04 | Ashish ingestion, PR #3, with foundation baseline B1 (`0bbee13`) | `2666ffe` | none recorded: merged before this mechanism, `dev` had no workflows; owner's own Docker run is in `ashish.md` | merged by Lalith; Satvika commented "good", Lalith approved | Retroactive entry. 98 files: 47 ingestion plus the baseline. No delivery note existed; `ashish.md` was written afterwards |
| 2026-11-04 | Integration mechanism, PR #4 (`integration/mechanism`, head `9a59d3d`) | `0d02a57` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 16:57Z; he approved; Satvika's review request was left pending | Retroactive entry. First push failed the Docker platform job because the image has no git; fixed by skipping the 18 git-dependent tests there (they run in the host gates) |
| 2026-11-04 | Reconstruction, evaluation scorer and validator, planner and pipeline, PR #5 (`integration/reconstruction`, head `7f284f1`) | `bf40c39` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by Satvika0404 at 21:13Z; approved by Satvika0404 | Retroactive entry. Manya's `152b0a2` merged intact; Lalith's scorer and Satvika's validator merged unchanged; `plan_case` is the integrator's stand-in because `plan()` was still a stub |
| 2026-11-04 | Output-quality pass, PR #7 (`integration/account-linking`, head `58ed664`) | `a722cbc` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 23:17Z; approved by dglalithchandra | Retroactive entry. Parser fix, learned account linking, retained-record checks, `scripts/build_submission.py`. Measured on the 32 public answers: status 29/32, false COMPLETE 0, step F1 0.701 |
