"""Strict, deterministic challenge CSV exporter."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from slam.contracts import CaseAnswer

from .validation import validate_answer

OUTPUT_COLUMNS = ("case_id", "deletion_status", "steps_json")


def export_output_csv(
    answers: Iterable[CaseAnswer],
    required_case_ids: Iterable[str],
    path: Path,
) -> None:
    """Validate a complete answer set and atomically write the challenge CSV."""
    required = tuple(required_case_ids)
    if len(required) != len(set(required)):
        raise ValueError("required_case_ids contains duplicates")
    expected = set(required)
    by_id: dict[str, CaseAnswer] = {}
    for answer in answers:
        if answer.case_id in by_id:
            raise ValueError(f"duplicate answer for case_id {answer.case_id}")
        validated = validate_answer(answer)
        by_id[validated.case_id] = validated
    missing = expected - set(by_id)
    extra = set(by_id) - expected
    if missing or extra:
        raise ValueError(
            f"answer set mismatch: missing={sorted(missing)[:10]}, extra={sorted(extra)[:10]}"
        )

    target = Path(path)
    if not target.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {target.parent}")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(OUTPUT_COLUMNS)
            for case_id in sorted(expected):
                answer = by_id[case_id]
                assert answer.deletion_status is not None
                steps = [step.model_dump(mode="json") for step in answer.steps]
                serialized = json.dumps(
                    steps,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                writer.writerow((case_id, answer.deletion_status.value, serialized))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
