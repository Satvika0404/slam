---
owner: integration
workstream: Integration, seam tests, CI, packaging
status: READY_FOR_INTEGRATION
contract_version: 1.1.0
contract_sha256: 95cfa189ae07490fe5b42527dc08990b50779d83fa7a82965caefeeb28275a23
built_on: b4382c964382614776b835243102814f6a92bf1a
merge_after: none
last_updated: 2026-11-05
---

# Integration - mechanism, CI, merge record

<!-- Used by branches named integration/<topic>. The record at the bottom is append-only. -->

## Delivers

**This PR (on top of PR #10, already in `dev`):** makes the `dev` to `main` promotion check pass. PR #11 (`dev` to `main`) fails `Delivery note` with *6 file(s) outside your ownership are not declared (belonging to: nobody)*: `.gitignore`, `code/slam/__init__.py`, `code/slam/pipeline.py`, `evaluation/side_by_side_samples.md`, `scripts/build_submission.py` and `scripts/smoke_test.py`. The integrator added them in PR #5, #7 and #8 and they were never put in `ownership.toml`. This PR assigns exactly those six paths to the `integration` owner and records PR #10 in the merge record. No code, test, contract or dependency changes; `output.csv` is unaffected.

**PR #10 (already in `dev`):** an optional, measured model path with ordered API-key failover. The decision path is untouched: `output.csv` is byte-identical with and without it, and a normal run still makes 0 model calls.
- `code/slam/runtime/key_pool.py` (`KeyPool`): ordered failover. The first usable key is kept until it is rejected (401/403: retired) or runs out (429: a short `retry-after` cools it down and it returns, a long one retires it); timeouts and 5xx retry, then move on; only `key#N` labels are ever shown, never a value.
- `code/slam/runtime/groq_provider.py` (`GroqModelProvider`): Groq through the existing `openai` SDK (no new dependency), JSON mode validated against the pydantic model, per-key usage, and `check_keys()` which spends no tokens. 400/404/413/422 and malformed or truncated output are raised, not failed over, because they would fail on every key.
- `code/slam/runtime/metering.py` (`ModelPrice`, `MeteredProvider`) and `code/slam/runtime/factory.py` (`build_provider`): every call recorded; the call ceiling is exact and counts logical calls (one per `generate()`, failed ones included; the HTTP attempts a call makes while failing over are shown per key); token and priced-budget ceilings; `fatal` is set once no call can succeed. A real provider is never built without a call ceiling.
- `code/slam/config.py`: `groq` provider, `GROQ_API_KEYS`, ceilings and prices. Invalid configuration refuses to start; `hide_input_in_errors` stops a validation error from printing a key (this also covers `OPENAI_API_KEY`); the base URL must be https, with plain http only for a parsed loopback host.
- `code/evaluation/model_check.py` with `python code/main.py --check-keys` and `--dataset dataset --model-check [--model-check-requests N]`: calls the production intent and screenshot fallbacks on purpose, compares them with the rules and OCR, and writes real call counts, tokens, per-key use and an honest cost line into the two reports. `ask_provider_for_intent` is extracted from `interpret_request` (behaviour unchanged) so the check runs the exact production prompt.
- Tests: `tests/runtime/` (key pool; Groq failover with fake clients; a loopback HTTP server through the real SDK; ceilings; configuration), `tests/evaluation/test_model_check.py`, one more case in `tests/integration/test_report_writer.py`. Two deliberate breakages (cooling keys treated as usable; call ceiling off by one) were each caught.

**PR #8 (already in `dev`):** the submission package and the records that were still open after PR #7. Nothing in the pipeline's behaviour changed; `output.csv` was byte-identical before and after.
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

None. `docs/integration/ownership.toml` and this note are the integrator's own paths.

Earlier PR, kept for the record:

Each file below is another owner's or unowned; the owner must confirm.

- `README.md` - Lalith: new "Optional: measure a real model" section; Lalith to confirm
- `.env.example` - Lalith: commented Groq settings only (the defaults stay offline); Lalith to confirm
- `code/main.py` - Lalith: `--check-keys`, `--model-check`, `--model-check-requests`; the default path is unchanged; Lalith to confirm (his open PR #6 changes this file's docstring and printed summary: expect a trivial conflict)
- `code/slam/config.py` - Lalith: `groq` provider, key list, ceilings, prices, `hide_input_in_errors`, base-URL check; `fake` and `openai` behaviour unchanged; Lalith to confirm
- `code/slam/runtime/metering.py` - Lalith: `UsageLedger` untouched, `ModelPrice` and `MeteredProvider` added; Lalith to confirm
- `code/slam/runtime/key_pool.py` - Lalith: new module; Lalith to confirm
- `code/slam/runtime/groq_provider.py` - Lalith: new module; Lalith to confirm
- `code/slam/runtime/factory.py` - Lalith: new module; Lalith to confirm
- `code/evaluation/main.py` - Lalith: `write_reports(..., model_check=)`; Lalith to confirm
- `code/evaluation/model_check.py` - Lalith: new module; Lalith to confirm
- `code/evaluation/evaluation_report.md` - Lalith: generated report, rewritten by every `--evaluate` run; Lalith to confirm
- `code/evaluation/usage_report.md` - Lalith: generated report, rewritten by every `--evaluate` run; Lalith to confirm
- `code/slam/reconstruction/request_intent.py` - Manya: `ask_provider_for_intent` extracted from `interpret_request`, no behaviour change; Manya to confirm
- `tests/runtime/test_key_pool.py` - Lalith: new tests; Lalith to confirm
- `tests/runtime/test_groq_provider.py` - Lalith: new tests; Lalith to confirm
- `tests/runtime/test_groq_http_failover.py` - Lalith: new tests (loopback server only); Lalith to confirm
- `tests/runtime/test_metering_and_config.py` - Lalith: new tests; Lalith to confirm
- `tests/evaluation/test_model_check.py` - Lalith: new tests; Lalith to confirm
- `evaluation/evaluation_report.md` - unowned: mirror of the generated report
- `evaluation/usage_report.md` - unowned: mirror of the generated report

## Requires from others

| From | What | Why | Status |
|---|---|---|---|
| Ashish, Manya, Satvika, Lalith | A current delivery note in every PR from their branch | The gate fails otherwise, and the preflight reads `merge_after`, `built_on` and `Integration notes` from it | Ashish done; others pre-filled |
| Lalith | Approve this mechanism and the two contract-related decisions in `DEPENDENCY_MATRIX.md` | `contracts.py` and `SHARED_BUILD_CONTRACT.md` are his | OPEN |
| Lalith | Confirm the edits listed above to `README.md`, `.env.example`, `code/main.py`, `code/slam/config.py`, `code/slam/runtime/**`, `code/evaluation/**` and the new tests. When merging PR #6 expect one trivial hunk in `code/main.py` (docstring) and 3 real hunks in `code/slam/pipeline.py`: his `answer_cases` calls `reconstruct`, `dev` calls `reconstruct_with_links`. Keep the `link_model` path and add his `contexts` hook, otherwise the learned account linking is silently dropped and the step score falls | He owns those paths; PR #6 also changes them. Trial-merged onto this branch, 2026-11-05 | OPEN |
| Manya | Confirm the pure extraction `ask_provider_for_intent` in `request_intent.py` | It lets the cross-check run the exact production prompt; `interpret_request` behaves as before | OPEN |
| Whoever holds the Groq keys | Keys and ceilings in an uncommitted `.env`; provider and model passed with `-e` (Compose copies them into every container); run `--check-keys`, then `--dataset dataset --model-check` | Without a run both reports state that no real model run was measured | MET 2026-11-05: run once with four keys, reports regenerated |
| Satvika | Reconcile `origin/satvika` (`d1022dc`) with `plan_case` in `code/slam/planning/engine.py`: a trial merge conflicts in `engine.py` (3 hunks) and `tests/planning/test_engine.py` (9 hunks). Her version also blocks certification on uncertain or ineligible-evidence resources, so the COMPLETE count can change | The planner in `dev` is the integrator's stand-in; a merge must be re-measured against the 32 public answers first | OPEN |

## Provides to others

| To | What | Where | They must honour |
|---|---|---|---|
| Everyone | Rules for what a PR must contain | `docs/integration/README.md`, `.github/PULL_REQUEST_TEMPLATE.md` | Update your own note in every PR; declare cross-owner edits |
| Everyone | A local way to run the same gate before pushing | `python scripts/delivery_check.py ci --base origin/dev --head HEAD --branch <you>` | Run it before opening the PR |
| Everyone | A merge order, conflict table and Q1-Q4 decisions | `INTEGRATOR_PLAYBOOK.md`, `DEPENDENCY_MATRIX.md` | Merges happen only through the integrator |

## Contract and dependency requests

None. No new dependency: Groq is reached through the `openai` package already in `uv.lock`, and `pyproject.toml`, `uv.lock`, `Dockerfile` and `docker-compose.yml` are untouched. Compose passes `SLAM_*` values through from `.env` by interpolation and `Settings` reads `.env` itself for the rest, so no compose change is needed.

## Verification

This PR, 2026-11-05. The failure was reproduced with the exact command CI runs for PR #11, on `dev` (`b4382c9`): `python scripts/delivery_check.py ci --base origin/main --head HEAD --branch dev` printed the six-file error (1 error). With this change applied to `dev` the same command prints 0 errors, 0 warnings. `python scripts/delivery_check.py ci --base origin/dev --head HEAD --branch integration/ownership-map`: 0 errors, 0 warnings. `ownership.toml` parses (12 integrator paths). `tests/integration` on the Windows host, where git runs: 63 passed, 1 failed (`test_public_samples_never_produce_a_false_complete`, status 0.6875 against a 0.85 floor) because the host has no Tesseract and cannot read the 11 screenshots; the same test passes in Docker (`test_pipeline_seam.py` and `test_delivery_check.py`: 27 passed, 18 skipped for lack of git) and in CI, which installs Tesseract. This is an environment limit, not a regression: the PR changes no code.

Earlier verification, still true for the code in `dev` (this PR changes no code):

Docker (`docker compose run --rm -T slam-dev ...`), 2026-11-05, on this branch: `ruff check code tests scripts` clean; `ruff format --check` clean on every new or rewritten file; `mypy code/slam code/main.py code/evaluation/main.py code/evaluation/model_check.py` no issues in 59 files; `pytest -q` **610 passed, 18 skipped** (git-dependent, no git in image; 54 of the passes are new). `python code/main.py --dataset dataset --evaluate`: 518 rows, 0 failures, `output.csv` sha256 `55fabff2a919456c9d33604837338165df0f03b4721ff3ab6a7f0a50bb3edb81`, identical to what `dev` produced before this change, so no answer changed. `python scripts/build_submission.py`: 147 files, self-check OK. Two deliberate breakages (cooling keys treated as usable; call ceiling off by one) were each caught by the tests.

End to end through the real `openai` SDK and HTTP, against a throwaway local server that rejected key 1, daily-limited key 2, ran key 3 dry after 25 calls and left key 4 working: `--check-keys` printed key#1 rejected and the model found on the rest; `--dataset dataset --model-check --model-check-requests 20` made 31 calls (11 screenshots, 20 requests), 0 failed, and the usage report showed key#3 serving 25 calls and key#4 the remaining 6. Those were mock figures and were not committed.

Real run, 2026-11-05, Groq, model `qwen/qwen3.8-27b`, four keys in an uncommitted `.env` (values never printed, logged or committed; a scan of the repo, the log, scratch files and `code.zip` found them only in `.env`). `--check-keys`: all four keys ok and the model found. A two-call smoke test, then `--dataset dataset --model-check` with the default 60 requests: **76 calls** (11 screenshots, 60 requests, 5 more than the 71 planned, the image parser's schema-repair retries), **0 failed**, **54,329 tokens** (48,477 in, 5,852 out), unpriced so no dollar figure is claimed. Groq rate-limited 43 HTTP attempts (key#1 13, key#2 8, key#3 10, key#4 12); each was absorbed by cooling that key and moving to another, and the run never stopped. Request intent: 60 of 60 agree with the rules. Screenshots: the model found 56.9% of the identifiers OCR found, and 89.2% of its own were also in OCR; evidence_19, 42 and 46 gave nothing usable, so OCR stays the primary reader. `output.csv` sha256 `55fabff2...edb81` unchanged. The committed `usage_report.md` and `evaluation_report.md` are the output of that run.

Against HackerRank's own `sample_output.csv` (32 cases, official clone): status accuracy 0.906 (29/32), **false COMPLETE 0**, step precision 0.744, recall 0.663, **F1 0.701**, exact cases 11/32, field accuracy 0.771; 161 of 193 expected steps reproduced, evidence id correct on every matched step. HackerRank publishes no answers for the 518, so those cannot be scored.

## Known limits

- 7 hand-made teaching cases (`account_001`..`010`) use a different timing regime with too few labelled pairs to validate; 7 further cases stay ambiguous (request order, case number and activity-id order were tested as tiebreakers and are at chance).
- Support records: HackerRank's DELETE-vs-REDACT choice for 2 cases has no safe general rule; `support_replica` is not aliased to `support_platform`.
- The linker's validated groups were learned on the 518; the 32 public samples are only a proxy and some of their timing patterns differ.
- `usage_report.md` states 0 model calls (true, the pipeline is deterministic); no real API run has been measured.
- Groq applies rate limits per organization (its rate-limit page says so). Failing over across keys always helps against a revoked or mistyped key, but adds quota only when the keys belong to different organizations.
- The model id depends on the account; `--check-keys` confirms it without spending tokens. Strict JSON-schema decoding is not available on every Groq model and is not documented together with images, so replies are requested in JSON mode and validated here.
- Token and priced-budget ceilings are checked before a call and can overshoot by one call; `SLAM_API_MAX_CALLS` is exact.
- The real-model figures come from one run (2026-11-05, four keys, `qwen/qwen3.8-27b`), so they are a sample, not a benchmark; rerun `--model-check` to refresh them.
- Agreement between the model and the rules is not accuracy: there are no published answers for the 518.
- See `docs/integration/RCA_ACCURACY.md` for the evidence behind every item.

## Integration notes

Merge record (append-only; newest last). One row per unit merged into `dev` or `main`.

| Date | Unit | Merged commit | Gates run | Result | Notes |
|---|---|---|---|---|---|
| 2026-11-04 | Ashish ingestion, PR #3, with foundation baseline B1 (`0bbee13`) | `2666ffe` | none recorded: merged before this mechanism, `dev` had no workflows; owner's own Docker run is in `ashish.md` | merged by Lalith; Satvika commented "good", Lalith approved | Retroactive entry. 98 files: 47 ingestion plus the baseline. No delivery note existed; `ashish.md` was written afterwards |
| 2026-11-04 | Integration mechanism, PR #4 (`integration/mechanism`, head `9a59d3d`) | `0d02a57` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 16:57Z; he approved; Satvika's review request was left pending | Retroactive entry. First push failed the Docker platform job because the image has no git; fixed by skipping the 18 git-dependent tests there (they run in the host gates) |
| 2026-11-04 | Reconstruction, evaluation scorer and validator, planner and pipeline, PR #5 (`integration/reconstruction`, head `7f284f1`) | `bf40c39` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by Satvika0404 at 21:13Z; approved by Satvika0404 | Retroactive entry. Manya's `152b0a2` merged intact; Lalith's scorer and Satvika's validator merged unchanged; `plan_case` is the integrator's stand-in because `plan()` was still a stub |
| 2026-11-04 | Output-quality pass, PR #7 (`integration/account-linking`, head `58ed664`) | `a722cbc` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 23:17Z; approved by dglalithchandra | Retroactive entry. Parser fix, learned account linking, retained-record checks, `scripts/build_submission.py`. Measured on the 32 public answers: status 29/32, false COMPLETE 0, step F1 0.701 |
| 2026-11-05 | Submission package, PR #8 (`integration/submission-reports`, head `634fe18`) | `c36b6eb` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 01:33Z; approved by dglalithchandra | Reports now in `code/evaluation/`, the `code.zip` self-check requires them, merge-record rows for PR #4, #5 and #7 added, Manya `INTEGRATED`. `output.csv` byte-identical to `dev` before the PR |
| 2026-11-05 | Groq provider with ordered multi-key failover, metering and measured model cross-check, PR #10 (`integration/model-check`, head `653e51c`) | `b4382c9` | Delivery note, Merge gate, Quick gate, Docker platform: all SUCCESS | merged by dglalithchandra at 02:25Z; approved by dglalithchandra | Retroactive entry. Decision path untouched, `output.csv` byte-identical; real Groq run recorded in the reports. Open PR #9 (Satvika) and PR #6 (Lalith) are not part of it |
