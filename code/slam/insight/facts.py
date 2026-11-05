"""Per-case facts for the insight layer.

Two strictly separated halves:

* **Labels** come from the deterministic audit (``CaseAnswer``): did the deletion fail, and how.
* **Features** come only from what the deletion workflow *claimed* (request metadata, the
  system-activity stream, which evidence exists). They never read a resource state, a finding or a
  step, so a model trained on them cannot simply copy the audit verdict out of its inputs.

Nothing here decides a status or a step. It only describes what the audit already decided.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from slam.contracts import (
    _OPERATION_RULES,
    Activity,
    DeletionStatus,
    EvidenceBundle,
    Operation,
    Phase,
    Step,
)
from slam.pipeline import AuditedCase
from slam.reconstruction.graph import classify_activity

FAILURE_BY_FINDING: dict[Operation, str] = {
    Operation.REPORT_REMAINING_RECORD: "REMAINING_RECORD",
    Operation.REPORT_EXPOSED_PII: "EXPOSED_PII",
    Operation.REPORT_ACTIVE_DATA_FLOW: "ACTIVE_DATA_FLOW",
    Operation.REPORT_RESTORE_RISK: "RESTORE_RISK",
}
FAILURE_TYPES: tuple[str, ...] = tuple(FAILURE_BY_FINDING.values())

_TREATMENT_TOKENS = frozenset({"DELETE", "ANONYMIZE", "REDACT"})
_MITIGATION_TOKENS = frozenset({"CHECK", "DISABLE", "BLOCK"})
_RESULTS = ("SUCCESS", "FAILED", "PARTIAL")
_SOURCE_KINDS = ("sql", "json", "log", "pdf", "image", "text")

FEATURES: tuple[str, ...] = (
    "reported_complete",
    "reported_partial",
    "reported_not_started",
    "email_is_historical",
    "identity_changes",
    "acts_linked",
    "acts_success",
    "acts_failed",
    "acts_partial",
    "treat_total",
    "treat_success",
    "treat_failed",
    "treat_partial",
    "copy_total",
    "copy_restore",
    "copy_after_treatment",
    "mitigation_total",
    "mitigation_not_success",
    "systems_touched",
    *(f"src_{kind}" for kind in _SOURCE_KINDS),
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One FINDING step of the audit answer, with the policy category of its resource."""

    step_no: int
    operation: str
    failure_type: str
    system_id: str
    resource_id: str
    category: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class CaseFacts:
    case_id: str
    cohort: str  # "evaluation" (the 518) or "sample" (the 32 public cases, validation only)
    status: str
    reported_status: str
    audit_at: datetime
    findings: tuple[Finding, ...]
    steps: tuple[Step, ...]
    features: tuple[float, ...]
    not_certified_because: tuple[str, ...]

    @property
    def is_audited(self) -> bool:
        """COMPLETE or INCOMPLETE; a non-deletion request has nothing to predict."""

        return self.status in {DeletionStatus.COMPLETE.value, DeletionStatus.INCOMPLETE.value}

    @property
    def failed(self) -> bool:
        return self.status == DeletionStatus.INCOMPLETE.value

    @property
    def failure_types(self) -> frozenset[str]:
        return frozenset(item.failure_type for item in self.findings)

    @property
    def violating_systems(self) -> tuple[str, ...]:
        return tuple(sorted({item.system_id for item in self.findings}))

    @property
    def signature(self) -> frozenset[str]:
        """The failure pattern: which policy categories failed, and how."""

        return frozenset(f"{item.category}:{item.failure_type}" for item in self.findings)


def _family(activity_type: str) -> str:
    tokens = {token for token in re.split(r"[^A-Z0-9]+", activity_type.upper()) if token}
    if tokens & _TREATMENT_TOKENS:
        return "treatment"
    if tokens & _MITIGATION_TOKENS:
        return "mitigation"
    kind = classify_activity(activity_type)
    if kind == "restore":
        return "restore"
    return "copy" if kind == "flow" else "other"


def _claim_features(item: AuditedCase, index: _Index) -> tuple[float, ...]:
    request, context = item.request, item.context
    activities = sorted(
        (
            index.activities[key]
            for key in context.evidence_captured_at
            if key in index.activities
        ),
        key=lambda a: (a.occurred_at, a.activity_id),
    )
    results = Counter((a.reported_result or "").upper() for a in activities)
    families = [(_family(a.activity_type), a) for a in activities]

    def count(family: str, result: str | None = None) -> float:
        return float(
            sum(
                1
                for fam, act in families
                if fam == family
                and (result is None or (act.reported_result or "").upper() == result)
            )
        )

    treatment = [a for fam, a in families if fam == "treatment"]
    first_treatment = treatment[0].occurred_at if treatment else None
    copies_after = (
        sum(
            1
            for fam, a in families
            if fam in {"copy", "restore"} and a.occurred_at > first_treatment
        )
        if first_treatment is not None
        else 0
    )
    mitigation = [a for fam, a in families if fam == "mitigation"]

    subject = context.subject_id
    current = index.identity.get(subject) if subject else None
    changes = index.change_count.get(subject, 0) if subject else 0
    historical = current is not None and request.email.strip().casefold() != current.casefold()

    kinds = Counter(
        index.source_kind[key] for key in context.evidence_captured_at if key in index.source_kind
    )
    reported = request.reported_status.upper()
    values: dict[str, float] = {
        "reported_complete": float(reported == "COMPLETE"),
        "reported_partial": float(reported == "PARTIALLY_COMPLETE"),
        "reported_not_started": float(reported == "NOT_STARTED"),
        "email_is_historical": float(historical),
        "identity_changes": float(changes),
        "acts_linked": float(len(activities)),
        "acts_success": float(results["SUCCESS"]),
        "acts_failed": float(results["FAILED"]),
        "acts_partial": float(results["PARTIAL"]),
        "treat_total": count("treatment"),
        "treat_success": count("treatment", "SUCCESS"),
        "treat_failed": count("treatment", "FAILED"),
        "treat_partial": count("treatment", "PARTIAL"),
        "copy_total": count("copy") + count("restore"),
        "copy_restore": count("restore"),
        "copy_after_treatment": float(copies_after),
        "mitigation_total": float(len(mitigation)),
        "mitigation_not_success": float(
            sum(1 for a in mitigation if (a.reported_result or "").upper() != "SUCCESS")
        ),
        "systems_touched": float(len({a.system_id for a in activities if a.system_id})),
        **{f"src_{kind}": float(kinds[kind]) for kind in _SOURCE_KINDS},
    }
    return tuple(values[name] for name in FEATURES)


@dataclass(frozen=True, slots=True)
class _Index:
    activities: dict[str, Activity]
    source_kind: dict[str, str]
    identity: dict[str, str]
    change_count: dict[str, int]


def _index(bundle: EvidenceBundle) -> _Index:
    return _Index(
        activities={a.activity_id: a for a in bundle.activities},
        source_kind={s.source_id: s.kind.value for s in bundle.sources},
        identity={i.user_id: i.email for i in bundle.current_identities},
        change_count=dict(Counter(change.user_id for change in bundle.identity_changes)),
    )


def _findings(item: AuditedCase) -> tuple[Finding, ...]:
    category = {(s.system_id, s.resource_id): s.category for s in item.context.resource_states}
    found = []
    for step in item.answer.steps:
        if step.phase is Phase.FINDING:
            found.append(
                Finding(
                    step_no=step.step_no,
                    operation=step.operation.value,
                    failure_type=FAILURE_BY_FINDING[step.operation],
                    system_id=step.system_id,
                    resource_id=step.resource_id,
                    category=category.get((step.system_id, step.resource_id), "UNKNOWN"),
                    evidence_id=step.evidence_id,
                )
            )
    return tuple(found)


def extract_facts(
    audited: Sequence[AuditedCase], bundle: EvidenceBundle, *, cohort: str
) -> list[CaseFacts]:
    """Facts for every answered case, in case-id order (deterministic)."""

    index = _index(bundle)
    facts = []
    for item in sorted(audited, key=lambda a: a.request.case_id):
        status = item.answer.deletion_status
        if status is None:
            continue
        facts.append(
            CaseFacts(
                case_id=item.request.case_id,
                cohort=cohort,
                status=status.value,
                reported_status=item.request.reported_status.upper(),
                audit_at=item.request.audit_at,
                findings=_findings(item),
                steps=item.answer.steps,
                features=_claim_features(item, index),
                not_certified_because=tuple(item.answer.trace.get("not_certified_because", ())),
            )
        )
    return facts


def retention_lost(facts: CaseFacts, removed: frozenset[str]) -> bool:
    """Does deleting these systems destroy a record that policy requires to be retained?"""

    return any(
        step.system_id in removed and step.operation is Operation.VERIFY_RECORD_PRESENT
        for step in facts.steps
    )


_KEEP_AFTER_DELETE = frozenset(
    {
        Operation.VERIFY_RECORD_PRESENT,
        Operation.VERIFY_DATA_FLOW_DISABLED,
        Operation.VERIFY_RESTORE_BLOCKED,
    }
)


def apply_deletion(facts: CaseFacts, removed: frozenset[str]) -> CaseFacts:
    """What this case's answer becomes if every record in the ``removed`` systems is deleted.

    A what-if, never written to ``output.csv``. Findings and remediation at a removed system are
    resolved, its verification steps become "record absent" (retained-record, flow and restore
    checks stay as they are), and a case with nothing left to fix is COMPLETE with verification
    steps only. Losing a record that policy requires to be retained makes the case INCOMPLETE:
    a deletion is complete only while every required retained record remains available.
    """

    if not removed or facts.status == DeletionStatus.NOT_APPLICABLE.value:
        return facts
    lost = retention_lost(facts, removed)
    kept: list[Step] = []
    for step in facts.steps:
        if step.system_id not in removed:
            kept.append(step)
        elif step.phase is Phase.VERIFICATION:
            kept.append(
                step
                if step.operation in _KEEP_AFTER_DELETE
                else step.model_copy(
                    update={
                        "operation": Operation.VERIFY_RECORD_ABSENT,
                        "state": _OPERATION_RULES[Operation.VERIFY_RECORD_ABSENT][1],
                    }
                )
            )
    findings = tuple(f for f in facts.findings if f.system_id not in removed)
    status = facts.status
    unresolved = findings or facts.not_certified_because
    if status == DeletionStatus.INCOMPLETE.value and not unresolved:
        status = DeletionStatus.COMPLETE.value
    if lost:
        status = DeletionStatus.INCOMPLETE.value
    if status == DeletionStatus.COMPLETE.value:
        kept = [s for s in kept if s.phase is Phase.VERIFICATION]
    steps = tuple(s.model_copy(update={"step_no": n}) for n, s in enumerate(kept, 1))
    return replace(facts, status=status, findings=findings, steps=steps)
