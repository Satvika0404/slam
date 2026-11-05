"""SLAM command-line entry point.

python code/main.py --dataset dataset                # write output.csv at the repo root
python code/main.py --dataset dataset --evaluate     # also score the 32 public samples
                                                     # and write code/evaluation/*.md
python code/main.py --check-keys                     # probe the configured Groq keys (no tokens)
python code/main.py --dataset dataset --model-check  # also run the measured model cross-check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slam.config import ProviderName, Settings
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
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="probe every configured Groq key and the model name; spends no tokens",
    )
    parser.add_argument(
        "--model-check",
        action="store_true",
        help=(
            "also call the configured model on purpose (screenshots and request intent), compare "
            "it with OCR and the rules, and report real usage; implies --evaluate; never changes "
            "output.csv"
        ),
    )
    parser.add_argument(
        "--model-check-requests",
        type=int,
        default=60,
        help="how many request texts the intent cross-check sends to the model (default 60)",
    )
    return parser


def _check_keys(settings: Settings) -> int:
    if settings.model_provider is not ProviderName.GROQ:
        print("--check-keys needs SLAM_MODEL_PROVIDER=groq (see .env.example)")
        return 2
    from slam.runtime.groq_provider import GroqModelProvider

    results = GroqModelProvider(settings).check_keys()
    for result in results:
        model = (
            ""
            if result.model_available is None
            else f", model {settings.model!r} {'found' if result.model_available else 'NOT FOUND'}"
        )
        print(f"{result.label}: {result.status}{model}")
    usable = [r for r in results if r.status == "ok" and r.model_available]
    return 0 if usable else 1


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings()
    if args.check_keys:
        return _check_keys(settings)
    if args.foundation_status or args.dataset is None:
        print(
            f"SLAM foundation contract={CONTRACT_VERSION} "
            f"provider={settings.model_provider.value} model={settings.model}"
        )
        if args.dataset is None:
            return 0
    from evaluation.main import write_reports
    from slam.pipeline import run
    from slam.runtime.factory import build_provider
    from slam.runtime.metering import UsageLedger

    metered = None
    if args.model_check:
        metered = build_provider(settings, UsageLedger())
        if metered is None:
            print("--model-check needs a real provider: set SLAM_MODEL_PROVIDER (see .env.example)")
            return 2

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
    if metered is not None:
        from evaluation.model_check import run_model_check

        check = run_model_check(args.dataset, metered, intent_sample=args.model_check_requests)
        print(
            json.dumps(
                {
                    "model_check": {
                        "provider": check.provider,
                        "model": check.model,
                        "calls": check.attempted_calls,
                        "failed": check.failed_calls,
                        "tokens": check.total_tokens,
                        "stopped": check.stopped,
                    }
                },
                indent=2,
            )
        )
        write_reports(args.dataset, summary, settings, model_check=check)
    elif args.evaluate:
        write_reports(args.dataset, summary, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
