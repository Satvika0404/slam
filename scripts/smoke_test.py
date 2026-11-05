"""Smoke test: run ONE random case through every stage, check invariants, explain differences.

    docker compose run --rm -T slam-dev python scripts/smoke_test.py --dataset dataset --seed 7

Picks a random public sample (has an answer key, so it is diffed) and a random evaluation case
(no key, so only invariants are checked). Exits non-zero if any hard check fails. It never
tunes anything: the diff against the key is a diagnostic, not an input.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

from slam.contracts import AuditRequest, CaseAnswer, DeletionStatus
from slam.ingestion.api import ingest, load_requests
from slam.pipeline import eligible_evidence_ids, load_request_file
from slam.planning.engine import plan_case
from slam.planning.validation import validate_answer
from slam.reconstruction import linking, reconstruct_with_links


def _steps(answer: CaseAnswer) -> set[tuple[str, str, str, str]]:
    return {(s.phase.value, s.operation.value, s.system_id, s.resource_id) for s in answer.steps}


def check_case(request: AuditRequest, bundle, model, key_row: dict[str, str] | None) -> list[str]:  # type: ignore[no-untyped-def]
    """Return the list of HARD failures; print the trace as a side effect."""

    failures: list[str] = []
    context = reconstruct_with_links(request, bundle, model)
    answer = plan_case(context, bundle)
    print(f"\n=== {request.case_id}  audit_at={request.audit_at.isoformat()}")
    print(f"  intent={context.request_intent.value} subject={context.subject_id}")
    print(
        f"  eligible_obs={len(context.eligible_observation_ids)} "
        f"future_excluded={len(context.excluded_future_observation_ids)} "
        f"states={len(context.resource_states)} flows={len(context.active_flows)} "
        f"restores={len(context.restore_risks)}"
    )
    print(f"  blocking: conflicts={len(context.unresolved_conflicts)} "
          f"coverage={len(context.coverage_issues)}")
    print(f"  status={answer.deletion_status.value if answer.deletion_status else None} "
          f"steps={len(answer.steps)}")
    for step in answer.steps[:10]:
        print(f"    {step.step_no:2d} {step.phase.value[:4]} {step.operation.value:26s} "
              f"{step.system_id}/{step.resource_id} [{step.evidence_id}]")

    if answer.deletion_status is None:
        failures.append("no supported status")
        return failures
    eligible = eligible_evidence_ids(bundle, request.audit_at)
    try:
        validate_answer(answer, eligible_evidence_ids=eligible)
    except Exception as exc:
        failures.append(f"answer validation: {exc}")
    cited = {s.evidence_id for s in answer.steps if s.evidence_id}
    if cited - eligible:
        failures.append(f"cites evidence not eligible at audit_at: {sorted(cited - eligible)}")
    future = {o.observation_id for o in bundle.observations if o.effective_time > request.audit_at}
    if future & set(context.eligible_observation_ids):
        failures.append("a future observation is eligible")
    again = plan_case(reconstruct_with_links(request, bundle, model), bundle)
    if again.model_dump_json() != answer.model_dump_json():
        failures.append("not deterministic on rerun")
    status = answer.deletion_status
    phases = {s.phase.value for s in answer.steps}
    if status is DeletionStatus.NOT_APPLICABLE and answer.steps:
        failures.append("NOT_APPLICABLE has steps")
    if status is DeletionStatus.COMPLETE and (phases - {"VERIFICATION"} or not answer.steps):
        failures.append("COMPLETE must be verification-only and non-empty")
    if status is DeletionStatus.INCOMPLETE and answer.steps and "VERIFICATION" not in phases:
        failures.append("INCOMPLETE has no verification")

    if key_row is not None:
        expected = json.loads(key_row["steps_json"])
        want = {(s["phase"], s["operation"], s["system_id"], s["resource_id"]) for s in expected}
        got = _steps(answer)
        print(f"  KEY status={key_row['deletion_status']} "
              f"{'MATCH' if key_row['deletion_status'] == status.value else 'MISMATCH'}; "
              f"steps matched {len(want & got)}/{len(want)}, extra {len(got - want)}")
        for item in sorted(want - got):
            print("    missing:", item)
        for item in sorted(got - want):
            print("    extra  :", item)
        if status is DeletionStatus.COMPLETE and key_row["deletion_status"] != "COMPLETE":
            failures.append("FALSE COMPLETE against the key")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    samples = load_request_file(args.dataset / "sample_deletion_requests.csv")
    key = {r["case_id"]: r for r in csv.DictReader(
        (args.dataset / "sample_output.csv").open(encoding="utf-8"))}
    full = load_requests(args.dataset)
    bundle = ingest(args.dataset)
    model = linking.fit(bundle, tuple({r.case_id: r for r in (*samples, *full)}.values()))
    print(f"link groups enabled: {len(model.groups)}")
    picks = [(rng.choice(samples), True), (rng.choice(full), False)]
    failures: list[str] = []
    for request, labelled in picks:
        failures += [f"{request.case_id}: {f}" for f in
                     check_case(request, bundle, model, key[request.case_id] if labelled else None)]
    print("\nSMOKE", "FAIL" if failures else "PASS", *failures, sep="\n  " if failures else " ")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
