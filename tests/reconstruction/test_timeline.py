from datetime import UTC, datetime

from conftest import observation, request, source
from slam.contracts import EvidenceBundle
from slam.reconstruction.timeline import reconstruct_timeline


def test_future_evidence_is_excluded_and_never_changes_cutoff_state() -> None:
    audit_at = datetime(2026, 2, 1, tzinfo=UTC)
    before = observation("before", state="PRESENT")
    after = observation(
        "after",
        state="DELETED",
        source_id="evidence_2",
        effective_time=datetime(2026, 2, 2, tzinfo=UTC),
    )
    bundle = EvidenceBundle(
        sources=(source(), source("evidence_2", captured_at=datetime(2026, 2, 2, tzinfo=UTC))),
        observations=(after, before),
    )
    result = reconstruct_timeline(
        request(audit_at=audit_at), bundle, frozenset({"old@example.test"}), None
    )
    assert result.states[0].state == "PRESENT"
    assert result.eligible[0].observation_id == before.observation_id
    assert result.excluded_future[0].observation_id == after.observation_id


def test_not_found_is_uncertain_without_snapshot_scope() -> None:
    missing = observation("missing", state="NOT_FOUND")
    result = reconstruct_timeline(
        request(),
        EvidenceBundle(sources=(source(),), observations=(missing,)),
        frozenset({"old@example.test"}),
        None,
    )
    assert result.states[0].state == "NOT_FOUND"
    assert result.states[0].uncertain is True


def test_not_found_with_eligible_snapshot_scope_can_establish_absence() -> None:
    missing = observation("missing", state="NOT_FOUND")
    scope = observation(
        "scope",
        category="SNAPSHOT_SCOPE",
        state="SCOPED",
        email="",
        resource="scope_1",
    )
    result = reconstruct_timeline(
        request(),
        EvidenceBundle(sources=(source(),), observations=(missing, scope)),
        frozenset({"old@example.test"}),
        None,
    )
    assert result.states[0].state == "ABSENT"
    assert result.states[0].uncertain is False


def test_same_resource_across_systems_stays_distinct_and_conflicted() -> None:
    primary = observation("primary", system="account_service", state="DELETED")
    replica = observation("replica", system="reporting_replica", state="PRESENT")
    result = reconstruct_timeline(
        request(),
        EvidenceBundle(sources=(source(),), observations=(primary, replica)),
        frozenset({"old@example.test"}),
        None,
    )
    assert {(state.system_id, state.state) for state in result.states} == {
        ("account_service", "ABSENT"),
        ("reporting_replica", "PRESENT"),
    }
    assert all(state.uncertain for state in result.states)
    assert any("replica" in conflict for conflict in result.conflicts)


def test_duplicate_observations_do_not_duplicate_logical_state() -> None:
    item = observation("same")
    result = reconstruct_timeline(
        request(),
        EvidenceBundle(sources=(source(),), observations=(item, item)),
        frozenset({"old@example.test"}),
        None,
    )
    assert len(result.eligible) == 1
    assert len(result.states) == 1


def test_same_time_conflicting_direct_observations_are_preserved() -> None:
    present = observation("present", state="PRESENT")
    absent = observation("absent", state="DELETED")
    result = reconstruct_timeline(
        request(),
        EvidenceBundle(sources=(source(),), observations=(present, absent)),
        frozenset({"old@example.test"}),
        None,
    )
    assert result.states[0].uncertain is True
    assert result.states[0].conflicting_evidence_ids == ("evidence_1",)
    assert any("conflicting terminal states" in conflict for conflict in result.conflicts)
