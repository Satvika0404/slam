"""The optional model cross-check: sampling, comparison, stopping, and honest reporting."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import main as cli
import pytest
from evaluation.model_check import (
    ImageRow,
    IntentCheck,
    ModelCheckReport,
    _sample_requests,
    evaluation_section,
    run_model_check,
    usage_lines,
)
from PIL import Image
from slam.contracts import RequestIntent
from slam.ingestion.parsers.image_parser import ExtractedRecord, ImageExtraction
from slam.reconstruction.request_intent import IntentProposal
from slam.runtime.fake_provider import FakeModelProvider
from slam.runtime.key_pool import KeyReport
from slam.runtime.metering import MeteredProvider, UsageLedger
from slam.runtime.provider import ModelQuotaError

DELETE = "Please delete my account and every record you hold about me."
EXPORT = "Could you send me a copy of the data you hold about me?"


def build_dataset(root: Path) -> Path:
    (root / "evidence" / "images").mkdir(parents=True)
    Image.new("RGB", (80, 40), "white").save(root / "evidence" / "images" / "console.png")
    with (root / "evidence_files.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file_id", "file_path", "origin", "captured_at"])
        writer.writerow(
            ["evidence_90", "evidence/images/console.png", "admin_console", "2026-09-01T10:00:00Z"]
        )
    with (root / "deletion_requests.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "email",
                "requested_at",
                "reported_status",
                "reported_at",
                "audit_at",
                "request_text",
            ]
        )
        for case_id, text in (("case_01", DELETE), ("case_02", EXPORT), ("case_03", DELETE)):
            writer.writerow(
                [
                    case_id,
                    f"{case_id}@example.com",
                    "2026-08-01T08:00:00Z",
                    "COMPLETE",
                    "2026-08-02T08:00:00Z",
                    "2026-08-05T08:00:00Z",
                    text,
                ]
            )
    return root


def proposal(intent: RequestIntent, text: str) -> IntentProposal:
    return IntentProposal(intent=intent, supporting_excerpt=text[:12])


def test_sampling_keeps_every_non_deletion_then_spreads_the_rest_evenly() -> None:
    rows = [(f"case_{n:02d}", "t", RequestIntent.DELETION) for n in range(1, 21)]
    rows.append(("case_90", "t", RequestIntent.NON_DELETION))
    rows.append(("case_91", "t", RequestIntent.UNCLEAR))
    chosen = _sample_requests(rows, 6)
    ids = [row[0] for row in chosen]
    assert "case_90" in ids and "case_91" in ids
    assert len(chosen) == 6
    assert ids == sorted(ids)
    assert _sample_requests(rows, 0) == []
    assert [r[0] for r in _sample_requests(rows, 1)] == ["case_90"]


def test_cross_check_compares_the_model_with_the_rules_and_with_ocr(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    inner = FakeModelProvider(
        [
            ImageExtraction(records=[ExtractedRecord(resource_id="backup_9287")]),
            proposal(RequestIntent.DELETION, DELETE),  # case_01: agrees
            proposal(RequestIntent.DELETION, EXPORT),  # case_02: model disagrees with the rules
            proposal(RequestIntent.DELETION, DELETE),  # case_03: agrees
        ]
    )
    metered = MeteredProvider(inner, UsageLedger(), max_calls=20)
    report = run_model_check(dataset, metered, intent_sample=3)

    assert report.requests_total == 3
    assert report.attempted_calls == 4 and report.failed_calls == 0
    assert report.intent.sampled == 3
    assert report.intent.agree + len(report.intent.disagreements) + report.intent.unusable == 3
    assert [d.case_id for d in report.intent.disagreements] == ["case_02"]
    (image,) = report.images
    assert (image.file_id, image.model_ids) == ("evidence_90", 1)
    assert report.stopped is None


def test_a_ceiling_or_quota_stops_the_check_instead_of_hammering_the_api(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    inner = FakeModelProvider(
        [
            ImageExtraction(records=[]),
            ModelQuotaError("all keys used up"),
        ]
    )
    metered = MeteredProvider(inner, UsageLedger(), max_calls=20)
    report = run_model_check(dataset, metered, intent_sample=3)
    assert report.stopped == "ModelQuotaError"
    assert report.attempted_calls == 2  # the image call and the one that hit the quota
    assert report.intent.sampled <= 1

    capped = MeteredProvider(FakeModelProvider([]), UsageLedger(), max_calls=1)
    report = run_model_check(dataset, capped, intent_sample=3)
    assert report.stopped == "ModelBudgetError"
    assert report.attempted_calls == 1


def sample_report(**changes: object) -> ModelCheckReport:
    report = ModelCheckReport(
        provider="groq",
        model="test-model",
        requests_total=518,
        intent=IntentCheck(sampled=60, agree=57, unusable=1),
        images=[ImageRow("evidence_90", 10, 9, 8, ())],
        attempted_calls=71,
        failed_calls=2,
        input_tokens=50_000,
        output_tokens=6_000,
        max_calls=200,
        keys=(KeyReport("key#1", "exhausted", 40, 38, 1, 30_000, 4_000),),
    )
    for name, value in changes.items():
        setattr(report, name, value)
    return report


def test_usage_lines_state_real_numbers_and_never_invent_a_cost() -> None:
    free = usage_lines(sample_report())
    assert "71 attempted, 69 succeeded, 2 failed (ceiling 200)" in free
    assert "50000 / 6000" in free and "(total 56000" in free
    assert "not estimated" in free and "$" not in free
    assert "key#1: exhausted, 38 ok / 40 tried" in free

    priced = usage_lines(sample_report(cost_usd=Decimal("0.0518"), stopped="ModelBudgetError"))
    assert "$0.0518 total" in priced and "per request" in priced
    assert "Stopped early: ModelBudgetError" in priced


def test_evaluation_section_reports_agreement_without_calling_it_accuracy() -> None:
    text = evaluation_section(sample_report())
    assert "57 agree with the rules (96.6%)" in text
    assert "Agreement is not accuracy" in text
    assert "| evidence_90 | 10 | 9 | 8 | - |" in text


def test_parser_has_the_new_flags_and_check_keys_needs_the_groq_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = cli.build_parser().parse_args(["--model-check", "--model-check-requests", "12"])
    assert args.model_check and args.model_check_requests == 12
    assert cli.build_parser().parse_args(["--check-keys"]).check_keys
    from slam.config import Settings

    assert cli._check_keys(Settings(_env_file=None)) == 2
    assert "SLAM_MODEL_PROVIDER=groq" in capsys.readouterr().out
