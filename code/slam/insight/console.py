"""One-command console: build whatever is missing, then serve the live dashboard.

``python code/main.py --dataset dataset --console`` does, in order, only the steps that are needed:

1. ``dashboard/build_data.py`` when ``dashboard_data.json`` is missing (activity statistics and the
   system graph topology);
2. one audit of the 518 cases, kept in memory for live runs;
3. the stored insight data when ``insight_data.json`` is missing. It is written without a model, so
   nothing is spent on a first start. Run ``--insight`` once to store model-written explanations;
4. ``dashboard/build_page.py``, always, because it takes a second and keeps the page current.

Then it serves the page and the live analysis (see ``server``).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from slam.config import Settings
from slam.insight import build


def _run_script(script: Path, say: Callable[[str], None]) -> None:
    say(f"running {script.name}")
    done = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-5:]
        raise RuntimeError(f"{script.name} failed:\n" + "\n".join(tail))


def prepare_console(
    dataset_dir: Path,
    dashboard_dir: Path,
    settings: Settings,
    *,
    cache_path: Path,
    output_csv: Path,
    refresh: bool = False,
    say: Callable[[str], None] = print,
) -> build.Prepared:
    """Make sure every file the page needs exists, and return the audit for live runs."""

    topology = dashboard_dir / "dashboard_data.json"
    if refresh or not topology.is_file():
        _run_script(dashboard_dir / "build_data.py", say)

    say("auditing the 518 cases once (about half a minute)")
    prep = build.prepare(dataset_dir, topology)

    stored = dashboard_dir / "insight_data.json"
    if refresh or not stored.is_file():
        say("building the stored insight data without a model")
        analysis = build.analyse(
            prep,
            settings=settings,
            provider=None,
            llm_cases=0,
            cache_path=cache_path,
            output_csv=output_csv,
        )
        stored.write_text(build.to_json(analysis.data), encoding="utf-8")

    _run_script(dashboard_dir / "build_page.py", say)
    return prep
