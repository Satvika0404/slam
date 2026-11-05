"""Optional model cross-check: measure the model paths without letting them decide anything.

The pipeline answers every case without a model. Its two model fallbacks (request intent, and
screenshots OCR cannot read) never fire on this dataset, so a normal run makes zero model calls.
This pass calls the *same* production fallbacks on purpose and compares them with the rules and
with OCR, so the usage report reflects a real, measured model run. Nothing here feeds
``output.csv``.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image
from slam.contracts import RequestIntent
from slam.ingestion.api import load_requests
from slam.ingestion.extraction_cache import ExtractionCache
from slam.ingestion.parsers.base import ParseOutput, SourceContext
from slam.ingestion.parsers.image_parser import ImageParser, OcrResult, TesseractOcr
from slam.reconstruction.request_intent import ask_provider_for_intent, interpret_request
from slam.runtime.key_pool import KeyReport
from slam.runtime.metering import MeteredProvider

IMAGE_FOLDER = "evidence/images/"


class _ModelOnlyOcr:
    """Reports itself unavailable so the parser must ask the model about the whole image."""

    def read(self, image: Image.Image) -> OcrResult:
        del image
        return OcrResult(available=False, error="cross-check: ask the model directly")


@dataclass(frozen=True, slots=True)
class IntentRow:
    case_id: str
    rules: str
    model: str
    basis: str


@dataclass(slots=True)
class IntentCheck:
    sampled: int = 0
    agree: int = 0
    unusable: int = 0  # the model failed, was ungrounded or answered UNCLEAR
    disagreements: list[IntentRow] = field(default_factory=list)

    @property
    def compared(self) -> int:
        return self.sampled - self.unusable


@dataclass(frozen=True, slots=True)
class ImageRow:
    file_id: str
    ocr_ids: int
    model_ids: int
    shared: int
    model_issues: tuple[str, ...]


@dataclass(slots=True)
class ModelCheckReport:
    provider: str
    model: str
    requests_total: int
    intent: IntentCheck = field(default_factory=IntentCheck)
    images: list[ImageRow] = field(default_factory=list)
    stopped: str | None = None
    attempted_calls: int = 0
    failed_calls: int = 0
    unknown_usage_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    max_calls: int = 0
    cost_usd: Decimal | None = None
    keys: tuple[KeyReport, ...] = ()

    @property
    def succeeded_calls(self) -> int:
        return self.attempted_calls - self.failed_calls

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _identifiers(output: ParseOutput) -> set[str]:
    found: set[str] = set()
    for fact in output.facts:
        for key in ("emails", "phones", "user_ids"):
            found.update(str(v).strip().lower() for v in fact.data.get(key, ()) if v)
        if fact.resource_id:
            found.add(fact.resource_id.strip().lower())
    return found


def _sample_requests(
    rows: list[tuple[str, str, RequestIntent]], limit: int
) -> list[tuple[str, str, RequestIntent]]:
    """Every request the rules did not call a deletion, then evenly spaced deletions."""

    if limit <= 0:
        return []
    rows = sorted(rows)
    rest = [row for row in rows if row[2] is RequestIntent.DELETION]
    chosen = [row for row in rows if row[2] is not RequestIntent.DELETION][:limit]
    room = limit - len(chosen)
    if room > 0 and rest:
        step = max(1, len(rest) // room)
        chosen += rest[::step][:room]
    return sorted(chosen)


def _check_intent(
    dataset: Path, provider: MeteredProvider, limit: int, report: ModelCheckReport
) -> None:
    rules = [
        (r.case_id, r.request_text, interpret_request(r.request_text, None).intent)
        for r in load_requests(dataset)
    ]
    report.requests_total = len(rules)
    for case_id, text, expected in _sample_requests(rules, limit):
        if provider.fatal:
            return
        got = ask_provider_for_intent(text, provider)
        report.intent.sampled += 1
        if got.intent is RequestIntent.UNCLEAR:
            report.intent.unusable += 1
        elif got.intent is expected:
            report.intent.agree += 1
        else:
            report.intent.disagreements.append(
                IntentRow(case_id, expected.value, got.intent.value, got.basis)
            )


def _check_images(dataset: Path, provider: MeteredProvider, report: ModelCheckReport) -> None:
    with (dataset / "evidence_files.csv").open(newline="", encoding="utf-8-sig") as handle:
        manifest = [r for r in csv.DictReader(handle) if r["file_path"].startswith(IMAGE_FOLDER)]
    ocr_parser = ImageParser(ocr=TesseractOcr(), provider=None, cache=ExtractionCache())
    model_parser = ImageParser(ocr=_ModelOnlyOcr(), provider=provider, cache=ExtractionCache())
    for row in sorted(manifest, key=lambda r: r["file_id"]):
        if provider.fatal:
            return
        data = (dataset / row["file_path"]).read_bytes()
        ctx = SourceContext(
            source_id=row["file_id"],
            origin=row["origin"],
            captured_at=datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00")),
            rel_path=row["file_path"],
            sha256=hashlib.sha256(data).hexdigest(),
        )
        from_ocr = _identifiers(ocr_parser(ctx, data))
        modelled = model_parser(ctx, data)
        from_model = _identifiers(modelled)
        report.images.append(
            ImageRow(
                file_id=row["file_id"],
                ocr_ids=len(from_ocr),
                model_ids=len(from_model),
                shared=len(from_ocr & from_model),
                model_issues=tuple(
                    sorted(i.code for i in modelled.issues if i.code.startswith("IMAGE_MODEL"))
                ),
            )
        )


def run_model_check(
    dataset: Path, provider: MeteredProvider, *, intent_sample: int = 60
) -> ModelCheckReport:
    """Run both cross-checks, stopping at the first fatal error or ceiling."""

    report = ModelCheckReport(provider=provider.name, model=provider.model, requests_total=0)
    _check_images(dataset, provider, report)
    _check_intent(dataset, provider, intent_sample, report)
    report.stopped = provider.fatal
    report.attempted_calls = provider.attempted_calls
    report.failed_calls = provider.failed_calls
    report.unknown_usage_calls = provider.unknown_usage_calls
    report.input_tokens = provider.input_tokens
    report.output_tokens = provider.output_tokens
    report.max_calls = provider.max_calls
    report.cost_usd = provider.cost_usd
    report.keys = provider.key_reports()
    return report


# -- rendering ------------------------------------------------------------------------------


def _money(value: Decimal) -> str:
    return f"${value:.4f}"


def usage_lines(report: ModelCheckReport) -> str:
    cases = max(report.requests_total, 1)
    calls = max(report.attempted_calls, 1)
    if report.cost_usd is None:
        cost = (
            "- Estimated cost: not estimated (no per-token price was supplied: free tier or "
            "unpriced), so no dollar figure is claimed\n"
        )
    else:
        cost = (
            f"- Estimated cost: {_money(report.cost_usd)} total, "
            f"{_money(report.cost_usd / cases)} per request\n"
        )
    keys = "".join(
        f"  - {k.label}: {k.state}, {k.successes} ok / {k.calls} tried, "
        f"{k.rate_limited} rate-limited, {k.input_tokens} in / {k.output_tokens} out tokens\n"
        for k in report.keys
    )
    stopped = f"- Stopped early: {report.stopped}\n" if report.stopped else ""
    unknown = (
        f"- {report.unknown_usage_calls} call(s) returned no token counts; totals are a lower "
        "bound\n"
        if report.unknown_usage_calls
        else ""
    )
    return (
        "## Optional model cross-check (does not change `output.csv`)\n\n"
        f"- Model provider: `{report.provider}`, model `{report.model}`\n"
        f"- Model calls: {report.attempted_calls} attempted, {report.succeeded_calls} succeeded, "
        f"{report.failed_calls} failed (ceiling {report.max_calls})\n"
        f"- Input / output tokens: {report.input_tokens} / {report.output_tokens} "
        f"(total {report.total_tokens}; average {report.total_tokens / calls:.0f} per call, "
        f"{report.total_tokens / cases:.1f} per request over {cases} requests)\n"
        f"{cost}"
        f"- Per-model totals: `{report.model}` only, the figures above\n"
        f"{stopped}{unknown}"
        "- Per key (labels only, never values):\n"
        f"{keys}"
    )


def evaluation_section(report: ModelCheckReport) -> str:
    intent = report.intent
    rate = f"{intent.agree / intent.compared:.1%}" if intent.compared else "n/a"
    rows = "".join(
        f"| {r.file_id} | {r.ocr_ids} | {r.model_ids} | {r.shared} | "
        f"{', '.join(r.model_issues) or '-'} |\n"
        for r in report.images
    )
    disagreements = "".join(
        f"- {d.case_id}: rules {d.rules}, model {d.model} ({d.basis})\n"
        for d in intent.disagreements
    )
    ocr_total = sum(r.ocr_ids for r in report.images)
    shared_total = sum(r.shared for r in report.images)
    model_total = sum(r.model_ids for r in report.images)
    recall = f"{shared_total / ocr_total:.1%}" if ocr_total else "n/a"
    precision = f"{shared_total / model_total:.1%}" if model_total else "n/a"
    return (
        "## Model cross-check (optional pass, nothing here feeds `output.csv`)\n\n"
        f"Provider `{report.provider}`, model `{report.model}`. The two model fallbacks never "
        "fire on this dataset, so they were called on purpose and compared with the rules and "
        "with OCR. Agreement is not accuracy: HackerRank publishes no answers for these "
        "requests, and neither the rules nor the model is ground truth.\n\n"
        f"**Request intent:** {intent.sampled} requests sampled (every request the rules did not "
        f"call a deletion, then evenly spaced ones); {intent.unusable} had no usable model "
        f"answer; of {intent.compared} compared, {intent.agree} agree with the rules ({rate}).\n"
        f"{disagreements}\n"
        f"**Screenshots:** model read {model_total} identifiers against OCR's {ocr_total}; "
        f"{shared_total} in common (OCR identifiers the model also found: {recall}; "
        f"model identifiers OCR also found: {precision}).\n\n"
        "| file | OCR ids | model ids | shared | model issues |\n|---|---|---|---|---|\n"
        f"{rows}"
    )
