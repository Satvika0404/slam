from __future__ import annotations

import pytest
from pydantic import ValidationError
from slam.contracts import CaseAnswer, DeletionStatus, Operation, Phase, Step, StepState
from slam.planning.validation import PlanningValidationError, validate_answer


def step(
    number: int,
    phase: Phase,
    operation: Operation,
    state: StepState,
    evidence_id: str,
) -> Step:
    return Step(
        step_no=number,
        phase=phase,
        system_id="system-a",
        resource_id="record-a",
        operation=operation,
        state=state,
        evidence_id=evidence_id,
    )


def answer(status: DeletionStatus, *steps: Step) -> CaseAnswer:
    return CaseAnswer(
        case_id="synthetic-case",
        deletion_status=status,
        steps=steps,
        ready_for_export=True,
    )


def test_valid_incomplete_answer_has_grounded_findings_and_future_actions() -> None:
    result = validate_answer(
        answer(
            DeletionStatus.INCOMPLETE,
            step(1, Phase.FINDING, Operation.REPORT_REMAINING_RECORD, StepState.PRESENT, "file-1"),
            step(2, Phase.REMEDIATION, Operation.DELETE_RECORD, StepState.ABSENT, ""),
            step(3, Phase.VERIFICATION, Operation.VERIFY_RECORD_ABSENT, StepState.ABSENT, ""),
        ),
        eligible_evidence_ids={"file-1"},
    )

    assert result.deletion_status is DeletionStatus.INCOMPLETE


def test_not_applicable_requires_no_steps() -> None:
    result = validate_answer(answer(DeletionStatus.NOT_APPLICABLE))
    assert result.steps == ()

    with pytest.raises(ValidationError):
        answer(
            DeletionStatus.NOT_APPLICABLE,
            step(1, Phase.FINDING, Operation.REPORT_REMAINING_RECORD, StepState.PRESENT, "file-1"),
        )


def test_step_rejects_invalid_operation_state_pair() -> None:
    with pytest.raises(ValidationError, match="requires phase"):
        step(1, Phase.REMEDIATION, Operation.DELETE_RECORD, StepState.PRESENT, "")


def test_answer_rejects_nonconsecutive_step_numbers() -> None:
    with pytest.raises(ValidationError, match="consecutive"):
        answer(
            DeletionStatus.INCOMPLETE,
            step(2, Phase.FINDING, Operation.REPORT_REMAINING_RECORD, StepState.PRESENT, "file-1"),
        )


def test_answer_rejects_phase_order_regression() -> None:
    with pytest.raises(ValidationError, match="FINDING, REMEDIATION, VERIFICATION"):
        answer(
            DeletionStatus.INCOMPLETE,
            step(1, Phase.REMEDIATION, Operation.DELETE_RECORD, StepState.ABSENT, ""),
            step(2, Phase.FINDING, Operation.REPORT_REMAINING_RECORD, StepState.PRESENT, "file-1"),
        )


def test_finding_requires_evidence() -> None:
    with pytest.raises(PlanningValidationError, match="findings require"):
        validate_answer(
            answer(
                DeletionStatus.INCOMPLETE,
                step(1, Phase.FINDING, Operation.REPORT_REMAINING_RECORD, StepState.PRESENT, ""),
            )
        )


def test_incomplete_future_steps_must_not_claim_evidence() -> None:
    with pytest.raises(PlanningValidationError, match="future remediation"):
        validate_answer(
            answer(
                DeletionStatus.INCOMPLETE,
                step(1, Phase.REMEDIATION, Operation.DELETE_RECORD, StepState.ABSENT, "file-1"),
            )
        )


def test_complete_answers_only_have_evidence_backed_verifications() -> None:
    result = validate_answer(
        answer(
            DeletionStatus.COMPLETE,
            step(1, Phase.VERIFICATION, Operation.VERIFY_RECORD_ABSENT, StepState.ABSENT, "file-1"),
        ),
        eligible_evidence_ids={"file-1"},
    )
    assert result.deletion_status is DeletionStatus.COMPLETE

    with pytest.raises(PlanningValidationError, match="verifications require"):
        validate_answer(
            answer(
                DeletionStatus.COMPLETE,
                step(1, Phase.VERIFICATION, Operation.VERIFY_RECORD_ABSENT, StepState.ABSENT, ""),
            )
        )


def test_ineligible_citation_is_rejected_when_eligibility_set_is_supplied() -> None:
    with pytest.raises(PlanningValidationError, match="ineligible evidence_id"):
        validate_answer(
            answer(
                DeletionStatus.INCOMPLETE,
                step(
                    1,
                    Phase.FINDING,
                    Operation.REPORT_REMAINING_RECORD,
                    StepState.PRESENT,
                    "future-file",
                ),
            ),
            eligible_evidence_ids={"eligible-file"},
        )


def test_step_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Step.model_validate(
            {
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "system-a",
                "resource_id": "record-a",
                "operation": "REPORT_REMAINING_RECORD",
                "state": "PRESENT",
                "evidence_id": "file-1",
                "unexpected": "not allowed",
            }
        )
