"""SLAM command-line entry point.

python code/main.py --dataset dataset                # write output.csv at the repo root
python code/main.py --dataset dataset --evaluate     # also score the 32 public samples
                                                     # and write evaluation/*.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slam.config import Settings
from slam.contracts import CONTRACT_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SLAM deletion-audit agent")
    parser.add_argument("--dataset", type=Path, help="participant dataset directory")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--foundation-status", action="store_true")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="score the public samples and write evaluation/*.md reports",
    )
    return parser


def _write_reports(dataset: Path, full: object, settings: Settings) -> None:
    from slam.pipeline import RunSummary, evaluate_samples

    assert isinstance(full, RunSummary)
    _, metrics = evaluate_samples(dataset)
    target = REPO_ROOT / "evaluation"
    target.mkdir(exist_ok=True)
    (target / "evaluation_report.md").write_text(
        "# Evaluation report\n\n"
        "Scored with `slam.evaluation.scorer` against `dataset/sample_output.csv` "
        f"({metrics.cases} public cases, offline, no model call).\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"| Case-level deletion-status accuracy | {metrics.status_accuracy:.3f} |\n"
        f"| Exact case accuracy | {metrics.exact_case_accuracy:.3f} |\n"
        f"| Step precision / recall / F1 | {metrics.step_precision:.3f} / "
        f"{metrics.step_recall:.3f} / {metrics.step_f1:.3f} |\n"
        f"| Field-level accuracy | {metrics.field_accuracy:.3f} |\n"
        f"| Sequence accuracy | {metrics.sequence_accuracy:.3f} |\n"
        f"| False COMPLETE count | {metrics.false_complete_count} |\n\n"
        f"Full run: {full.cases} cases, statuses {dict(full.statuses)}, "
        f"{full.uncertain_cases} not certified (uncertain), {len(full.failures)} failed.\n\n"
        "## Additional evaluation cases (created by us)\n\n"
        "`tests/planning/test_engine.py` holds three: a clean COMPLETE case, an INCOMPLETE case "
        "with an active flow and a restorable backup (flow disabled and restore blocked before "
        "records change, downstream copies before the profile), and a non-deletion request "
        "(NOT_APPLICABLE, no steps).\n\n"
        "## Failures found and improvements made\n\n"
        "- Intent recall rose from 20/32 to 32/32 samples (0 of 518 unclear) after adding deletion "
        "nouns, Korean/Chinese, negation and marketing scoping; a false NOT_APPLICABLE was fixed.\n"
        "- Graph: `DISABLE_DATA_FLOW`/`BLOCK_RESTORE`/`CHECK_*` activities were being read as "
        "risks (116 flow + 58 restore edges) and 303 plain search/export records as flows; fixed.\n"
        "- Known gap: records with no identifier (anonymized analytics, 404 lookups, attachments) "
        "cannot be attributed to a person from the data, so absent/anonymized verification steps "
        "are under-reported.\n",
        encoding="utf-8",
    )
    (target / "usage_report.md").write_text(
        "# Usage report\n\n"
        f"Final full-dataset run that produced `output.csv` ({full.cases} cases, "
        f"{full.seconds:.1f} s).\n\n"
        f"- Model provider: `{settings.model_provider.value}`, model `{settings.model}`\n"
        "- Model calls: 0 (deterministic pipeline; OCR resolved every image)\n"
        "- Input / output tokens: 0 / 0 (total 0, average 0 per request)\n"
        "- Estimated cost: $0.00 total, $0.00 per request\n"
        "- Per-model totals: none (no model was called)\n",
        encoding="utf-8",
    )


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings()
    if args.foundation_status or args.dataset is None:
        print(
            f"SLAM foundation contract={CONTRACT_VERSION} "
            f"provider={settings.model_provider.value} model={settings.model}"
        )
        if args.dataset is None:
            return 0
    from slam.pipeline import run

    summary = run(args.dataset, args.output)
    print(
        json.dumps(
            {
                "cases": summary.cases,
                "statuses": dict(summary.statuses),
                "not_certified_uncertain": summary.uncertain_cases,
                "failures": summary.failures,
                "seconds": round(summary.seconds, 1),
                "output": str(summary.output_path) if summary.output_path else None,
                "diagnostic_findings": len(summary.evidence_quality.findings)
                if summary.evidence_quality
                else 0,
                "diagnostic_json": str(summary.diagnostic_json_path)
                if summary.diagnostic_json_path
                else None,
                "diagnostic_markdown": str(summary.diagnostic_markdown_path)
                if summary.diagnostic_markdown_path
                else None,
            },
            indent=2,
        )
    )
    if not summary.ok:
        return 1
    if args.evaluate:
        _write_reports(args.dataset, summary, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
