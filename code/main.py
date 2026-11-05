"""SLAM command-line entry point.

python code/main.py --dataset dataset                # write output.csv at the repo root
python code/main.py --dataset dataset --evaluate     # also score the 32 public samples
                                                     # and write code/evaluation/*.md
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
        help="score the public samples and write code/evaluation/*.md reports",
    )
    return parser


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
    from evaluation.main import write_reports
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
        write_reports(args.dataset, summary, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
