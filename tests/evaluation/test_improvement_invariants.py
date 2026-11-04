"""Cross-run safety invariants on fictional, ground-truth-free evidence inputs."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st
from slam.contracts import (
    AuditRequest,
    CurrentIdentity,
    DeletionStatus,
    EvidenceBundle,
    Observation,
    PolicyRule,
    SourceKind,
    SourceRecord,
    SourceSpan,
)
from slam.evaluation.data_quality import analyze_evidence_patterns
from slam.planning.engine import plan_case
from slam.reconstruction import reconstruct

NOW = datetime(2026, 3, 1, tzinfo=UTC)
EMAIL = "fictional-audit-subject@example.test"


def _request() -> AuditRequest:
    return AuditRequest(
        case_id="fictional-case",
        email=EMAIL,
        requested_at=NOW - timedelta(days=20),
        reported_status="COMPLETE",
        reported_at=NOW - timedelta(days=10),
        audit_at=NOW,
        request_text="Please delete this fictional account.",
    )


def _observation(
    label: str,
    resource: str,
    state: str,
    *,
    email: str = EMAIL,
    category: str = "USER_PROFILE",
    effective_at: datetime = NOW - timedelta(days=1),
    fields: dict[str, object] | None = None,
) -> Observation:
    return Observation(
        observation_id=hashlib.sha256(label.encode()).hexdigest(),
        subject_hints=(email,) if email else (),
        system_id="fictional-primary",
        resource_id=resource,
        category=category,
        observed_state=state,
        effective_time=effective_at,
        source_kind=SourceKind.JSON,
        identifiers={"email": email} if email else {},
        fields={"evidence_nature": "observation", "source": {}, **(fields or {})},
        spans=(SourceSpan(source_id="fictional-evidence", json_path=f"$.{label}"),),
    )


def _bundle(*observations: Observation) -> EvidenceBundle:
    source = SourceRecord(
        source_id="fictional-evidence",
        kind=SourceKind.JSON,
        origin="fictional-fixture",
        path="synthetic/evidence.json",
        captured_at=NOW - timedelta(days=2),
        sha256=hashlib.sha256(b"fictional evidence").hexdigest(),
        parse_status="parsed",
    )
    identity = CurrentIdentity(
        user_id="fictional-subject-1",
        name="Fictional Person",
        email=EMAIL,
        email_normalized=EMAIL,
        phone="+1 202 555 0100",
        email_hash=hashlib.sha256(EMAIL.encode()).hexdigest(),
        updated_at=NOW - timedelta(days=5),
        source_id=source.source_id,
    )
    return EvidenceBundle(
        sources=(source,),
        current_identities=(identity,),
        observations=observations,
        policy_rules=(
            PolicyRule(
                rule_id="fictional-delete", category="USER_PROFILE", required_action="DELETE"
            ),
            PolicyRule(
                rule_id="fictional-backup-delete",
                category="BACKUP_ARCHIVE",
                required_action="DELETE",
            ),
        ),
    )


def _audit(bundle: EvidenceBundle):
    context = reconstruct(_request(), bundle)
    return context, plan_case(context, bundle)


def test_input_reordering_and_duplicate_evidence_do_not_change_answer_or_duplicate_actions() -> (
    None
):
    observations = (
        _observation("a", "fictional-profile", "PRESENT"),
        _observation("b", "fictional-replica", "ABSENT"),
    )
    first_context, first = _audit(_bundle(*observations))
    reversed_context, reversed_answer = _audit(_bundle(*reversed(observations)))
    _, duplicated_answer = _audit(_bundle(*observations, observations[0]))
    assert first == reversed_answer
    assert first_context.eligible_observation_ids == reversed_context.eligible_observation_ids
    assert first.deletion_status is DeletionStatus.INCOMPLETE
    action_keys = [
        (step.system_id, step.resource_id, step.operation) for step in duplicated_answer.steps
    ]
    assert len(action_keys) == len(set(action_keys))


def test_unrelated_evidence_does_not_change_subject_membership() -> None:
    relevant = _observation("matched", "fictional-profile", "PRESENT")
    unrelated = _observation(
        "other-subject",
        "fictional-other-profile",
        "PRESENT",
        email="unrelated-fictional-subject@example.test",
    )
    context_before, _ = _audit(_bundle(relevant))
    context_after, answer_after = _audit(_bundle(relevant, unrelated))
    assert context_before.eligible_observation_ids == context_after.eligible_observation_ids
    assert "fictional-other-profile" not in {
        state.resource_id for state in context_after.resource_states
    }
    assert answer_after.deletion_status is DeletionStatus.INCOMPLETE


def test_post_cutoff_observation_does_not_change_earlier_audit_answer() -> None:
    prior = _observation("prior", "fictional-profile", "NOT_FOUND")
    after_cutoff = _observation(
        "future", "fictional-profile", "PRESENT", effective_at=NOW + timedelta(seconds=1)
    )
    _, baseline = _audit(_bundle(prior))
    future_context, with_future = _audit(_bundle(prior, after_cutoff))
    assert baseline == with_future
    assert after_cutoff.observation_id not in set(future_context.eligible_observation_ids)


@given(offset_seconds=st.integers(min_value=-1, max_value=1))
@settings(max_examples=12, deadline=None, database=None)
def test_audit_cutoff_boundary_is_inclusive_and_stable(offset_seconds: int) -> None:
    boundary_observation = _observation(
        f"boundary-{offset_seconds}",
        "fictional-profile",
        "PRESENT",
        effective_at=NOW + timedelta(seconds=offset_seconds),
    )
    context, _ = _audit(_bundle(boundary_observation))
    included = boundary_observation.observation_id in set(context.eligible_observation_ids)
    assert included is (offset_seconds <= 0)


@given(
    first_state=st.sampled_from(("PRESENT", "ABSENT")),
    second_state=st.sampled_from(("PRESENT", "ABSENT")),
)
@settings(max_examples=4, deadline=None, database=None)
def test_hypothesis_varies_contradictory_evidence(first_state: str, second_state: str) -> None:
    first = _observation("variable-a", "fictional-profile", first_state)
    second = _observation("variable-b", "fictional-profile", second_state)
    context, answer = _audit(_bundle(first, second))
    if first_state == second_state:
        assert not context.unresolved_conflicts
    else:
        assert context.unresolved_conflicts
        assert answer.deletion_status is not DeletionStatus.COMPLETE


@given(active=st.booleans())
@settings(max_examples=2, deadline=None, database=None)
def test_hypothesis_varies_active_recreation_cycle(active: bool) -> None:
    state = "ACTIVE" if active else "DISABLED"
    one = _observation(
        "flow-one",
        "flow-one",
        state,
        category="DATA_FLOW",
        fields={
            "source": {
                "source_system": "fictional-a",
                "source_resource_id": "a",
                "target_system": "fictional-b",
                "target_resource_id": "b",
            }
        },
    )
    two = _observation(
        "flow-two",
        "flow-two",
        state,
        category="DATA_FLOW",
        fields={
            "source": {
                "source_system": "fictional-b",
                "source_resource_id": "b",
                "target_system": "fictional-a",
                "target_resource_id": "a",
            }
        },
    )
    findings, _ = analyze_evidence_patterns(_bundle(one, two))
    has_cycle = "RECREATION_CYCLE" in {finding.code for finding in findings}
    assert has_cycle is active


def test_proven_surviving_copy_and_unresolved_conflict_never_certify_complete() -> None:
    surviving_copy = _observation(
        "copy-present", "fictional-backup-copy", "PRESENT", category="BACKUP_ARCHIVE"
    )
    _, survivor_answer = _audit(_bundle(surviving_copy))
    assert survivor_answer.deletion_status is DeletionStatus.INCOMPLETE

    absent = _observation("state-absent", "fictional-profile", "NOT_FOUND")
    present = _observation("state-present", "fictional-profile", "PRESENT")
    context, conflict_answer = _audit(_bundle(absent, present))
    assert context.unresolved_conflicts
    assert conflict_answer.deletion_status is not DeletionStatus.COMPLETE
