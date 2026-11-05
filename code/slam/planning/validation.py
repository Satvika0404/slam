"""Strict validation helpers for planning answers and their evidence citations."""

from __future__ import annotations

from collections.abc import Collection

from pydantic import ValidationError

from slam.contracts import CaseAnswer, DeletionStatus, Phase


class PlanningValidationError(ValueError):
    """Raised when an answer is not safe to pass to a downstream exporter."""


def validate_answer(
    answer: CaseAnswer,
    *,
    eligible_evidence_ids: Collection[str] | None = None,
) -> CaseAnswer:
    """Validate contract invariants plus planning evidence and status rules.

    This validates one answer without making a policy decision. Finding evidence and
    verifications for a completed case must be eligible citations. Future remediation
    and verification steps in an incomplete case must not claim evidence.
    """
    try:
        validated = CaseAnswer.model_validate(answer.model_dump(mode="python"))
    except ValidationError as exc:
        raise PlanningValidationError(str(exc)) from exc

    if validated.ready_for_export and validated.deletion_status is None:
        raise PlanningValidationError("export-ready answer requires a deletion status")

    if validated.deletion_status is DeletionStatus.NOT_APPLICABLE:
        if validated.steps:
            raise PlanningValidationError("NOT_APPLICABLE answer must not contain steps")
        return validated

    evidence_ids = set(eligible_evidence_ids or ())
    for step in validated.steps:
        if step.phase is Phase.FINDING:
            if not step.evidence_id:
                raise PlanningValidationError("findings require an evidence_id")
            if eligible_evidence_ids is not None and step.evidence_id not in evidence_ids:
                raise PlanningValidationError(
                    f"finding cites ineligible evidence_id: {step.evidence_id}"
                )
        elif validated.deletion_status is DeletionStatus.COMPLETE:
            if step.phase is not Phase.VERIFICATION:
                raise PlanningValidationError(
                    "COMPLETE answers may contain verification steps only"
                )
            if not step.evidence_id:
                raise PlanningValidationError("COMPLETE verifications require an evidence_id")
            if eligible_evidence_ids is not None and step.evidence_id not in evidence_ids:
                raise PlanningValidationError(
                    f"verification cites ineligible evidence_id: {step.evidence_id}"
                )
        elif step.phase in (Phase.REMEDIATION, Phase.VERIFICATION) and step.evidence_id:
            raise PlanningValidationError(
                "future remediation and verification steps must have an empty evidence_id"
            )
    return validated
