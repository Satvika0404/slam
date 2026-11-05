"""Deterministic ``output.csv`` writer."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from slam.contracts import CaseAnswer, DeletionStatus

COLUMNS = ("case_id", "deletion_status", "steps_json")


class ExportError(ValueError):
    """The answers cannot be exported without inventing or dropping a case."""


def steps_json(answer: CaseAnswer) -> str:
    return json.dumps(
        [
            {
                "step_no": step.step_no,
                "phase": step.phase.value,
                "system_id": step.system_id,
                "resource_id": step.resource_id,
                "operation": step.operation.value,
                "state": step.state.value,
                "evidence_id": step.evidence_id,
            }
            for step in answer.steps
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def export_output_csv(
    answers: Iterable[CaseAnswer], required_case_ids: Iterable[str], path: Path
) -> None:
    """Write exactly one row per required case, sorted by case id, or raise."""

    required = list(required_case_ids)
    if len(set(required)) != len(required):
        raise ExportError("required_case_ids contains duplicates")
    by_id: dict[str, CaseAnswer] = {}
    for answer in answers:
        if answer.case_id in by_id:
            raise ExportError(f"duplicate answer for {answer.case_id}")
        by_id[answer.case_id] = answer
    missing = sorted(set(required) - set(by_id))
    extra = sorted(set(by_id) - set(required))
    if len(set(required)) != len(required) or missing or extra:
        raise ExportError(f"answer set mismatch: missing={missing[:5]} extra={extra[:5]}")
    rows = []
    for case_id in sorted(required):
        answer = by_id[case_id]
        if answer.deletion_status is None or not answer.ready_for_export:
            raise ExportError(
                f"blocked answer: {case_id} has no supported answer: {answer.blocking_issues}"
            )
        not_applicable = answer.deletion_status is DeletionStatus.NOT_APPLICABLE
        body = "[]" if not_applicable else steps_json(answer)
        rows.append((case_id, answer.deletion_status.value, body))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
