"""SLAM command-line entry point.

python code/main.py --dataset dataset                # write output.csv at the repo root
python code/main.py --dataset dataset --evaluate     # also score the 32 public samples
                                                     # and write code/evaluation/*.md
python code/main.py --check-keys                     # probe the configured Groq keys (no tokens)
python code/main.py --dataset dataset --model-check  # also run the measured model cross-check
python code/main.py --dataset dataset --insight      # write dashboard/insight_data.json
python code/main.py --dataset dataset --serve        # live console: re-run on a deletion
python code/main.py --dataset dataset --console      # build what is missing, then serve
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
    parser.add_argument(
        "--insight",
        action="store_true",
        help=(
            "build dashboard/insight_data.json: LightGBM failure risk, DBSCAN patterns, recreation "
            "paths and explanations; uses the configured model for explanations when one is set; "
            "never changes output.csv"
        ),
    )
    parser.add_argument(
        "--insight-llm",
        type=int,
        default=80,
        help="how many failed cases get a model-written explanation (default 80)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "serve the console and run the insight stages live on a what-if deletion "
            "(Neo4j delete, re-audit, LightGBM, DBSCAN, model explanations); never changes "
            "output.csv"
        ),
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="like --serve, but first build every file the page needs that is missing",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="with --console, rebuild the dashboard data and the stored insight data too",
    )
    parser.add_argument("--serve-host", default="127.0.0.1", help="interface to listen on")
    parser.add_argument("--serve-port", type=int, default=8765)
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


def _serve(args: argparse.Namespace, settings: Settings) -> int:
    from slam.insight.console import prepare_console
    from slam.insight.server import serve, serve_prepared

    dashboard = REPO_ROOT / "dashboard"
    cache = REPO_ROOT / ".slam-cache" / "insight_explain.json"
    if args.console:
        prep = prepare_console(
            args.dataset,
            dashboard,
            settings,
            cache_path=cache,
            output_csv=args.output,
            refresh=args.refresh,
            say=lambda line: print(line, flush=True),
        )
        server = serve_prepared(
            prep, dashboard, settings, host=args.serve_host, port=args.serve_port, cache=cache
        )
    else:
        print("auditing the 518 cases once, this takes about half a minute...", flush=True)
        server = serve(
            args.dataset,
            dashboard,
            settings,
            host=args.serve_host,
            port=args.serve_port,
            cache=cache,
        )
    host, port = server.address
    print(f"live console ready: http://127.0.0.1:{port}/  (listening on {host}:{port})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.close()
    return 0


def _insight(args: argparse.Namespace, settings: Settings) -> int:
    from slam.insight.build import run_insight
    from slam.runtime.factory import build_provider
    from slam.runtime.metering import UsageLedger

    provider = build_provider(settings, UsageLedger())
    result = run_insight(
        args.dataset,
        REPO_ROOT / "dashboard",
        settings=settings,
        provider=provider,
        llm_cases=args.insight_llm,
        cache_dir=REPO_ROOT / ".slam-cache",
        output_csv=args.output,
    )
    from slam.results import write_insight_summary

    write_insight_summary(REPO_ROOT / "results", result.output_path)
    print(
        json.dumps(
            {
                "insight": {
                    "cases": result.cases,
                    "llm_selected": result.llm_selected,
                    "llm_accepted": result.llm_accepted,
                    "stopped": result.stopped,
                    "data": str(result.output_path),
                    "prompt": str(result.prompt_path),
                }
            },
            indent=2,
        )
    )
    return 0


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

    if args.serve or args.console:
        return _serve(args, settings)
    if args.insight:
        return _insight(args, settings)

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
    from slam.results import write_results

    for written in write_results(REPO_ROOT / "results", summary, args.output, args.dataset):
        print(f"wrote {written.relative_to(REPO_ROOT)}")
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
