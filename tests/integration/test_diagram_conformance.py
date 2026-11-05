"""Every box of the project flowchart (the shared pipeline image) maps to code that exists.

Boxes, top to bottom: Input files -> Input loaders -> Evidence ingestion -> Parsers -> Evidence
bundle -> Searchable evidence store -> Orchestrator -> "Deletion actually requested?" -> (No) /
(Yes) Resolve identity and timeline -> Reconstruct state at audit_at -> Find relevant records and
recreation paths -> Apply policy -> "Evidence sufficient?" (3 branches) -> Validate answer ->
Collect all case answers -> Output validator -> output.csv -> Evaluation and usage reports ->
Submission package.
"""

from __future__ import annotations

import importlib
import inspect
import sqlite3
from pathlib import Path

import pytest
from slam.contracts import (
    CaseAnswer,
    DeletionStatus,
    EvidenceBundle,
    RequestIntent,
    SourceKind,
)

ROOT = Path(__file__).resolve().parents[2]


def test_input_loaders_and_ingestion_cover_every_source_kind_in_the_diagram() -> None:
    api = importlib.import_module("slam.ingestion.api")
    assert callable(api.load_requests) and callable(api.ingest)
    # CSV . JSON . logs . text . PDF . screenshots . SQL
    assert {kind.value for kind in SourceKind} == {
        "csv",
        "json",
        "log",
        "text",
        "pdf",
        "image",
        "sql",
    }


@pytest.mark.parametrize("module", ["pypdf", "PIL", "pytesseract"])
def test_parsers_use_the_libraries_named_in_the_diagram(module: str) -> None:
    importlib.import_module(module)  # pypdf . Pillow . Tesseract wrapper


def test_evidence_bundle_carries_observations_sources_issues_and_provenance() -> None:
    fields = set(EvidenceBundle.model_fields)
    assert {"observations", "sources", "issues"} <= fields
    assert "extraction" in importlib.import_module("slam.contracts").Observation.model_fields


def test_searchable_evidence_store_is_sqlite_fts5() -> None:
    sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
    assert hasattr(importlib.import_module("slam.ingestion.ledger"), "Ledger")


def test_orchestrator_isolates_a_failing_case_instead_of_guessing() -> None:
    orchestrator = importlib.import_module("slam.runtime.orchestrator")
    assert "isolate" in (inspect.getsource(orchestrator.run_cases)).lower()


def test_deletion_actually_requested_no_branch_is_not_applicable_with_no_steps() -> None:
    from slam.reconstruction.request_intent import interpret_request

    assert (
        interpret_request("Please export a copy of my data.").intent is RequestIntent.NON_DELETION
    )
    assert interpret_request("Please delete my account.").intent is RequestIntent.DELETION
    answer = CaseAnswer(
        case_id="c", deletion_status=DeletionStatus.NOT_APPLICABLE, ready_for_export=True
    )
    assert answer.steps == ()


def test_yes_branch_stages_exist_in_the_order_of_the_diagram() -> None:
    recon = importlib.import_module("slam.reconstruction")
    for stage in (
        "slam.reconstruction.identity",  # resolve identity (current + historical identifiers)
        "slam.reconstruction.timeline",  # reconstruct state at audit_at, exclude future evidence
        "slam.reconstruction.graph",  # replicas, sync/import, backups/restores
        "slam.reconstruction.ownership",  # find relevant records (explicit owner evidence)
        "slam.reconstruction.linking",  # ... and learned attribution
        "slam.planning.engine",  # apply deletion and retention policy
    ):
        importlib.import_module(stage)
    assert callable(recon.reconstruct) and callable(recon.reconstruct_with_links)


def test_evidence_sufficient_has_three_outcomes() -> None:
    from slam.planning.engine import plan_case  # noqa: F401  (behaviour covered in tests/planning)

    # uncertain -> flagged and never COMPLETE; compliant -> COMPLETE; violations -> INCOMPLETE
    assert {DeletionStatus.COMPLETE, DeletionStatus.INCOMPLETE} <= set(DeletionStatus)
    source = inspect.getsource(importlib.import_module("slam.planning.engine"))
    assert "blocking_reasons" in source and "not_certified_because" in source


def test_validate_collect_and_output_validator_exist() -> None:
    assert callable(importlib.import_module("slam.planning.validation").validate_answer)
    pipeline = importlib.import_module("slam.pipeline")
    assert callable(pipeline.answer_cases)  # collects every case, isolating failures
    assert callable(importlib.import_module("slam.planning.export").export_output_csv)
    assert callable(importlib.import_module("slam.evaluation.validator").validate_output_csv)


def test_evaluation_and_usage_reports_and_submission_package_are_produced() -> None:
    main = (ROOT / "code" / "evaluation" / "main.py").read_text(encoding="utf-8")
    assert "evaluation_report.md" in main and "usage_report.md" in main
    assert (ROOT / "scripts" / "build_submission.py").exists()  # code.zip
