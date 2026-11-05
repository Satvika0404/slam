"""Deterministic policy planner for evidence-grounded deletion audits."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from slam.contracts import (
    CaseAnswer,
    CaseContext,
    DeletionStatus,
    GraphEdge,
    Operation,
    Phase,
    PolicyRule,
    RequestIntent,
    ResourceState,
    Step,
    StepState,
)

_ACTION_ALIASES = {
    "DELETE": Operation.DELETE_RECORD,
    "DELETE_RECORD": Operation.DELETE_RECORD,
    "REDACT": Operation.REDACT_RECORD,
    "REDACT_RECORD": Operation.REDACT_RECORD,
    "ANONYMIZE": Operation.ANONYMIZE_RECORD,
    "ANONYMIZE_RECORD": Operation.ANONYMIZE_RECORD,
    "RETAIN": None,
    "RETAIN_RECORD": None,
    "PRESERVE": None,
}
_STATE_ORDER = {
    Operation.DELETE_RECORD: ("ABSENT", "DELETED", "REMOVED", "PURGED"),
    Operation.REDACT_RECORD: ("REDACTED",),
    Operation.ANONYMIZE_RECORD: ("ANONYMIZED",),
}
_PRESENT_STATES = frozenset(
    {"PRESENT", "IDENTIFIABLE", "ACTIVE", "RESTORABLE", "REDACTED", "ANONYMIZED"}
)
_FINDING = {
    Operation.DELETE_RECORD: Operation.REPORT_REMAINING_RECORD,
    Operation.REDACT_RECORD: Operation.REPORT_EXPOSED_PII,
    Operation.ANONYMIZE_RECORD: Operation.REPORT_EXPOSED_PII,
}
_REMEDIATION_ORDER = {
    Operation.DISABLE_DATA_FLOW: 0,
    Operation.BLOCK_RESTORE: 1,
    Operation.DELETE_RECORD: 2,
    Operation.REDACT_RECORD: 3,
    Operation.ANONYMIZE_RECORD: 4,
}
_VERIFICATION = {
    Operation.DELETE_RECORD: Operation.VERIFY_RECORD_ABSENT,
    Operation.REDACT_RECORD: Operation.VERIFY_RECORD_REDACTED,
    Operation.ANONYMIZE_RECORD: Operation.VERIFY_RECORD_ANONYMIZED,
}
_STATE_FOR = {
    Operation.REPORT_REMAINING_RECORD: StepState.PRESENT,
    Operation.REPORT_EXPOSED_PII: StepState.PRESENT,
    Operation.REPORT_ACTIVE_DATA_FLOW: StepState.ACTIVE,
    Operation.REPORT_RESTORE_RISK: StepState.ACTIVE,
    Operation.DISABLE_DATA_FLOW: StepState.DISABLED,
    Operation.BLOCK_RESTORE: StepState.BLOCKED,
    Operation.DELETE_RECORD: StepState.ABSENT,
    Operation.REDACT_RECORD: StepState.REDACTED,
    Operation.ANONYMIZE_RECORD: StepState.ANONYMIZED,
    Operation.VERIFY_RECORD_ABSENT: StepState.ABSENT,
    Operation.VERIFY_RECORD_PRESENT: StepState.PRESENT,
    Operation.VERIFY_RECORD_REDACTED: StepState.REDACTED,
    Operation.VERIFY_RECORD_ANONYMIZED: StepState.ANONYMIZED,
    Operation.VERIFY_DATA_FLOW_DISABLED: StepState.DISABLED,
    Operation.VERIFY_RESTORE_BLOCKED: StepState.BLOCKED,
}


@dataclass(frozen=True, slots=True)
class _Treatment:
    resource: ResourceState
    action: Operation | None
    retain: bool
    compliant: bool


def _eligible_ids(context: CaseContext) -> set[str]:
    return {
        evidence_id
        for evidence_id, captured_at in context.evidence_captured_at.items()
        if evidence_id and captured_at <= context.request.audit_at
    }


def _rule_for(resource: ResourceState, rules: tuple[PolicyRule, ...]) -> PolicyRule | None:
    if resource.applicable_rule_id:
        return next((rule for rule in rules if rule.rule_id == resource.applicable_rule_id), None)
    candidates = [
        rule
        for rule in rules
        if rule.category.strip().casefold() == resource.category.strip().casefold()
    ]
    if len(candidates) != 1:
        return None
    rule = candidates[0]
    # A condition cannot be truthfully evaluated from the reduced ResourceState contract.
    if rule.condition or rule.attributes:
        return None
    return rule


def _treatment(resource: ResourceState, rule: PolicyRule) -> _Treatment | None:
    action_name = rule.required_action.strip().upper().replace(" ", "_")
    if action_name not in _ACTION_ALIASES:
        return None
    action = _ACTION_ALIASES[action_name]
    state = resource.state.strip().upper()
    if action is None:
        return _Treatment(resource, None, True, state in {"PRESENT", "RETAINED", "REDACTED"})
    if resource.uncertain:
        return None
    compliant_states = set(_STATE_ORDER[action])
    if state in compliant_states:
        return _Treatment(resource, action, False, True)
    if action is Operation.DELETE_RECORD and state in _PRESENT_STATES:
        return _Treatment(resource, action, False, False)
    if action in (Operation.REDACT_RECORD, Operation.ANONYMIZE_RECORD) and state in {
        "PRESENT",
        "IDENTIFIABLE",
    }:
        return _Treatment(resource, action, False, False)
    # Unknown, unavailable, scoped, or already-absent records cannot receive a
    # safe record-change operation based on the reduced state contract.
    return None


def _evidence_id(ids: tuple[str, ...], eligible: set[str]) -> str | None:
    usable = sorted(set(ids) & eligible)
    return usable[0] if usable else None


def _step(
    *,
    phase: Phase,
    system_id: str,
    resource_id: str,
    operation: Operation,
    evidence_id: str = "",
) -> Step:
    return Step(
        step_no=1,
        phase=phase,
        system_id=system_id,
        resource_id=resource_id,
        operation=operation,
        state=_STATE_FOR[operation],
        evidence_id=evidence_id,
    )


def _node_location(node: str) -> tuple[str, str] | None:
    parts = node.split(":", 2)
    if len(parts) == 3 and parts[0] == "resource" and parts[1] and parts[2]:
        return parts[1], parts[2]
    if len(parts) == 2 and parts[0] == "system" and parts[1]:
        return parts[1], "system_flow"
    return None


def _edge_location(edge: GraphEdge) -> tuple[str, str] | None:
    source = _node_location(edge.source)
    target = _node_location(edge.target)
    if source is None or target is None:
        return None
    return source[0], f"{source[1]}->{target[0]}:{target[1]}"


def _dependency_order(
    treatments: list[_Treatment], edges: tuple[GraphEdge, ...]
) -> list[_Treatment] | None:
    """Order downstream resource changes before their upstream sources."""
    by_node = {
        f"resource:{item.resource.system_id}:{item.resource.resource_id}": item
        for item in treatments
    }
    indegree = {node: 0 for node in by_node}
    outgoing: dict[str, set[str]] = {node: set() for node in by_node}
    for edge in edges:
        # Source -> target means the target is the downstream copy and must be handled first.
        source = edge.source
        target = edge.target
        if (
            source in by_node
            and target in by_node
            and source != target
            and source not in outgoing[target]
        ):
            outgoing[target].add(source)
            indegree[source] += 1
    ready: list[tuple[str, str, str]] = []
    for node, degree in indegree.items():
        if degree == 0:
            item = by_node[node]
            heapq.heappush(ready, (item.resource.system_id, item.resource.resource_id, node))
    ordered: list[_Treatment] = []
    while ready:
        _, _, node = heapq.heappop(ready)
        ordered.append(by_node[node])
        for neighbor in sorted(outgoing[node]):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                item = by_node[neighbor]
                heapq.heappush(
                    ready, (item.resource.system_id, item.resource.resource_id, neighbor)
                )
    return ordered if len(ordered) == len(by_node) else None


def plan(context: CaseContext) -> CaseAnswer:
    """Produce a deterministic, evidence-backed answer or block certification."""
    if context.request_intent is RequestIntent.NON_DELETION:
        return CaseAnswer(
            case_id=context.request.case_id,
            deletion_status=DeletionStatus.NOT_APPLICABLE,
            ready_for_export=True,
            trace={"decision": "request does not authorize deletion"},
        )
    if context.request_intent is RequestIntent.UNCLEAR:
        return _blocked(context, ("request intent is unresolved",))

    blockers = list(context.coverage_issues)
    blockers.extend(context.unresolved_conflicts)
    if not context.subject_id:
        blockers.append("subject identity is unresolved")
    if not context.resource_states:
        blockers.append("no subject resource states are available")
    eligible = _eligible_ids(context)
    treatments: list[_Treatment] = []
    policy_assessments: list[dict[str, str]] = []
    for resource in context.resource_states:
        rule = _rule_for(resource, context.policy_rules)
        if rule is None:
            blockers.append(f"no unique unconditional policy rule for {resource.category}")
            continue
        treatment = _treatment(resource, rule)
        if treatment is None:
            blockers.append(
                f"policy action or resource state is unresolved for {resource.resource_id}"
            )
            continue
        if (
            not treatment.retain
            and not treatment.compliant
            and _evidence_id(resource.supporting_evidence_ids, eligible) is None
        ):
            blockers.append(f"no eligible participant-visible evidence for {resource.resource_id}")
        if resource.uncertain:
            blockers.append(f"resource state is uncertain for {resource.resource_id}")
        treatments.append(treatment)
        policy_assessments.append(
            {
                "system_id": resource.system_id,
                "resource_id": resource.resource_id,
                "rule_id": rule.rule_id,
                "required_action": rule.required_action,
            }
        )

    flows: list[tuple[GraphEdge, str, str, str]] = []
    restores: list[tuple[GraphEdge, str, str, str]] = []
    for edge in context.active_flows:
        location = _edge_location(edge)
        evidence = _evidence_id(edge.evidence_ids, eligible)
        if location is None or evidence is None:
            blockers.append("active flow lacks a valid location or eligible evidence")
        else:
            flows.append((edge, location[0], location[1], evidence))
    for edge in context.restore_risks:
        location = _edge_location(edge)
        evidence = _evidence_id(edge.evidence_ids, eligible)
        if location is None or evidence is None:
            blockers.append("restore risk lacks a valid location or eligible evidence")
        else:
            restores.append((edge, location[0], location[1], evidence))

    records_to_change = [item for item in treatments if not item.retain and not item.compliant]
    ordered = _dependency_order(records_to_change, (*context.active_flows, *context.restore_risks))
    if ordered is None:
        blockers.append("record dependency graph contains an unsafe cycle")
        ordered = []
    for item in treatments:
        if item.retain and not item.compliant:
            blockers.append(
                "policy-required retained record is missing or noncompliant: "
                f"{item.resource.resource_id}"
            )

    if blockers:
        return _blocked(context, tuple(sorted(set(blockers)))).model_copy(
            update={"trace": {"policy_assessments": policy_assessments}}
        )

    findings: list[Step] = []
    remediations: list[Step] = []
    verifications: list[Step] = []
    for item in treatments:
        resource = item.resource
        if item.retain:
            evidence = _evidence_id(resource.supporting_evidence_ids, eligible)
            if evidence is None:
                return _blocked(
                    context, (f"retained record lacks eligible evidence: {resource.resource_id}",)
                )
            verifications.append(
                _step(
                    phase=Phase.VERIFICATION,
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    operation=Operation.VERIFY_RECORD_PRESENT,
                    evidence_id=evidence,
                )
            )
        elif item.compliant:
            action = item.action
            if action is None:
                return _blocked(context, (f"missing treatment for {resource.resource_id}",))
            evidence = _evidence_id(resource.supporting_evidence_ids, eligible)
            if evidence is None:
                return _blocked(
                    context, (f"compliant state lacks eligible evidence: {resource.resource_id}",)
                )
            verifications.append(
                _step(
                    phase=Phase.VERIFICATION,
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    operation=_VERIFICATION[action],
                    evidence_id=evidence,
                )
            )
        else:
            assert item.action is not None
            evidence = _evidence_id(resource.supporting_evidence_ids, eligible)
            if evidence is None:
                return _blocked(
                    context, (f"violation lacks eligible evidence: {resource.resource_id}",)
                )
            findings.append(
                _step(
                    phase=Phase.FINDING,
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    operation=_FINDING[item.action],
                    evidence_id=evidence,
                )
            )
            remediations.append(
                _step(
                    phase=Phase.REMEDIATION,
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    operation=item.action,
                )
            )
            verifications.append(
                _step(
                    phase=Phase.VERIFICATION,
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    operation=_VERIFICATION[item.action],
                )
            )

    for _, system, resource_key, evidence in flows:
        findings.append(
            _step(
                phase=Phase.FINDING,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.REPORT_ACTIVE_DATA_FLOW,
                evidence_id=evidence,
            )
        )
        remediations.append(
            _step(
                phase=Phase.REMEDIATION,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.DISABLE_DATA_FLOW,
            )
        )
        verifications.append(
            _step(
                phase=Phase.VERIFICATION,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.VERIFY_DATA_FLOW_DISABLED,
            )
        )
    for _, system, resource_key, evidence in restores:
        findings.append(
            _step(
                phase=Phase.FINDING,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.REPORT_RESTORE_RISK,
                evidence_id=evidence,
            )
        )
        remediations.append(
            _step(
                phase=Phase.REMEDIATION,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.BLOCK_RESTORE,
            )
        )
        verifications.append(
            _step(
                phase=Phase.VERIFICATION,
                system_id=system,
                resource_id=resource_key,
                operation=Operation.VERIFY_RESTORE_BLOCKED,
            )
        )

    findings.sort(key=lambda s: (list(Operation).index(s.operation), s.system_id, s.resource_id))
    remediations.sort(key=lambda s: (_REMEDIATION_ORDER[s.operation], s.system_id, s.resource_id))
    verifications.sort(
        key=lambda s: (list(Operation).index(s.operation), s.system_id, s.resource_id)
    )
    if remediations:
        # Preserve the graph-derived ordering among record changes after process controls.
        record_keys = {
            (item.resource.system_id, item.resource.resource_id): i
            for i, item in enumerate(ordered)
        }
        remediations.sort(
            key=lambda s: (
                _REMEDIATION_ORDER[s.operation],
                record_keys.get((s.system_id, s.resource_id), -1)
                if s.operation
                in (Operation.DELETE_RECORD, Operation.REDACT_RECORD, Operation.ANONYMIZE_RECORD)
                else (s.system_id, s.resource_id),
                s.system_id,
                s.resource_id,
            )
        )
    status = DeletionStatus.INCOMPLETE if remediations else DeletionStatus.COMPLETE
    if status is DeletionStatus.INCOMPLETE:
        verifications = [step.model_copy(update={"evidence_id": ""}) for step in verifications]
    steps = tuple(
        step.model_copy(update={"step_no": index})
        for index, step in enumerate((*findings, *remediations, *verifications), start=1)
    )
    answer = CaseAnswer(
        case_id=context.request.case_id,
        deletion_status=status,
        steps=steps,
        ready_for_export=True,
        trace={
            "policy_assessments": policy_assessments,
            "policy_rules": [rule.rule_id for rule in context.policy_rules],
            "resource_count": len(treatments),
            "active_flow_count": len(flows),
            "restore_risk_count": len(restores),
        },
    )
    from .validation import validate_answer

    return validate_answer(answer, eligible_evidence_ids=eligible)


def _blocked(context: CaseContext, blockers: tuple[str, ...]) -> CaseAnswer:
    return CaseAnswer(
        case_id=context.request.case_id,
        ready_for_export=False,
        blocking_issues=blockers,
        trace={"decision": "blocked; insufficient or conflicting evidence/policy"},
    )
