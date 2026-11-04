"""Policy decision and ordered step generation (the "apply policy" stage of the pipeline).

``plan_case(context, bundle)`` turns a reconstructed ``CaseContext`` into a ``CaseAnswer``.
It is additive: the frozen ``plan(context)`` signature cannot see policy rules or the
observations behind a context, so this takes the same ``EvidenceBundle`` reconstruction used.
Everything here is deterministic and makes no model call.

Decision rules
--------------
* Non-deletion request -> ``NOT_APPLICABLE`` with no steps; unclear intent -> no answer.
* Each policy-relevant resource is judged against the rule for its category
  (``deletion_rules.csv``): DELETE, ANONYMIZE, REDACT or RETAIN, plus data flows (must be
  disabled) and backups (restore must be blocked).
* ``COMPLETE`` only when nothing violates policy *and* nothing is uncertain. A conflict, a
  coverage issue or an unresolved request never certifies; such a case is reported
  ``INCOMPLETE`` (the safe side) with its reasons in ``blocking_issues``-style trace data.
* Remediation disables flows and blocks restores first, then changes records, downstream
  copies before the profile they came from. Verification covers every relevant resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from slam.contracts import (
    CaseAnswer,
    CaseContext,
    DeletionStatus,
    EvidenceBundle,
    Observation,
    Operation,
    Phase,
    PolicyRule,
    RequestIntent,
    ResourceState,
    Step,
    StepState,
)

_DIRECT_IDENTIFIERS = frozenset({"email", "phone", "email_hash", "name"})
_ABSENT = frozenset({"NOT_FOUND", "ABSENT", "DELETED", "REMOVED", "PURGED"})
_LIVE = frozenset({"PRESENT", "ACTIVE", "IDENTIFIABLE", "RESTORABLE"})
# Downstream copies are processed before the profile they derive from.
_ORDER = (
    "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY",
    "USER_EXPORT",
    "SUPPORT_ATTACHMENT",
    "SUPPORT_MESSAGE",
    "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY",
    "MARKETING_PROFILE",
    "EMAIL_DELIVERY_LOG",
    "SECONDARY_IDENTIFIER",
    "ACCOUNT_TOMBSTONE",
    "USER_PROFILE",
)
_STATE_OF = {
    Operation.VERIFY_RECORD_ABSENT: StepState.ABSENT,
    Operation.VERIFY_RECORD_PRESENT: StepState.PRESENT,
    Operation.VERIFY_RECORD_REDACTED: StepState.REDACTED,
    Operation.VERIFY_RECORD_ANONYMIZED: StepState.ANONYMIZED,
    Operation.VERIFY_DATA_FLOW_DISABLED: StepState.DISABLED,
    Operation.VERIFY_RESTORE_BLOCKED: StepState.BLOCKED,
    Operation.REPORT_REMAINING_RECORD: StepState.PRESENT,
    Operation.REPORT_EXPOSED_PII: StepState.PRESENT,
    Operation.REPORT_ACTIVE_DATA_FLOW: StepState.ACTIVE,
    Operation.REPORT_RESTORE_RISK: StepState.ACTIVE,
    Operation.DISABLE_DATA_FLOW: StepState.DISABLED,
    Operation.BLOCK_RESTORE: StepState.BLOCKED,
    Operation.DELETE_RECORD: StepState.ABSENT,
    Operation.REDACT_RECORD: StepState.REDACTED,
    Operation.ANONYMIZE_RECORD: StepState.ANONYMIZED,
}
_PHASE_OF = {
    **dict.fromkeys(
        (
            Operation.REPORT_REMAINING_RECORD,
            Operation.REPORT_EXPOSED_PII,
            Operation.REPORT_ACTIVE_DATA_FLOW,
            Operation.REPORT_RESTORE_RISK,
        ),
        Phase.FINDING,
    ),
    **dict.fromkeys(
        (
            Operation.DISABLE_DATA_FLOW,
            Operation.BLOCK_RESTORE,
            Operation.DELETE_RECORD,
            Operation.REDACT_RECORD,
            Operation.ANONYMIZE_RECORD,
        ),
        Phase.REMEDIATION,
    ),
}


@dataclass(frozen=True, slots=True)
class _Item:
    """One policy-relevant resource and what must happen to it."""

    state: ResourceState
    finding: Operation | None
    remediation: Operation | None
    verification: Operation

    @property
    def rank(self) -> tuple[int, str, str]:
        category = self.state.category
        position = _ORDER.index(category) if category in _ORDER else len(_ORDER)
        return position, self.state.system_id, self.state.resource_id


def _exposed(
    context: CaseContext, observations: dict[str, Observation] | None, state: ResourceState
) -> bool:
    """Does the latest eligible observation still carry a direct identifier?"""

    if observations is None:
        return state.state not in {"REDACTED", "ANONYMIZED"}

    mine = [
        observations[oid]
        for oid in context.eligible_observation_ids
        if oid in observations
        and observations[oid].system_id == state.system_id
        and observations[oid].resource_id == state.resource_id
    ]
    if not mine:
        return False
    latest = max(item.effective_time for item in mine)
    return any(
        any(key in _DIRECT_IDENTIFIERS and value.strip() for key, value in item.identifiers.items())
        for item in mine
        if item.effective_time == latest
    )


def _assess(action: str | None, state: ResourceState, exposed: bool) -> _Item | None:
    category, value = state.category, state.state
    absent = value in _ABSENT
    if category == "DATA_FLOW":
        if value == "DISABLED":
            return _Item(state, None, None, Operation.VERIFY_DATA_FLOW_DISABLED)
        if value in {"ACTIVE", "PRESENT"}:
            return _Item(
                state,
                Operation.REPORT_ACTIVE_DATA_FLOW,
                Operation.DISABLE_DATA_FLOW,
                Operation.VERIFY_DATA_FLOW_DISABLED,
            )
        return None
    if category == "BACKUP_ARCHIVE":
        if value == "BLOCKED":
            return _Item(state, None, None, Operation.VERIFY_RESTORE_BLOCKED)
        if value in _LIVE:
            return _Item(
                state,
                Operation.REPORT_RESTORE_RISK,
                Operation.BLOCK_RESTORE,
                Operation.VERIFY_RESTORE_BLOCKED,
            )
        return None
    if action == "DELETE":
        if absent:
            return _Item(state, None, None, Operation.VERIFY_RECORD_ABSENT)
        return _Item(
            state,
            Operation.REPORT_REMAINING_RECORD,
            Operation.DELETE_RECORD,
            Operation.VERIFY_RECORD_ABSENT,
        )
    if action == "ANONYMIZE":
        if absent:
            return _Item(state, None, None, Operation.VERIFY_RECORD_ABSENT)
        if value == "ANONYMIZED" or not exposed:
            return _Item(state, None, None, Operation.VERIFY_RECORD_ANONYMIZED)
        return _Item(
            state,
            Operation.REPORT_EXPOSED_PII,
            Operation.ANONYMIZE_RECORD,
            Operation.VERIFY_RECORD_ANONYMIZED,
        )
    if action == "REDACT":
        if absent:
            return _Item(state, None, None, Operation.VERIFY_RECORD_ABSENT)
        if value == "REDACTED" or not exposed:
            return _Item(state, None, None, Operation.VERIFY_RECORD_REDACTED)
        return _Item(
            state,
            Operation.REPORT_EXPOSED_PII,
            Operation.REDACT_RECORD,
            Operation.VERIFY_RECORD_REDACTED,
        )
    if action == "RETAIN" and not absent:
        return _Item(state, None, None, Operation.VERIFY_RECORD_PRESENT)
    return None


def _cite(state: ResourceState, captured: dict[str, datetime], audit_at: datetime) -> str:
    """The most recent supporting citation captured by the audit cutoff."""

    ids = sorted(state.supporting_evidence_ids)
    known = [item for item in ids if item in captured and captured[item] <= audit_at]
    if not known:
        return ""
    return max(known, key=lambda item: (captured[item], item))


def _step(number: int, operation: Operation, state: ResourceState, evidence_id: str) -> Step:
    return Step(
        step_no=number,
        phase=_PHASE_OF.get(operation, Phase.VERIFICATION),
        system_id=state.system_id,
        resource_id=state.resource_id,
        operation=operation,
        state=_STATE_OF[operation],
        evidence_id=evidence_id,
    )


def blocking_reasons(context: CaseContext) -> tuple[str, ...]:
    """Why this case cannot be certified COMPLETE, in a stable order."""

    reasons = [f"conflict:{item}" for item in context.unresolved_conflicts]
    reasons += [f"coverage:{item}" for item in context.coverage_issues]
    reasons += [
        f"conflicting-evidence:{state.system_id}:{state.resource_id}"
        for state in context.resource_states
        if state.conflicting_evidence_ids
    ]
    reasons += [
        f"uncertain-resource:{state.system_id}:{state.resource_id}"
        for state in context.resource_states
        if state.uncertain
    ]
    if not context.resource_states:
        reasons.append("no relevant resource states were established")
    captured = context.evidence_captured_at
    for state in context.resource_states:
        if not any(
            evidence_id in captured and captured[evidence_id] <= context.request.audit_at
            for evidence_id in state.supporting_evidence_ids
        ):
            reasons.append(f"no eligible supporting evidence:{state.system_id}:{state.resource_id}")
    return tuple(sorted(set(reasons)))


def _actions_for_states(context: CaseContext) -> tuple[dict[tuple[str, str], str], tuple[str, ...]]:
    """Resolve one exact policy rule per resource; ambiguous rules block evaluation."""
    by_id = {rule.rule_id: rule for rule in context.policy_rules}
    by_category: dict[str, list[PolicyRule]] = {}
    for rule in context.policy_rules:
        by_category.setdefault(rule.category, []).append(rule)
    actions: dict[tuple[str, str], str] = {}
    issues: list[str] = []
    for state in context.resource_states:
        key = (state.system_id, state.resource_id)
        if state.category in {"DATA_FLOW", "BACKUP_ARCHIVE"}:
            continue
        if state.applicable_rule_id:
            selected_rule = by_id.get(state.applicable_rule_id)
            if selected_rule is None or selected_rule.category != state.category:
                issues.append(
                    f"unknown applicable policy rule:{state.system_id}:{state.resource_id}"
                )
                continue
        else:
            candidates = by_category.get(state.category, [])
            if len(candidates) != 1:
                issues.append(
                    f"ambiguous or missing policy rule:{state.system_id}:{state.resource_id}"
                )
                continue
            selected_rule = candidates[0]
        action = selected_rule.required_action.upper()
        if action not in {"DELETE", "REDACT", "ANONYMIZE", "RETAIN"}:
            issues.append(f"unsupported policy action:{selected_rule.rule_id}")
            continue
        if action == "RETAIN" and state.state.upper() in _ABSENT:
            issues.append(
                f"required retained record is absent:{state.system_id}:{state.resource_id}"
            )
            continue
        actions[key] = action
    return actions, tuple(sorted(issues))


def plan_case(context: CaseContext, bundle: EvidenceBundle | None = None) -> CaseAnswer:
    """Apply policy to one reconstructed case and return its ordered answer."""

    if not context.policy_rules and bundle is not None:
        context = context.model_copy(update={"policy_rules": bundle.policy_rules})
    case_id = context.request.case_id
    if context.request_intent is RequestIntent.NON_DELETION:
        return CaseAnswer(
            case_id=case_id,
            deletion_status=DeletionStatus.NOT_APPLICABLE,
            ready_for_export=True,
            trace={"reason": "request does not authorize deletion"},
        )
    if context.request_intent is RequestIntent.UNCLEAR:
        return CaseAnswer(
            case_id=case_id,
            blocking_issues=("request intent is unclear; deletion is not authorized",),
        )

    actions, rule_issues = _actions_for_states(context)
    reasons = tuple(sorted((*blocking_reasons(context), *rule_issues)))
    if reasons:
        return CaseAnswer(
            case_id=case_id,
            blocking_issues=reasons,
            trace={
                "subject_id": context.subject_id,
                "violations": 0,
                "relevant_resources": len(context.resource_states),
                "not_certified_because": list(reasons),
            },
        )

    # With a bundle we can see which identifiers a record still carries. Without one
    # (the frozen plan(context)) exposure is unknown, so a live record is assumed exposed.
    observations = {item.observation_id: item for item in bundle.observations} if bundle else None
    captured = dict(context.evidence_captured_at) or (
        {source.source_id: source.captured_at for source in bundle.sources} if bundle else {}
    )

    items: list[_Item] = []
    for state in context.resource_states:
        item = _assess(
            actions.get((state.system_id, state.resource_id)),
            state,
            _exposed(context, observations, state),
        )
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: item.rank)

    violations = [item for item in items if item.remediation is not None]
    steps: list[Step] = []
    if not violations and not reasons and items:
        for item in items:
            steps.append(
                _step(
                    len(steps) + 1,
                    item.verification,
                    item.state,
                    _cite(item.state, captured, context.request.audit_at),
                )
            )
        status = DeletionStatus.COMPLETE
    else:
        status = DeletionStatus.INCOMPLETE
        for item in violations:
            assert item.finding is not None
            steps.append(
                _step(
                    len(steps) + 1,
                    item.finding,
                    item.state,
                    _cite(item.state, captured, context.request.audit_at),
                )
            )
        for first in (Operation.DISABLE_DATA_FLOW, Operation.BLOCK_RESTORE):
            for item in violations:
                if item.remediation is first:
                    steps.append(_step(len(steps) + 1, first, item.state, ""))
        for item in violations:
            if item.remediation not in {Operation.DISABLE_DATA_FLOW, Operation.BLOCK_RESTORE}:
                assert item.remediation is not None
                steps.append(_step(len(steps) + 1, item.remediation, item.state, ""))
        for item in items:
            steps.append(_step(len(steps) + 1, item.verification, item.state, ""))

    return CaseAnswer(
        case_id=case_id,
        deletion_status=status,
        steps=tuple(steps),
        ready_for_export=True,
        trace={
            "subject_id": context.subject_id,
            "violations": len(violations),
            "relevant_resources": len(items),
            "not_certified_because": list(reasons),
        },
    )
