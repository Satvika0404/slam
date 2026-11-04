"""Planner behaviour on three hand-built evaluation cases, plus exporter invariants."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from slam.contracts import (
    AuditRequest,
    CaseContext,
    CurrentIdentity,
    DeletionStatus,
    EvidenceBundle,
    Observation,
    Operation,
    PolicyRule,
    RequestIntent,
    ResourceState,
    SourceKind,
    SourceRecord,
    SourceSpan,
)
from slam.planning.engine import plan_case
from slam.planning.export import ExportError, export_output_csv
from slam.planning.validation import validate_answer
from slam.reconstruction import reconstruct

EMAIL = "pat@example.test"
RULES = tuple(
    PolicyRule(rule_id=f"r{i}", category=cat, required_action=act)
    for i, (cat, act) in enumerate(
        [
            ("USER_PROFILE", "DELETE"),
            ("SEARCH_INDEX_ENTRY", "DELETE"),
            ("ANALYTICS_PROFILE", "ANONYMIZE"),
            ("BACKUP_ARCHIVE", "RETAIN"),
        ]
    )
)


def _request(text: str = "Please delete my account.") -> AuditRequest:
    return AuditRequest(
        case_id="c1",
        email=EMAIL,
        requested_at=datetime(2026, 1, 1, tzinfo=UTC),
        reported_status="COMPLETE",
        reported_at=datetime(2026, 1, 2, tzinfo=UTC),
        audit_at=datetime(2026, 2, 1, tzinfo=UTC),
        request_text=text,
    )


def _obs(
    label: str, resource: str, system: str, category: str, state: str, with_email: bool = True
) -> Observation:
    return Observation(
        observation_id=hashlib.sha256(label.encode()).hexdigest(),
        subject_hints=(EMAIL,) if with_email else (),
        system_id=system,
        resource_id=resource,
        category=category,
        observed_state=state,
        effective_time=datetime(2026, 1, 20, tzinfo=UTC),
        source_kind=SourceKind.JSON,
        identifiers={"email": EMAIL} if with_email else {},
        fields={"evidence_nature": "observation", "source": {}},
        spans=(SourceSpan(source_id="evidence_1", json_path=f"$.{label}"),),
    )


def _bundle(*observations: Observation, rules: tuple[PolicyRule, ...] = RULES) -> EvidenceBundle:
    identity = CurrentIdentity(
        user_id="user_1",
        name="Pat",
        email=EMAIL,
        email_normalized=EMAIL,
        phone="+1 202 555 0101",
        email_hash="a" * 64,
        updated_at=datetime(2026, 1, 10, tzinfo=UTC),
        source_id="identity_1",
    )
    source = SourceRecord(
        source_id="evidence_1",
        kind=SourceKind.JSON,
        origin="t",
        path="e.json",
        captured_at=datetime(2026, 1, 20, tzinfo=UTC),
        sha256="b" * 64,
        parse_status="parsed",
    )
    return EvidenceBundle(
        sources=(source,),
        current_identities=(identity,),
        observations=observations,
        policy_rules=rules,
    )


def _plan(bundle: EvidenceBundle, text: str = "Please delete my account."):  # type: ignore[no-untyped-def]
    answer = plan_case(reconstruct(_request(text), bundle), bundle)
    return validate_answer(answer, eligible_evidence_ids={"evidence_1"}) if answer.steps else answer


def test_complete_case_has_only_evidence_backed_verification() -> None:
    answer = _plan(
        _bundle(
            _obs("scope", "account_1", "account_service", "SNAPSHOT_SCOPE", "SCOPED", False),
            _obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"),
        )
    )
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert [s.operation for s in answer.steps] == [Operation.VERIFY_RECORD_ABSENT]
    assert answer.steps[0].evidence_id == "evidence_1"


def test_incomplete_case_orders_mitigation_before_records_and_copies_before_profile() -> None:
    answer = _plan(
        _bundle(
            _obs("p", "account_1", "account_service", "USER_PROFILE", "PRESENT"),
            _obs("s", "search_1", "search_service", "SEARCH_INDEX_ENTRY", "PRESENT"),
            _obs("f", "data_flow_1", "integration_service", "DATA_FLOW", "ACTIVE"),
            _obs("b", "backup_1", "backup_service", "BACKUP_ARCHIVE", "RESTORABLE"),
        )
    )
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    ops = [s.operation for s in answer.steps]
    remediation = [s for s in answer.steps if s.phase.value == "REMEDIATION"]
    assert [s.operation for s in remediation] == [
        Operation.DISABLE_DATA_FLOW,
        Operation.BLOCK_RESTORE,
        Operation.DELETE_RECORD,
        Operation.DELETE_RECORD,
    ]
    assert [s.resource_id for s in remediation[2:]] == ["search_1", "account_1"]
    assert ops.index(Operation.DISABLE_DATA_FLOW) < ops.index(Operation.DELETE_RECORD)
    assert all(s.evidence_id == "" for s in answer.steps if s.phase.value != "FINDING")
    assert all(s.evidence_id == "evidence_1" for s in answer.steps if s.phase.value == "FINDING")


def test_order_is_stable_when_input_observations_are_shuffled() -> None:
    observations = (
        _obs("profile", "account_1", "account_service", "USER_PROFILE", "PRESENT"),
        _obs("search", "search_1", "search_service", "SEARCH_INDEX_ENTRY", "PRESENT"),
        _obs("flow", "flow_1", "integration", "DATA_FLOW", "ACTIVE"),
        _obs("backup", "backup_1", "backup", "BACKUP_ARCHIVE", "RESTORABLE"),
    )
    forward = _plan(_bundle(*observations))
    reverse = _plan(_bundle(*reversed(observations)))
    assert forward.steps == reverse.steps


def test_non_deletion_is_not_applicable_without_steps() -> None:
    answer = _plan(
        _bundle(_obs("p", "account_1", "account_service", "USER_PROFILE", "PRESENT")),
        "Please export a copy of my data.",
    )
    assert answer.deletion_status is DeletionStatus.NOT_APPLICABLE and answer.steps == ()


def test_conflict_never_certifies_complete() -> None:
    bundle = _bundle(
        _obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"),
        _obs("b", "account_1", "account_service", "USER_PROFILE", "PRESENT"),
    )
    answer = _plan(bundle)
    assert answer.deletion_status is None
    assert answer.ready_for_export is False
    assert answer.blocking_issues


def test_unclear_request_gets_no_status_and_export_refuses_it(tmp_path: Path) -> None:
    answer = plan_case(reconstruct(_request("hello"), _bundle()), _bundle())
    assert answer.deletion_status is None
    with pytest.raises(ExportError):
        export_output_csv([answer], ["c1"], tmp_path / "o.csv")


def test_export_is_sorted_exact_and_rejects_missing_cases(tmp_path: Path) -> None:
    bundle = _bundle(
        _obs("scope", "account_1", "account_service", "SNAPSHOT_SCOPE", "SCOPED", False),
        _obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"),
    )
    answer = _plan(bundle)
    target = tmp_path / "o.csv"
    export_output_csv([answer], ["c1"], target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "case_id,deletion_status,steps_json" and lines[1].startswith("c1,COMPLETE,")
    with pytest.raises(ExportError):
        export_output_csv([answer], ["c1", "c2"], target)


def test_frozen_plan_works_from_the_context_alone_and_context_carries_1_1_0_fields() -> None:
    from slam.planning import plan

    bundle = _bundle(_obs("p", "account_1", "account_service", "USER_PROFILE", "PRESENT"))
    context = reconstruct(_request(), bundle)
    assert context.policy_rules == RULES
    assert set(context.evidence_captured_at) == {"evidence_1"}
    assert all(t <= context.request.audit_at for t in context.evidence_captured_at.values())
    answer = plan(context)
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    assert [s.operation for s in answer.steps if s.phase.value == "REMEDIATION"] == [
        Operation.DELETE_RECORD
    ]


def test_without_a_bundle_exposure_is_assumed_never_a_false_complete() -> None:
    from slam.planning import plan

    bundle = _bundle(_obs("a", "analytics_1", "analytics_platform", "ANALYTICS_PROFILE", "PRESENT"))
    answer = plan(reconstruct(_request(), bundle))
    assert answer.deletion_status is DeletionStatus.INCOMPLETE


def test_compliant_tombstone_retains_stable_reference_and_verifies() -> None:
    from slam.planning import plan

    rules = (
        PolicyRule(rule_id="tombstone", category="ACCOUNT_TOMBSTONE", required_action="REDACT"),
    )
    observation = _obs(
        "tombstone", "t1", "account_service", "ACCOUNT_TOMBSTONE", "REDACTED"
    ).model_copy(update={"identifiers": {"user_id": "stable-42"}})
    answer = plan(reconstruct(_request(), _bundle(observation, rules=rules)))
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert [step.operation for step in answer.steps] == [Operation.VERIFY_RECORD_REDACTED]


def test_tombstone_with_exposed_hash_is_incomplete_and_redacted() -> None:
    from slam.planning import plan

    rules = (
        PolicyRule(rule_id="tombstone", category="ACCOUNT_TOMBSTONE", required_action="REDACT"),
    )
    observation = _obs(
        "tombstone", "t1", "account_service", "ACCOUNT_TOMBSTONE", "PRESENT", False
    ).model_copy(update={"identifiers": {"email_hash": "a" * 64}})
    answer = plan(reconstruct(_request(), _bundle(observation, rules=rules)))
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    assert [step.operation for step in answer.steps] == [
        Operation.REPORT_EXPOSED_PII,
        Operation.REDACT_RECORD,
        Operation.VERIFY_RECORD_REDACTED,
    ]


def test_required_retained_record_remains_and_gets_evidence_backed_verification() -> None:
    from slam.planning import plan

    rules = (PolicyRule(rule_id="hold", category="SECURITY_AUDIT", required_action="RETAIN"),)
    observation = _obs("audit", "audit-7", "audit_service", "SECURITY_AUDIT", "PRESENT")
    answer = plan(reconstruct(_request(), _bundle(observation, rules=rules)))
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert answer.steps[0].operation is Operation.VERIFY_RECORD_PRESENT
    assert answer.steps[0].evidence_id == "evidence_1"


def test_shared_support_record_is_redacted_not_deleted() -> None:
    from slam.planning import plan

    rules = (PolicyRule(rule_id="support", category="SUPPORT_MESSAGE", required_action="REDACT"),)
    observation = _obs("support", "ticket-4", "support_service", "SUPPORT_MESSAGE", "PRESENT")
    answer = plan(reconstruct(_request(), _bundle(observation, rules=rules)))
    assert [step.operation for step in answer.steps] == [
        Operation.REPORT_EXPOSED_PII,
        Operation.REDACT_RECORD,
        Operation.VERIFY_RECORD_REDACTED,
    ]


def test_attributable_analytics_is_anonymized() -> None:
    from slam.planning import plan

    rules = (
        PolicyRule(rule_id="analytics", category="ANALYTICS_PROFILE", required_action="ANONYMIZE"),
    )
    observation = _obs("analytics", "profile-4", "analytics", "ANALYTICS_PROFILE", "PRESENT")
    answer = plan(reconstruct(_request(), _bundle(observation, rules=rules)))
    assert [step.operation for step in answer.steps] == [
        Operation.REPORT_EXPOSED_PII,
        Operation.ANONYMIZE_RECORD,
        Operation.VERIFY_RECORD_ANONYMIZED,
    ]


def test_future_only_citation_blocks_certification() -> None:
    future = datetime(2026, 3, 1, tzinfo=UTC)
    context = CaseContext(
        request=_request(),
        request_intent=RequestIntent.DELETION,
        policy_rules=RULES,
        evidence_captured_at={"future-evidence": future},
        resource_states=(
            ResourceState(
                system_id="account_service",
                resource_id="account-1",
                category="USER_PROFILE",
                state="PRESENT",
                at=_request().audit_at,
                supporting_evidence_ids=("future-evidence",),
            ),
        ),
    )
    from slam.planning import plan

    answer = plan(context)
    assert answer.deletion_status is None
    assert not answer.ready_for_export
    assert any("no eligible supporting evidence" in item for item in answer.blocking_issues)


def test_duplicate_category_rules_require_an_explicit_applicable_rule() -> None:
    from slam.planning import plan

    bundle = _bundle(
        _obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"),
        rules=(
            PolicyRule(rule_id="delete", category="USER_PROFILE", required_action="DELETE"),
            PolicyRule(
                rule_id="retain-under-hold",
                category="USER_PROFILE",
                required_action="RETAIN",
                condition="legal hold applies",
            ),
        ),
    )
    context = reconstruct(_request(), bundle)
    answer = plan(context)
    assert answer.deletion_status is None
    assert any("ambiguous or missing policy rule" in item for item in answer.blocking_issues)
