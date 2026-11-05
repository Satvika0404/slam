"""Evidence ingestion: the frozen ``ingest`` and ``load_requests`` entry points.

``ingest`` attempts every manifest entry exactly once per source version and
returns one validated ``EvidenceBundle``. Nothing is dropped silently: a source
that cannot be read, recognised or parsed is a ``failed``/``partial`` source with
explicit issues, and a failure is never evidence that nothing is present. No
deletion status, step or policy decision is produced here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from slam.contracts import (
    CONTRACT_VERSION,
    Activity,
    AuditRequest,
    CurrentIdentity,
    EvidenceBundle,
    ExtractionProvenance,
    IdentityChangeEvent,
    IngestionIssue,
    IssueSeverity,
    Observation,
    ParseStatus,
    PolicyRule,
    SourceKind,
    SourceRecord,
)
from slam.runtime.events import emit
from slam.runtime.provider import ModelProvider

from . import normalizer, vocab
from .extraction_cache import ExtractionCache
from .issues import Issue
from .ledger import Ledger
from .manifest import ManifestEntry, load_manifest
from .parsers import image_parser, json_parser, log_parser, pdf_parser, sql_facts, text_parser
from .parsers.base import ParseOutput, SourceContext
from .parsers.image_parser import ImageParser, OcrEngine
from .parsers.registry import Parser, detect, hinted_kind
from .tables import TableResult, load_table

T = TypeVar("T")

INGESTION_VERSION = "1.0.0"
_STATUS = {
    "parsed": ParseStatus.PARSED,
    "partial": ParseStatus.PARTIAL,
    "failed": ParseStatus.FAILED,
}


class RequestLoadError(RuntimeError):
    """``deletion_requests.csv`` could not be loaded completely; nothing is guessed."""

    def __init__(self, issues: Sequence[IngestionIssue]) -> None:
        super().__init__(f"{len(issues)} problem(s) loading deletion requests")
        self.issues = tuple(issues)


def to_contract_issue(issue: Issue) -> IngestionIssue:
    return IngestionIssue(
        severity=IssueSeverity(issue.severity),
        code=issue.code,
        message=issue.message or issue.code,
        source_id=issue.source_id,
        locator=issue.locator,
    )


def _issues(items: Sequence[Issue]) -> list[IngestionIssue]:
    return [to_contract_issue(i) for i in items]


# -- tabular files ---------------------------------------------------------------


def _table(dataset_dir: Path, name: str) -> tuple[TableResult, list[IngestionIssue]]:
    result = load_table(dataset_dir, name)
    return result, _issues(result.issues)


def _identities(table: TableResult) -> list[CurrentIdentity]:
    out: list[CurrentIdentity] = []
    for row in table.rows:
        v = row.values
        out.append(
            CurrentIdentity(
                user_id=v["user_id"],
                name=v["name"],
                email=v["email"],
                email_normalized=v["email"].strip().lower(),
                phone=v["phone"],
                email_hash=v["email_hash"],
                updated_at=row.times["updated_at"],
                source_id=row.row_id,
            )
        )
    return out


def _identity_changes(table: TableResult) -> list[IdentityChangeEvent]:
    return [
        IdentityChangeEvent(
            audit_id=row.row_id,
            user_id=row.values["user_id"],
            field_name=row.values["field_name"],
            old_value=row.values["old_value"] or None,
            new_value=row.values["new_value"] or None,
            changed_at=row.times["event_time"],
            source_id=row.row_id,
        )
        for row in table.rows
    ]


def _activities(table: TableResult) -> list[Activity]:
    return [
        Activity(
            activity_id=row.row_id,
            activity_type=row.values["event_type"],
            occurred_at=row.times["event_time"],
            system_id=row.values["target_system"] or None,
            resource_id=row.values["resource_id"] or None,
            reported_result=row.values["reported_result"] or None,
            attributes={
                "source_system": row.values["source_system"],
                "target_system": row.values["target_system"],
                "details": row.values["details"],
                "evidence_nature": "claim",
            },
        )
        for row in table.rows
    ]


def _rules(table: TableResult) -> list[PolicyRule]:
    return [
        PolicyRule(
            rule_id=row.row_id,
            category=row.values["data_category"],
            required_action=row.values["required_action"],
            condition=row.values["condition"] or None,
        )
        for row in table.rows
    ]


def _build_rows(
    table: TableResult, build: Callable[[], list[T]], problems: list[IngestionIssue]
) -> list[T]:
    """Build contract rows; a validation failure is reported, never swallowed."""
    try:
        return build()
    except ValidationError as exc:
        problems.append(
            IngestionIssue(
                severity=IssueSeverity.ERROR,
                code="TABLE_ROW_INVALID",
                message=(
                    f"{table.name}: a row failed contract validation ({exc.error_count()} error(s))"
                ),
                source_id=table.name,
            )
        )
        return []


def load_requests(dataset_dir: Path) -> tuple[AuditRequest, ...]:
    """Load every audit request, in file order. Raises rather than dropping a row."""
    table, problems = _table(Path(dataset_dir), "deletion_requests")
    requests: list[AuditRequest] = []
    for row in table.rows:
        v = row.values
        try:
            requests.append(
                AuditRequest(
                    case_id=v["case_id"],
                    email=v["email"],
                    requested_at=row.times["requested_at"],
                    reported_status=v["reported_status"],
                    reported_at=row.times["reported_at"],
                    audit_at=row.times["audit_at"],
                    request_text=v["request_text"],
                )
            )
        except ValidationError:
            problems.append(
                IngestionIssue(
                    severity=IssueSeverity.ERROR,
                    code="REQUEST_INVALID",
                    message="a request row failed contract validation",
                    source_id=v["case_id"],
                    locator=f"deletion_requests.csv:{row.line_start}",
                )
            )
    if table.fatal or any(i.severity is IssueSeverity.ERROR for i in problems):
        raise RequestLoadError([i for i in problems if i.severity is IssueSeverity.ERROR])
    return tuple(requests)


# -- evidence sources --------------------------------------------------------------


def _fingerprint(provider: ModelProvider | None) -> str:
    """Identity of the whole pipeline: any change here must re-process every source."""
    material = {
        "ingestion": INGESTION_VERSION,
        "contract": CONTRACT_VERSION,
        "normalizer": normalizer.NORMALIZER_VERSION,
        "parsers": {
            "json": json_parser.PARSER_VERSION,
            "log": log_parser.PARSER_VERSION,
            "text": text_parser.PARSER_VERSION,
            "pdf": pdf_parser.PARSER_VERSION,
            "sql": sql_facts.PARSER_VERSION,
            "image": image_parser.PARSER_VERSION,
        },
        "image": {
            "prompt": image_parser.PROMPT_VERSION,
            "schema": image_parser.SCHEMA_VERSION,
            "ocr_scale": image_parser.OCR_SCALE,
            "min_confidence": image_parser.MIN_MEAN_CONFIDENCE,
            "provider": provider.name if provider else None,
            "model": provider.model if provider else None,
        },
        "vocab": hashlib.sha256(
            json.dumps([vocab.RESOURCE_PREFIXES, vocab.COLLECTIONS], sort_keys=True).encode()
        ).hexdigest(),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _provenance_of(output: ParseOutput, sha256: str) -> ExtractionProvenance:
    model: Mapping[str, Any] = next(
        (f.provenance for f in output.facts if f.provenance.get("model")), {}
    )
    return ExtractionProvenance(
        parser_name=output.parser_name,
        parser_version=output.parser_version,
        source_sha256=sha256,
        model_provider=model.get("model_provider"),
        model=model.get("model"),
        request_id=model.get("request_id"),
        prompt_version=model.get("prompt_version"),
        input_tokens=model.get("input_tokens"),
        output_tokens=model.get("output_tokens"),
        latency_ms=model.get("latency_ms"),
    )


def _process(
    entry: ManifestEntry, parsers: Mapping[SourceKind, Parser]
) -> tuple[SourceRecord, list[Observation], list[IngestionIssue]]:
    """Read, detect, parse and normalize one source. Never raises for bad content."""
    issues: list[Issue] = []
    try:
        data = entry.path.read_bytes()
    except OSError as exc:
        issues.append(
            Issue(
                "SOURCE_UNREADABLE",
                "error",
                f"cannot read file ({type(exc).__name__})",
                entry.file_id,
            )
        )
        data = b""
    sha = hashlib.sha256(data).hexdigest() if data else entry.sha256
    if data and sha != entry.sha256:
        issues.append(
            Issue(
                "SOURCE_CHANGED_DURING_READ",
                "warning",
                "file content changed after it was hashed; the parsed bytes were hashed instead",
                entry.file_id,
            )
        )

    ctx = SourceContext(entry.file_id, entry.origin, entry.captured_at, entry.rel_path, sha)
    detection = detect(data, entry.rel_path, entry.file_id) if data else None
    if detection is not None:
        issues.extend(detection.issues)
    kind = detection.kind if detection and detection.kind else hinted_kind(entry.rel_path)

    observations: list[Observation] = []
    status: ParseStatus = ParseStatus.FAILED
    extraction = ExtractionProvenance(parser_name="none", parser_version="0", source_sha256=sha)
    recognised = detection is not None and detection.kind is not None
    if not data and not any(i.code == "SOURCE_UNREADABLE" for i in issues):
        issues.append(
            Issue("SOURCE_EMPTY", "error", "file is empty; nothing was read", entry.file_id)
        )
    parser = parsers.get(kind) if recognised else None
    if recognised and parser is None:
        issues.append(
            Issue("PARSER_MISSING", "error", f"no parser for {kind.value}", entry.file_id)
        )
    if parser is not None:
        try:
            output = parser(ctx, data)
            observations, norm_issues = normalizer.normalize(ctx, kind, output)
        except Exception as exc:  # a parser bug must fail this source, not the whole run
            issues.append(
                Issue(
                    "PARSER_CRASHED",
                    "error",
                    f"{type(exc).__name__} while parsing; source treated as failed, not empty",
                    entry.file_id,
                )
            )
            observations = []
        else:
            issues.extend(output.issues)
            issues.extend(norm_issues)
            status = _STATUS[output.status]
            extraction = _provenance_of(output, sha)

    record = SourceRecord(
        source_id=entry.file_id,
        kind=kind,
        origin=entry.origin,
        path=entry.rel_path,
        captured_at=entry.captured_at,
        sha256=sha if len(sha) == 64 else entry.sha256,
        parse_status=status,
        extraction=extraction,
    )
    return record, observations, _issues(issues)


def ingest(
    dataset_dir: Path,
    *,
    cache_dir: Path | None = None,
    provider: ModelProvider | None = None,
) -> EvidenceBundle:
    """Ingest every participant source into one ``EvidenceBundle`` (frozen contract signature)."""
    return ingest_with_ocr(dataset_dir, cache_dir=cache_dir, provider=provider)


def ingest_with_ocr(
    dataset_dir: Path,
    *,
    cache_dir: Path | None = None,
    provider: ModelProvider | None = None,
    ocr: OcrEngine | None = None,
) -> EvidenceBundle:
    """``ingest`` with an injectable OCR engine (tests and alternative engines)."""
    root = Path(dataset_dir)
    problems: list[IngestionIssue] = []

    manifest = load_manifest(root)
    problems.extend(_issues(manifest.issues))

    identities_t, p = _table(root, "user_identities")
    problems.extend(p)
    audit_t, p = _table(root, "user_audit_log")
    problems.extend(p)
    activity_t, p = _table(root, "system_activity")
    problems.extend(p)
    rules_t, p = _table(root, "deletion_rules")
    problems.extend(p)
    identities = _build_rows(identities_t, lambda: _identities(identities_t), problems)
    changes = _build_rows(audit_t, lambda: _identity_changes(audit_t), problems)
    activities = _build_rows(activity_t, lambda: _activities(activity_t), problems)
    rules = _build_rows(rules_t, lambda: _rules(rules_t), problems)

    cache = ExtractionCache(cache_dir)
    settings: dict[str, Any] = {}
    parsers: dict[SourceKind, Parser] = {
        SourceKind.JSON: json_parser.parse_json,
        SourceKind.LOG: log_parser.parse_log,
        SourceKind.TEXT: text_parser.parse_text,
        SourceKind.PDF: pdf_parser.parse_pdf,
        SourceKind.SQL: sql_facts.parse_sql,
        SourceKind.IMAGE: ImageParser(ocr=ocr, provider=provider, cache=cache, settings=settings),
    }
    fingerprint = _fingerprint(provider)
    ledger = Ledger(None if cache_dir is None else Path(cache_dir) / "ledger.sqlite")
    sources: list[SourceRecord] = []
    observations: list[Observation] = []
    try:
        for position, entry in enumerate(manifest.entries):
            stored = ledger.read_source(entry.file_id, entry.sha256, fingerprint)
            if stored is None:
                record, found, source_issues = _process(entry, parsers)
                ledger.write_source(record, fingerprint, position, found, source_issues)
            else:
                record, found, source_issues = stored
            sources.append(record)
            observations.extend(found)
            problems.extend(source_issues)
            emit(
                "source.completed",
                source=record.model_dump(mode="json"),
                observations=len(found),
                issues=len(source_issues),
                cache_hit=stored is not None,
                completed=position + 1,
                total=len(manifest.entries),
            )
    finally:
        ledger.close()

    return EvidenceBundle(
        sources=tuple(sources),
        current_identities=tuple(identities),
        identity_changes=tuple(changes),
        activities=tuple(activities),
        observations=tuple(observations),
        policy_rules=tuple(rules),
        issues=tuple(problems),
    )
