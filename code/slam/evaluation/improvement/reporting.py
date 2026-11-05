"""Deterministic JSON and Markdown reporting for development-loop outcomes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from slam.evaluation.improvement.candidates import CandidateResult, CandidateSuiteResult


@dataclass(frozen=True, slots=True)
class ImprovementReport:
    scenario_label: str
    failure_fingerprint: str
    seed: int
    attempt: int
    decision: str
    candidate: CandidateResult
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    development_result: CandidateResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def render_markdown(report: ImprovementReport) -> str:
    base = report.candidate.baseline
    cand = report.candidate.candidate

    def rate(value: float | None) -> str:
        return "not measurable (0 denominator)" if value is None else f"{value:.4f}"

    patch_paths = ", ".join(f"`{path}`" for path in report.candidate.patch_paths) or "none"

    lines = [
        "# SLAM improvement-loop report",
        "",
        f"- Scenario set: **{report.scenario_label}**",
        f"- Fixture set ID: `{report.candidate.baseline.fixture_set_id}`",
        f"- Failure fingerprint: `{report.failure_fingerprint}`",
        f"- Seed: `{report.seed}`; attempt: `{report.attempt}` of at most 3",
        f"- Decision: **{report.decision}**",
        "",
        "## Baseline and candidate",
        "",
        "| Metric | Baseline | Candidate |",
        "|---|---:|---:|",
        "| False COMPLETE | "
        f"{base.false_complete_count}/{base.cases} ({rate(base.false_complete_rate)}) | "
        f"{cand.false_complete_count}/{cand.cases} ({rate(cand.false_complete_rate)}) |",
        f"| Status accuracy | {base.status_accuracy:.4f} | {cand.status_accuracy:.4f} |",
        f"| Step accuracy | {base.step_accuracy:.4f} | {cand.step_accuracy:.4f} |",
        "| Defect precision | "
        f"{base.defect_detection_precision:.4f} | {cand.defect_detection_precision:.4f} |",
        "| Defect detection recall | "
        f"{base.defect_detection_recall:.4f} | {cand.defect_detection_recall:.4f} |",
        f"| Latency (ms) | {base.latency_ms} | {cand.latency_ms} |",
        f"| API calls | {base.api_calls} | {cand.api_calls} |",
        f"| Cost (USD) | {base.cost_usd} | {cand.cost_usd} |",
        f"| Observed regressions | {base.regression_count} | {cand.regression_count} |",
        "",
        "Results are finite-set measurements, not a guarantee of correctness. "
        "Synthetic and real-data results are reported separately.",
        "",
        "## Checks and patch",
        "",
        f"- Reproduced failure fixed: `{report.candidate.reproduced_failure_fixed}`",
        f"- Required checks passed: `{report.candidate.checks_passed}`",
        f"- Within declared budgets: `{report.candidate.within_budget}`",
        f"- Patch paths: {patch_paths}",
        "",
        "## Assumptions and unknowns",
        "",
        *(f"- Assumption: {item}" for item in report.assumptions),
        *(f"- Unknown: {item}" for item in report.unknowns),
    ]
    if report.development_result is not None:
        dev_base = report.development_result.baseline
        dev_candidate = report.development_result.candidate
        lines.extend(
            [
                "",
                "## Development baseline and candidate",
                "",
                "| Metric | Baseline | Candidate |",
                "|---|---:|---:|",
                "| Fixture set ID | "
                f"`{dev_base.fixture_set_id}` | `{dev_candidate.fixture_set_id}` |",
                "| False COMPLETE | "
                f"{dev_base.false_complete_count}/{dev_base.cases} "
                f"({rate(dev_base.false_complete_rate)}) | "
                f"{dev_candidate.false_complete_count}/{dev_candidate.cases} "
                f"({rate(dev_candidate.false_complete_rate)}) |",
                f"| Status accuracy | {dev_base.status_accuracy:.4f} | "
                f"{dev_candidate.status_accuracy:.4f} |",
                f"| Step accuracy | {dev_base.step_accuracy:.4f} | "
                f"{dev_candidate.step_accuracy:.4f} |",
                f"| Defect precision | {dev_base.defect_detection_precision:.4f} | "
                f"{dev_candidate.defect_detection_precision:.4f} |",
                f"| Defect detection recall | {dev_base.defect_detection_recall:.4f} | "
                f"{dev_candidate.defect_detection_recall:.4f} |",
                f"| Latency (ms) | {dev_base.latency_ms} | {dev_candidate.latency_ms} |",
                f"| API calls | {dev_base.api_calls} | {dev_candidate.api_calls} |",
                f"| Cost (USD) | {dev_base.cost_usd} | {dev_candidate.cost_usd} |",
                f"| Observed regressions | {dev_base.regression_count} | "
                f"{dev_candidate.regression_count} |",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def report_for_suite(
    suite: CandidateSuiteResult,
    *,
    failure_fingerprint: str,
    seed: int,
    attempt: int,
    assumptions: tuple[str, ...] = (),
    unknowns: tuple[str, ...] = (),
) -> ImprovementReport:
    """Build one report containing independent development and held-out comparisons."""
    return ImprovementReport(
        scenario_label="synthetic",
        failure_fingerprint=failure_fingerprint,
        seed=seed,
        attempt=attempt,
        decision=suite.decision,
        candidate=suite.held_out,
        assumptions=assumptions,
        unknowns=unknowns,
        development_result=suite.development,
    )


def write_improvement_report(
    report: ImprovementReport, json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
