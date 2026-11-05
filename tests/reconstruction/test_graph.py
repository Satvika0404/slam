from datetime import UTC, datetime

from conftest import observation, request
from slam.contracts import Activity, EvidenceBundle, ResourceState
from slam.reconstruction.graph import build_dependency_graph


def state(resource: str, category: str, value: str = "PRESENT") -> ResourceState:
    return ResourceState(
        system_id="integration_service",
        resource_id=resource,
        category=category,
        state=value,
        at=datetime(2026, 2, 1, tzinfo=UTC),
    )


def test_active_flow_and_restore_risk_are_surfaced_with_visible_evidence() -> None:
    flow = observation(
        "flow",
        resource="data_flow_1",
        category="DATA_FLOW",
        state="ACTIVE",
        fields={"source": {"source_system": "account_service", "target_system": "search_service"}},
    )
    backup = observation(
        "backup",
        resource="backup_1",
        category="BACKUP_ARCHIVE",
        state="RESTORABLE",
        fields={"source": {"target_system": "account_service"}},
    )
    result = build_dependency_graph(
        request(),
        EvidenceBundle(),
        (flow, backup),
        (state("data_flow_1", "DATA_FLOW", "ACTIVE"), state("backup_1", "BACKUP_ARCHIVE")),
        frozenset({"old@example.test"}),
        "user_1",
    )
    assert result.active_flows[0].evidence_ids == ("evidence_1",)
    assert result.restore_risks[0].relationship == "restore_path"


def test_relevant_activity_claim_creates_edge_but_future_activity_does_not() -> None:
    active = Activity(
        activity_id="activity_1",
        activity_type="SYNC",
        occurred_at=datetime(2026, 1, 20, tzinfo=UTC),
        system_id="search_service",
        resource_id="account_1",
        reported_result="SUCCESS",
        attributes={"source_system": "account_service", "target_system": "search_service"},
    )
    future = active.model_copy(
        update={"activity_id": "activity_2", "occurred_at": datetime(2026, 3, 1, tzinfo=UTC)}
    )
    result = build_dependency_graph(
        request(),
        EvidenceBundle(activities=(future, active)),
        (),
        (state("account_1", "USER_PROFILE"),),
        frozenset({"old@example.test"}),
        "user_1",
    )
    assert [edge.evidence_ids for edge in result.active_flows] == [("activity_1",)]


def test_active_cycle_is_reported_without_unbounded_traversal() -> None:
    one = observation(
        "one",
        resource="data_flow_1",
        category="DATA_FLOW",
        state="ACTIVE",
        fields={"source": {"source_system": "a", "target_system": "b"}},
    )
    two = observation(
        "two",
        resource="data_flow_1",
        category="DATA_FLOW",
        state="ACTIVE",
        fields={"source": {"source_system": "b", "target_system": "a"}},
    )
    result = build_dependency_graph(
        request(),
        EvidenceBundle(),
        (one, two),
        (),
        frozenset({"old@example.test"}),
        "user_1",
    )
    assert any("active cycle" in conflict for conflict in result.conflicts)
