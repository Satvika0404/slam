from datetime import UTC, datetime

from slam.contracts import (
    AuditRequest,
    CaseContext,
    DeletionStatus,
    GraphEdge,
    Operation,
    PolicyRule,
    RequestIntent,
    ResourceState,
)
from slam.planning.api import plan

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def context(**updates):
    base = {
        "request": AuditRequest(
            case_id="case_1",
            email="person@example.test",
            requested_at=NOW,
            reported_status="COMPLETE",
            reported_at=NOW,
            audit_at=NOW,
            request_text="delete my data",
        ),
        "request_intent": RequestIntent.DELETION,
        "subject_id": "user_1",
        "policy_rules": (
            PolicyRule(rule_id="rule_1", category="PROFILE", required_action="DELETE"),
        ),
        "resource_states": (
            ResourceState(
                system_id="account",
                resource_id="profile_1",
                category="PROFILE",
                state="PRESENT",
                at=NOW,
                supporting_evidence_ids=("file_1",),
            ),
        ),
        "evidence_captured_at": {"file_1": NOW},
    }
    base.update(updates)
    return CaseContext(**base)


def test_non_deletion_is_not_applicable_with_no_steps():
    answer = plan(context(request_intent=RequestIntent.NON_DELETION))
    assert answer.deletion_status is DeletionStatus.NOT_APPLICABLE
    assert answer.steps == ()
    assert answer.ready_for_export


def test_present_delete_target_gets_finding_action_and_verification():
    answer = plan(context())
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    assert [step.operation for step in answer.steps] == [
        Operation.REPORT_REMAINING_RECORD,
        Operation.DELETE_RECORD,
        Operation.VERIFY_RECORD_ABSENT,
    ]
    assert answer.steps[0].evidence_id == "file_1"
    assert answer.steps[1].evidence_id == answer.steps[2].evidence_id == ""
    assert [step.step_no for step in answer.steps] == [1, 2, 3]


def test_compliant_redacted_record_is_complete_and_cites_evidence():
    answer = plan(
        context(
            policy_rules=(PolicyRule(rule_id="r", category="PROFILE", required_action="REDACT"),),
            resource_states=(
                ResourceState(
                    system_id="support",
                    resource_id="ticket_1",
                    category="PROFILE",
                    state="REDACTED",
                    at=NOW,
                    supporting_evidence_ids=("file_1",),
                ),
            ),
        )
    )
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert len(answer.steps) == 1
    assert answer.steps[0].operation is Operation.VERIFY_RECORD_REDACTED
    assert answer.steps[0].evidence_id == "file_1"


def test_present_redaction_target_reports_pii_and_plans_redaction():
    answer = plan(
        context(
            policy_rules=(PolicyRule(rule_id="r", category="PROFILE", required_action="REDACT"),),
        )
    )
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    assert [step.operation for step in answer.steps] == [
        Operation.REPORT_EXPOSED_PII,
        Operation.REDACT_RECORD,
        Operation.VERIFY_RECORD_REDACTED,
    ]


def test_retained_record_is_preserved_and_verified():
    answer = plan(
        context(
            policy_rules=(PolicyRule(rule_id="r", category="PROFILE", required_action="RETAIN"),),
        )
    )
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert [step.operation for step in answer.steps] == [Operation.VERIFY_RECORD_PRESENT]


def test_missing_or_future_citation_blocks_exportable_answer():
    answer = plan(context(evidence_captured_at={"file_1": datetime(2027, 1, 1, tzinfo=UTC)}))
    assert not answer.ready_for_export
    assert answer.deletion_status is None


def test_ambiguous_policy_blocks_instead_of_guessing():
    answer = plan(
        context(
            policy_rules=(
                PolicyRule(rule_id="r1", category="PROFILE", required_action="DELETE"),
                PolicyRule(rule_id="r2", category="PROFILE", required_action="REDACT"),
            )
        )
    )
    assert not answer.ready_for_export
    assert answer.deletion_status is None


def test_active_flow_is_disabled_before_record_changes():
    answer = plan(
        context(
            active_flows=(
                GraphEdge(
                    source="resource:account:profile_1",
                    target="resource:search:profile_1",
                    relationship="sync",
                    evidence_ids=("activity_1",),
                    active=True,
                ),
            ),
            evidence_captured_at={"file_1": NOW, "activity_1": NOW},
        )
    )
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    remediation = [step for step in answer.steps if step.phase.value == "REMEDIATION"]
    assert [step.operation for step in remediation] == [
        Operation.DISABLE_DATA_FLOW,
        Operation.DELETE_RECORD,
    ]


def test_restore_risk_is_blocked_before_record_changes():
    answer = plan(
        context(
            restore_risks=(
                GraphEdge(
                    source="resource:backup:archive_1",
                    target="resource:account:profile_1",
                    relationship="restore_path",
                    evidence_ids=("activity_1",),
                    active=True,
                ),
            ),
            evidence_captured_at={"file_1": NOW, "activity_1": NOW},
        )
    )
    remediation = [step for step in answer.steps if step.phase.value == "REMEDIATION"]
    assert [step.operation for step in remediation] == [
        Operation.BLOCK_RESTORE,
        Operation.DELETE_RECORD,
    ]


def test_downstream_copy_is_remediated_before_source():
    answer = plan(
        context(
            resource_states=(
                ResourceState(
                    system_id="account",
                    resource_id="source",
                    category="PROFILE",
                    state="PRESENT",
                    at=NOW,
                    supporting_evidence_ids=("file_1",),
                ),
                ResourceState(
                    system_id="search",
                    resource_id="copy",
                    category="PROFILE",
                    state="PRESENT",
                    at=NOW,
                    supporting_evidence_ids=("file_1",),
                ),
            ),
            active_flows=(
                GraphEdge(
                    source="resource:account:source",
                    target="resource:search:copy",
                    relationship="replicates_to",
                    evidence_ids=("activity_1",),
                    active=True,
                ),
            ),
            evidence_captured_at={"file_1": NOW, "activity_1": NOW},
        )
    )
    changes = [
        step.resource_id
        for step in answer.steps
        if step.phase.value == "REMEDIATION" and step.operation is Operation.DELETE_RECORD
    ]
    assert changes == ["copy", "source"]
