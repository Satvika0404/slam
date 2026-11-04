import csv
import json

import pytest
from slam.contracts import (
    CaseAnswer,
    DeletionStatus,
    Operation,
    Phase,
    Step,
    StepState,
)
from slam.planning.export import export_output_csv


def valid_answer(case_id: str) -> CaseAnswer:
    return CaseAnswer(
        case_id=case_id,
        deletion_status=DeletionStatus.COMPLETE,
        ready_for_export=True,
        steps=(
            Step(
                step_no=1,
                phase=Phase.VERIFICATION,
                system_id="account",
                resource_id="profile_1",
                operation=Operation.VERIFY_RECORD_ABSENT,
                state=StepState.ABSENT,
                evidence_id="file_1",
            ),
        ),
    )


def test_export_is_sorted_with_exact_columns_and_json_steps(tmp_path):
    output = tmp_path / "output.csv"
    export_output_csv(
        (valid_answer("case_2"), valid_answer("case_1")), ("case_2", "case_1"), output
    )
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        assert tuple(rows[0]) == ("case_id", "deletion_status", "steps_json")
    assert [row["case_id"] for row in rows] == ["case_1", "case_2"]
    assert json.loads(rows[0]["steps_json"])[0]["evidence_id"] == "file_1"


def test_export_rejects_missing_and_duplicate_cases(tmp_path):
    with pytest.raises(ValueError, match="answer set mismatch"):
        export_output_csv((valid_answer("case_1"),), ("case_1", "case_2"), tmp_path / "x.csv")
    with pytest.raises(ValueError, match="duplicate answer"):
        export_output_csv(
            (valid_answer("case_1"), valid_answer("case_1")),
            ("case_1",),
            tmp_path / "x.csv",
        )


def test_export_rejects_unresolved_answers(tmp_path):
    answer = CaseAnswer(case_id="case_1", ready_for_export=False)
    with pytest.raises(ValueError, match="blocked answer"):
        export_output_csv((answer,), ("case_1",), tmp_path / "x.csv")


def test_export_rejects_invalid_expected_case_set(tmp_path):
    answer = valid_answer("case_1")
    with pytest.raises(ValueError, match="required_case_ids contains duplicates"):
        export_output_csv((answer,), ("case_1", "case_1"), tmp_path / "x.csv")
