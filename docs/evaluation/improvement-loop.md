# Bounded reliability improvement loop

The loop in `code/slam/evaluation/improvement/` is a development tool. The production audit
pipeline does not import or execute it. It cannot change source evidence, identity links, policy,
deletion status, or certification decisions.

## Setup and checks

Use the existing locked image and dependencies; no dependency or contract changes are required.

```powershell
docker compose build
docker compose run --rm slam-dev pytest -q tests/evaluation/test_improvement_loop.py
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
```

The isolated candidate runner uses the already-built `slam-dev:py311` image, network isolation,
a read-only checkout mount, a temporary virtual environment, and a per-run disposable copy of the
read-only `slam_uv-cache` volume. Prime that cache with the normal Compose test command before
relying on offline candidate checks:

```powershell
docker compose run --rm slam-dev pytest -q
```

## Inputs and workflow

`generate_scenario(seed)` deterministically returns a fictional `AuditRequest` and a valid
participant-like `EvidenceBundle`, plus a readable synthetic event timeline. The scenario has no
expected answer field. The caller sends only `scenario.request` and `scenario.bundle` through
reconstruction/planning. Keep expected status, expected steps, and expected defects in a separate
test-only mapping and pass them only to `score_scenarios` after predictions are produced.

The module APIs compose the intended flow:

1. Diagnose/reproduce a failure and create a `FailureRecord` with a seed, versions, diagnostic
   codes, and opaque sanitized references; append it to a `FailureStore` JSONL file.
2. Generate a scenario from the stored seed and run the normal audit implementation on its
   participant-like request and evidence only.
3. Use `ImprovementLoop` to record the ordered diagnose/reproduce/generate/propose/evaluate/accept
   or reject/record transitions. `RecoveryPolicy` allows only named local handlers, at most three
   attempts, and explicit time/token budgets. Each handler receives a monotonic deadline and its
   remaining token allowance, which it must honor. Its log excludes exception text and input payloads.
4. Compare baseline and candidate predictions against the same development set and a disjoint
   held-out synthetic set using `score_scenarios` and `evaluate_candidate_sets`.
5. Validate the proposed unified diff with `validate_patch_paths`; then use
   `evaluate_patch_in_isolation` to apply it to a temporary copy and run the fixed command
`uv sync --frozen --offline && python -m pytest -p no:cacheprovider -q tests/evaluation` in Docker. Candidate-provided
   commands are never run. Only `code/slam/evaluation/improvement/**` and `tests/evaluation/**`
   may be changed by this repair loop.
6. Record the combined development/held-out decision with `ImprovementLoop.record_suite`, build one
   report containing both comparisons with `report_for_suite`, and write reviewable JSON and
   Markdown with `write_improvement_report`. An accepted result means eligible for human review
   only; it does not merge, deploy, or certify a production result.

Candidate scoring requires identical fixture IDs, case IDs, and denominators for each baseline /
candidate pair. The development and held-out fixture sets must have distinct IDs and disjoint
scenario IDs. Acceptance requires the reproduced failure to be fixed, checks to pass, declared
budgets to hold, no measured regressions, and no increase in false COMPLETE count/rate in either
set. A finite synthetic suite is not proof of correctness.

## Reports and limitations

`ImprovementReport` contains the false COMPLETE count and denominator, status and step accuracy,
defect precision/recall, regression count, latency, API calls, cost, assumptions, unknowns, and the
scenario-set label. Synthetic measurements are not presented as real-data performance. A zero-case
set is not accepted as a candidate comparison.

This increment supplies scenario construction, isolated evaluation, scoring, and reporting
primitives. It does not yet connect the existing diagnostic finding stream to automatic scenario
mutation or to an autonomous model repair proposer. The existing `ModelProvider` may be used by a
separately reviewed development adapter, but proposals must be schema/path checked and must never
be executed as commands. The Docker check requires Docker Desktop, the `slam-dev:py311` image, and
an offline-populated `slam_uv-cache` volume. If these are missing, evaluation rejects/blocks rather
than falling back to executing candidate code on the host. The participant `dataset/` is absent in
this checkout, so no real-data or hidden-case results are available.
