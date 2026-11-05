"""Validation gates for policy answers and their participant-visible citations."""

from __future__ import annotations

from collections.abc import Collection

from pydantic import ValidationError

from slam.contracts import CaseAnswer, DeletionStatus, Operation, Phase

_VERIFY_FOR = {
    Operation.DELETE_RECORD: Operation.VERIFY_RECORD_ABSENT,
    Operation.REDACT_RECORD: Operation.VERIFY_RECORD_REDACTED,
    Operation.ANONYMIZE_RECORD: Operation.VERIFY_RECORD_ANONYMIZED,
    Operation.DISABLE_DATA_FLOW: Operation.VERIFY_DATA_FLOW_DISABLED,
    Operation.BLOCK_RESTORE: Operation.VERIFY_RESTORE_BLOCKED,
}


class PlanningValidationError(ValueError):
    """Raised when an answer is unsafe or malformed for export."""


def validate_answer(
    answer: CaseAnswer,
    *,
    eligible_evidence_ids: Collection[str] | None = None,
) -> CaseAnswer:
    """Validate output semantics without making a policy decision."""
    try:
        validated = CaseAnswer.model_validate(answer.model_dump(mode="python"))
    except ValidationError as exc:
        raise PlanningValidationError(str(exc)) from exc

    if not validated.ready_for_export:
        raise PlanningValidationError("blocked answer cannot be exported")
    if validated.deletion_status is None:
        raise PlanningValidationError("export-ready answer requires a deletion status")
    if validated.deletion_status is DeletionStatus.NOT_APPLICABLE:
        if validated.steps:
            raise PlanningValidationError("NOT_APPLICABLE answer must not contain steps")
        return validated

    allowed = set(eligible_evidence_ids) if eligible_evidence_ids is not None else None
    findings = [step for step in validated.steps if step.phase is Phase.FINDING]
    remediations = [step for step in validated.steps if step.phase is Phase.REMEDIATION]
    verifications = [step for step in validated.steps if step.phase is Phase.VERIFICATION]
    if validated.deletion_status is DeletionStatus.COMPLETE and (findings or remediations):
        raise PlanningValidationError("COMPLETE answers may contain verification steps only")
    if validated.deletion_status is DeletionStatus.COMPLETE and not verifications:
        raise PlanningValidationError("COMPLETE answers require evidence-backed verification")
    if validated.deletion_status is DeletionStatus.INCOMPLETE and not findings:
        raise PlanningValidationError("INCOMPLETE answers require at least one finding")
    if validated.deletion_status is DeletionStatus.INCOMPLETE and not remediations:
        raise PlanningValidationError("INCOMPLETE answers require a remediation plan")

    for step in validated.steps:
        is_future = (
            validated.deletion_status is DeletionStatus.INCOMPLETE
            and step.phase is not Phase.FINDING
        )
        if is_future:
            if step.evidence_id:
                raise PlanningValidationError("future steps must have an empty evidence_id")
            continue
        if not step.evidence_id:
            raise PlanningValidationError(
                "findings and completed verifications need a visible evidence_id"
            )
        if allowed is not None and step.evidence_id not in allowed:
            raise PlanningValidationError(f"ineligible evidence_id: {step.evidence_id}")

    for remediation in remediations:
        verify_operation = _VERIFY_FOR[remediation.operation]
        if not any(
            step.system_id == remediation.system_id
            and step.resource_id == remediation.resource_id
            and step.operation is verify_operation
            for step in verifications
        ):
            raise PlanningValidationError(
                f"missing verification for {remediation.system_id}/{remediation.resource_id}"
            )
    if (
        validated.deletion_status is DeletionStatus.INCOMPLETE
        and remediations
        and not verifications
    ):
        raise PlanningValidationError("INCOMPLETE answers require post-remediation verification")
    return validated
