"""Planner behaviour on three hand-built evaluation cases, plus exporter invariants."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from slam.contracts import (
    AuditRequest,
    CurrentIdentity,
    DeletionStatus,
    EvidenceBundle,
    Observation,
    Operation,
    PolicyRule,
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


def _bundle(*observations: Observation) -> EvidenceBundle:
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
        policy_rules=RULES,
    )


def _plan(bundle: EvidenceBundle, text: str = "Please delete my account."):  # type: ignore[no-untyped-def]
    answer = plan_case(reconstruct(_request(text), bundle), bundle)
    return validate_answer(answer, eligible_evidence_ids={"evidence_1"}) if answer.steps else answer


def test_complete_case_has_only_evidence_backed_verification() -> None:
    answer = _plan(_bundle(_obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND")))
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert [s.operation for s in answer.steps] == [Operation.VERIFY_RECORD_ABSENT]
    assert answer.steps[0].evidence_id == "evidence_1"


def test_incomplete_case_follows_the_specified_step_order() -> None:
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
    # Spec: operation order, then system_id, then resource_id ascending.
    assert [s.resource_id for s in remediation[2:]] == ["account_1", "search_1"]
    assert ops.index(Operation.DISABLE_DATA_FLOW) < ops.index(Operation.DELETE_RECORD)
    assert all(s.evidence_id == "" for s in answer.steps if s.phase.value != "FINDING")
    assert all(s.evidence_id == "evidence_1" for s in answer.steps if s.phase.value == "FINDING")


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
    assert _plan(bundle).deletion_status is DeletionStatus.INCOMPLETE


def test_unclear_request_gets_no_status_and_export_refuses_it(tmp_path: Path) -> None:
    answer = plan_case(reconstruct(_request("hello"), _bundle()), _bundle())
    assert answer.deletion_status is None
    with pytest.raises(ExportError):
        export_output_csv([answer], ["c1"], tmp_path / "o.csv")


def test_export_is_sorted_exact_and_rejects_missing_cases(tmp_path: Path) -> None:
    bundle = _bundle(_obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"))
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


def _with_late_audit_record(bundle: EvidenceBundle) -> EvidenceBundle:
    """A retained audit record seen before the cutoff, in a file exported after it."""

    audit = _obs("aud", "audit_record_1", "security_service", "SECURITY_AUDIT_LOG", "PRESENT")
    audit = audit.model_copy(
        update={"spans": (SourceSpan(source_id="evidence_late", json_path="$.a"),)}
    )
    late = SourceRecord(
        source_id="evidence_late",
        kind=SourceKind.JSON,
        origin="t",
        path="l.json",
        captured_at=datetime(2026, 3, 1, tzinfo=UTC),
        sha256="c" * 64,
        parse_status="parsed",
    )
    rule = PolicyRule(rule_id="r_audit", category="SECURITY_AUDIT_LOG", required_action="RETAIN")
    return bundle.model_copy(
        update={
            "sources": (*bundle.sources, late),
            "observations": (*bundle.observations, audit),
            "policy_rules": (*bundle.policy_rules, rule),
        }
    )


def test_late_exported_retained_record_is_only_an_uncited_future_check() -> None:
    base = _bundle(_obs("p", "account_1", "account_service", "USER_PROFILE", "PRESENT"))
    answer = _plan(_with_late_audit_record(base))
    assert answer.deletion_status is DeletionStatus.INCOMPLETE
    audit = [s for s in answer.steps if s.resource_id == "audit_record_1"]
    assert [(s.phase.value, s.operation, s.evidence_id) for s in audit] == [
        ("VERIFICATION", Operation.VERIFY_RECORD_PRESENT, "")
    ]  # never a finding, never cited


def test_late_exported_retained_record_never_appears_in_a_complete_answer() -> None:
    base = _bundle(_obs("a", "account_1", "account_service", "USER_PROFILE", "NOT_FOUND"))
    answer = _plan(_with_late_audit_record(base))
    assert answer.deletion_status is DeletionStatus.COMPLETE
    assert [s.resource_id for s in answer.steps] == ["account_1"]
    assert all(s.evidence_id for s in answer.steps)
