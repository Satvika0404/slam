"""Strict validation helpers for planning answers and their evidence citations."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from pydantic import ValidationError

from slam.contracts import CaseAnswer, DeletionStatus, Phase


class PlanningValidationError(ValueError):
    """Raised when an answer is not safe to pass to a downstream exporter."""


def validate_answer(
    answer: CaseAnswer,
    *,
    eligible_evidence_ids: Collection[str] | None = None,
    evidence_captured_at: dict[str, datetime] | None = None,
    audit_at: datetime | None = None,
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
    if (evidence_captured_at is None) != (audit_at is None):
        raise PlanningValidationError("evidence_captured_at and audit_at must be supplied together")
    for step in validated.steps:
        if step.phase is Phase.FINDING:
            if not step.evidence_id:
                raise PlanningValidationError("findings require an evidence_id")
            if eligible_evidence_ids is not None and step.evidence_id not in evidence_ids:
                raise PlanningValidationError(
                    f"finding cites ineligible evidence_id: {step.evidence_id}"
                )
            _validate_cutoff(step.evidence_id, evidence_captured_at, audit_at)
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
            _validate_cutoff(step.evidence_id, evidence_captured_at, audit_at)
        elif step.phase in (Phase.REMEDIATION, Phase.VERIFICATION) and step.evidence_id:
            raise PlanningValidationError(
                "future remediation and verification steps must have an empty evidence_id"
            )
    return validated


def _validate_cutoff(
    evidence_id: str, captured_at: dict[str, datetime] | None, audit_at: datetime | None
) -> None:
    if captured_at is None or audit_at is None:
        return
    if evidence_id not in captured_at:
        raise PlanningValidationError(f"citation has no capture time: {evidence_id}")
    if captured_at[evidence_id] > audit_at:
        raise PlanningValidationError(f"citation is after audit_at: {evidence_id}")
