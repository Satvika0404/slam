"""The required evaluation/usage reports are written where the submission rules expect them."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from slam.config import Settings
from slam.pipeline import RunSummary

from evaluation import main as report_main

ROOT = Path(__file__).resolve().parents[2]


def _metrics() -> SimpleNamespace:
    return SimpleNamespace(
        cases=32,
        status_accuracy=0.906,
        exact_case_accuracy=0.344,
        step_precision=0.744,
        step_recall=0.663,
        step_f1=0.701,
        field_accuracy=0.771,
        sequence_accuracy=0.344,
        false_complete_count=0,
    )


@pytest.fixture
def targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    code_dir, mirror_dir = tmp_path / "code" / "evaluation", tmp_path / "evaluation"
    monkeypatch.setattr(report_main, "TARGETS", (code_dir, mirror_dir))
    monkeypatch.setattr("slam.pipeline.evaluate_samples", lambda dataset: (None, _metrics()))
    return code_dir, mirror_dir


def _summary() -> RunSummary:
    return RunSummary(
        cases=518,
        statuses=Counter({"INCOMPLETE": 3, "COMPLETE": 2}),
        seconds=12.5,
        link_groups=["ACTIVITY@system window -5..5 min, 10 pairs, 90% resolved"],
    )


def test_both_reports_are_written_to_the_required_folder_and_mirrored(
    targets: tuple[Path, Path],
) -> None:
    report_main.write_reports(Path("dataset"), _summary(), Settings())

    for folder in targets:
        assert (folder / "evaluation_report.md").is_file()
        assert (folder / "usage_report.md").is_file()
    code_dir, mirror_dir = targets
    for name in ("evaluation_report.md", "usage_report.md"):
        assert (code_dir / name).read_bytes() == (mirror_dir / name).read_bytes()


def test_evaluation_report_has_the_required_sections_and_honest_scope(
    targets: tuple[Path, Path],
) -> None:
    report_main.write_reports(Path("dataset"), _summary(), Settings())
    text = (targets[0] / "evaluation_report.md").read_text(encoding="utf-8")

    for required in (
        "Case-level deletion-status accuracy | 0.906",
        "Field-level accuracy | 0.771",
        "Sequence accuracy | 0.344",
        "## Additional evaluation cases (created by us)",
        "## Failures found and improvements made",
        "ACTIVITY@system window -5..5 min",
    ):
        assert required in text
    # The 518 have no published answers; the report must say so rather than imply a score.
    assert "publishes no answers for the 518" in text


def test_usage_report_states_the_run_it_summarises(targets: tuple[Path, Path]) -> None:
    report_main.write_reports(Path("dataset"), _summary(), Settings())
    produced = (targets[0] / "usage_report.md").read_text(encoding="utf-8")
    assert "Final full-dataset run that produced `output.csv` (518 cases, 12.5 s)" in produced
    assert "Model calls: 0" in produced

    report_main.write_reports(Path("dataset"), _summary(), Settings(), wrote_output=False)
    standalone = (targets[0] / "usage_report.md").read_text(encoding="utf-8")
    assert "Final full-dataset run that produced" not in standalone
    assert "Standalone full-dataset report run" in standalone
    assert "temporary file" in standalone


def test_standalone_entry_point_imports_without_a_preset_python_path() -> None:
    """``python code/evaluation/main.py`` works although the project is not an installed package."""

    result = subprocess.run(
        [sys.executable, str(ROOT / "code" / "evaluation" / "main.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dataset" in result.stdout
