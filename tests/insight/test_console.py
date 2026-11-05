"""The one-command console builds only what is missing and never spends tokens on a first start."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from slam.config import Settings
from slam.insight import console


class _Recorder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.scripts: list[str] = []
        self.analyse_calls: list[dict[str, Any]] = []
        self.prepared = SimpleNamespace(name="audit")

        def run_script(script: Path, say: Any) -> None:
            self.scripts.append(script.name)

        def prepare(dataset: Path, topology: Path) -> Any:
            self.scripts.append("audit")
            return self.prepared

        def analyse(prep: Any, **kwargs: Any) -> Any:
            self.analyse_calls.append(kwargs)
            return SimpleNamespace(data={"cases": []})

        monkeypatch.setattr(console, "_run_script", run_script)
        monkeypatch.setattr(console.build, "prepare", prepare)
        monkeypatch.setattr(console.build, "analyse", analyse)

    def run(self, folder: Path, *, refresh: bool = False) -> Any:
        return console.prepare_console(
            folder / "dataset",
            folder,
            Settings(),
            cache_path=folder / "cache.json",
            output_csv=folder / "output.csv",
            refresh=refresh,
            say=lambda line: None,
        )


def test_a_fresh_checkout_builds_everything_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _Recorder(monkeypatch)
    assert rec.run(tmp_path) is rec.prepared
    assert rec.scripts == ["build_data.py", "audit", "build_page.py"]
    (call,) = rec.analyse_calls
    assert call["provider"] is None and call["llm_cases"] == 0  # a first start spends nothing
    assert (tmp_path / "insight_data.json").is_file()


def test_existing_files_are_reused_and_only_the_page_is_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "dashboard_data.json").write_text("{}", encoding="utf-8")
    stored = tmp_path / "insight_data.json"
    stored.write_text('{"kept": true}', encoding="utf-8")
    rec = _Recorder(monkeypatch)
    rec.run(tmp_path)
    assert rec.scripts == ["audit", "build_page.py"]
    assert rec.analyse_calls == []
    assert stored.read_text(encoding="utf-8") == '{"kept": true}'  # model-written text survives


def test_refresh_rebuilds_the_data_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "dashboard_data.json").write_text("{}", encoding="utf-8")
    (tmp_path / "insight_data.json").write_text("{}", encoding="utf-8")
    rec = _Recorder(monkeypatch)
    rec.run(tmp_path, refresh=True)
    assert rec.scripts == ["build_data.py", "audit", "build_page.py"]
    assert len(rec.analyse_calls) == 1


def test_a_failing_build_script_reports_its_last_lines(tmp_path: Path) -> None:
    script = tmp_path / "boom.py"
    script.write_text("import sys\nprint('x')\nsys.stderr.write('real reason')\nsys.exit(3)\n")
    with pytest.raises(RuntimeError, match="real reason"):
        console._run_script(script, lambda line: None)
