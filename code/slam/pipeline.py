"""End-to-end run: requests + evidence -> validated answers -> ``output.csv`` -> reports.

Follows the project flow: load requests, ingest evidence once, then per case reconstruct,
plan and validate. A failing case is isolated and recorded, never replaced by a guess, and
the run reports failure until every required case has a supported answer.
"""

from __future__ import annotations

import csv
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from slam.contracts import AuditRequest, CaseAnswer, DeletionStatus, EvidenceBundle
from slam.evaluation.scorer import EvaluationMetrics, score_outputs
from slam.evaluation.validator import validate_output_csv
from slam.ingestion.api import ingest, load_requests
from slam.planning.engine import plan_case
from slam.planning.export import export_output_csv
from slam.planning.validation import validate_answer
from slam.reconstruction import linking, reconstruct_with_links
from slam.runtime.provider import ModelProvider


@dataclass(slots=True)
class RunSummary:
    cases: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    failures: dict[str, str] = field(default_factory=dict)
    uncertain_cases: int = 0
    link_groups: list[str] = field(default_factory=list)
    seconds: float = 0.0
    output_path: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and self.cases > 0


def load_request_file(path: Path) -> tuple[AuditRequest, ...]:
    """Load a requests CSV with the same columns as ``deletion_requests.csv``."""

    def when(value: str) -> datetime:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))

    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(
            AuditRequest(
                case_id=row["case_id"],
                email=row["email"],
                requested_at=when(row["requested_at"]),
                reported_status=row["reported_status"],
                reported_at=when(row["reported_at"]),
                audit_at=when(row["audit_at"]),
                request_text=row["request_text"],
            )
            for row in csv.DictReader(handle)
        )


def eligible_evidence_ids(bundle: EvidenceBundle, audit_at: datetime) -> set[str]:
    """Participant-visible ids that exist at the cutoff and may therefore be cited."""

    return (
        {item.source_id for item in bundle.sources if item.captured_at <= audit_at}
        | {item.activity_id for item in bundle.activities if item.occurred_at <= audit_at}
        | {item.audit_id for item in bundle.identity_changes if item.changed_at <= audit_at}
    )


def answer_cases(
    requests: tuple[AuditRequest, ...],
    bundle: EvidenceBundle,
    *,
    provider: ModelProvider | None = None,
    link_model: linking.LinkModel | None = None,
) -> tuple[list[CaseAnswer], dict[str, str]]:
    answers: list[CaseAnswer] = []
    failures: dict[str, str] = {}
    for request in requests:
        try:
            context = reconstruct_with_links(request, bundle, link_model, provider=provider)
            answer = plan_case(context, bundle)
            if answer.deletion_status is not None:
                answer = validate_answer(
                    answer, eligible_evidence_ids=eligible_evidence_ids(bundle, request.audit_at)
                )
            answers.append(answer)
        except Exception as exc:  # one bad case must not stop the run
            failures[request.case_id] = f"{type(exc).__name__}: {exc}"[:300]
    return answers, failures


def run(
    dataset_dir: Path,
    output_path: Path,
    *,
    requests_file: Path | None = None,
    provider: ModelProvider | None = None,
    cache_dir: Path | None = None,
    cohort: tuple[AuditRequest, ...] = (),
) -> RunSummary:
    started = time.monotonic()
    requests = load_request_file(requests_file) if requests_file else load_requests(dataset_dir)
    bundle = ingest(dataset_dir, cache_dir=cache_dir, provider=provider)
    # Timing signatures are learned from every known request (the cohort), not only this run's.
    everyone = tuple({r.case_id: r for r in (*requests, *cohort)}.values())
    model = linking.fit(bundle, everyone)
    answers, failures = answer_cases(requests, bundle, provider=provider, link_model=model)
    summary = RunSummary(cases=len(requests), failures=failures)
    summary.link_groups = [
        f"{g.key[0]}@{g.key[1]} window {g.window[0]:.0f}..{g.window[1]:.0f} min, "
        f"{g.pairs} pairs, {g.resolved:.0%} resolved"
        for g in model.groups
    ]
    for answer in answers:
        if answer.deletion_status is None:
            summary.failures[answer.case_id] = "; ".join(answer.blocking_issues)
        else:
            summary.statuses[answer.deletion_status.value] += 1
            if answer.trace.get("not_certified_because"):
                summary.uncertain_cases += 1
    if summary.ok:
        required = [request.case_id for request in requests]
        export_output_csv(answers, required, output_path)
        by_id = {request.case_id: request for request in requests}
        validate_output_csv(
            output_path,
            expected_case_ids=required,
            eligible_evidence_ids=set().union(
                *(eligible_evidence_ids(bundle, by_id[case].audit_at) for case in required)
            ),
        )
        summary.output_path = output_path
    summary.seconds = time.monotonic() - started
    return summary


def evaluate_samples(
    dataset_dir: Path, *, provider: ModelProvider | None = None
) -> tuple[RunSummary, EvaluationMetrics]:
    """Run the 32 public samples and score them against ``sample_output.csv``."""

    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "sample_prediction.csv"
        summary = run(
            dataset_dir,
            target,
            requests_file=dataset_dir / "sample_deletion_requests.csv",
            provider=provider,
            cohort=load_requests(dataset_dir),
        )
        if not summary.ok:
            raise RuntimeError(f"sample run failed: {summary.failures}")
        return summary, score_outputs(target, dataset_dir / "sample_output.csv")


def status_of(answer: CaseAnswer) -> DeletionStatus | None:
    return answer.deletion_status
