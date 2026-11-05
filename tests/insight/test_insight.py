"""Insight layer: no audit leakage into the model, grounded explanations, cross-checked graph."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from slam.config import Settings
from slam.contracts import (
    Activity,
    AuditRequest,
    CaseAnswer,
    CaseContext,
    DeletionStatus,
    Operation,
    Phase,
    RequestIntent,
    ResourceState,
    Step,
    StepState,
)
from slam.insight import explain, graph, patterns, predict
from slam.insight.build import select_for_llm
from slam.insight.facts import FEATURES, CaseFacts, Finding, _claim_features, _Index
from slam.pipeline import AuditedCase
from slam.runtime.fake_provider import FakeModelProvider
from slam.runtime.provider import ModelBudgetError, ModelMalformedResponseError

T0 = datetime(2026, 5, 1, tzinfo=UTC)
SYSTEMS = ["search_service", "integration_service", "account_service", "analytics_platform"]


# ------------------------------------------------ leakage: features read claims only
def _audited(resource_state: str, steps: tuple[Step, ...]) -> AuditedCase:
    request = AuditRequest(
        case_id="case_1",
        email="a@example.test",
        requested_at=T0,
        reported_status="COMPLETE",
        reported_at=T0 + timedelta(days=1),
        audit_at=T0 + timedelta(days=9),
        request_text="please delete my account",
    )
    context = CaseContext(
        request=request,
        request_intent=RequestIntent.DELETION,
        subject_id="user_1",
        evidence_captured_at={"activity_1": T0 + timedelta(days=2)},
        resource_states=(
            ResourceState(
                system_id="search_service",
                resource_id="search_1",
                category="SEARCH_INDEX_ENTRY",
                state=resource_state,
                at=T0 + timedelta(days=8),
            ),
        ),
    )
    answer = CaseAnswer(case_id="case_1", deletion_status=DeletionStatus.COMPLETE, steps=steps)
    return AuditedCase(request=request, context=context, answer=answer)


def _index() -> _Index:
    activity = Activity(
        activity_id="activity_1",
        activity_type="DELETE_RECORD",
        occurred_at=T0 + timedelta(days=2),
        system_id="account_service",
        resource_id="account_1",
        reported_result="PARTIAL",
    )
    return _Index(
        activities={"activity_1": activity},
        source_kind={},
        identity={"user_1": "a@example.test"},
        change_count={"user_1": 0},
    )


def test_features_ignore_resource_states_and_steps() -> None:
    """Two cases with identical claims but opposite audit outcomes get identical features."""

    failing_steps = (
        Step(
            step_no=1,
            phase=Phase.FINDING,
            system_id="search_service",
            resource_id="search_1",
            operation=Operation.REPORT_REMAINING_RECORD,
            state=StepState.PRESENT,
            evidence_id="evidence_1",
        ),
    )
    clean = _claim_features(_audited("ABSENT", ()), _index())
    dirty = _claim_features(_audited("PRESENT", failing_steps), _index())
    assert clean == dirty
    assert len(clean) == len(FEATURES)


def test_feature_names_never_mention_audit_vocabulary() -> None:
    banned = ("finding", "violation", "state", "present", "absent", "status", "verdict")
    assert not [name for name in FEATURES if any(word in name for word in banned)]


# ---------------------------------------------------------------- predictor
def _synthetic(n: int = 120) -> list[CaseFacts]:
    rng = np.random.default_rng(3)
    cases = []
    for i in range(n):
        signal = float(rng.integers(0, 3))
        values = [0.0] * len(FEATURES)
        values[FEATURES.index("treat_partial")] = signal
        values[FEATURES.index("acts_linked")] = float(rng.integers(0, 4))
        failed = rng.random() < 0.2 + 0.3 * signal
        findings = (
            (Finding(1, "REPORT_REMAINING_RECORD", "REMAINING_RECORD", "search_service",
                     f"search_{i}", "SEARCH_INDEX_ENTRY", "evidence_1"),)
            if failed
            else ()
        )
        cases.append(
            CaseFacts(
                case_id=f"case_{i:03d}",
                cohort="evaluation",
                status="INCOMPLETE" if failed else "COMPLETE",
                reported_status="COMPLETE",
                audit_at=T0 + timedelta(hours=i),
                findings=findings,
                steps=(),
                features=tuple(values),
                not_certified_because=(),
            )
        )
    return cases


def test_predictor_is_deterministic_out_of_fold_and_bounded() -> None:
    cases = _synthetic()
    gold = {c.case_id: c.status for c in cases[:20]}
    first, report = predict.train_and_score(cases[20:], cases[:20], gold)
    second, _ = predict.train_and_score(cases[20:], cases[:20], gold)
    assert first.keys() == {c.case_id for c in cases[20:]}
    assert all(0.0 <= risk.p_failure <= 1.0 for risk in first.values())
    assert {k: v.p_failure for k, v in first.items()} == {k: v.p_failure for k, v in second.items()}
    assert report.cv["auc"] > 0.55  # the planted signal is found
    assert "treat_partial" in report.features_used
    assert "lag_request_to_audit_d" not in report.features_used
    assert report.external is not None and report.external["n"] == 20


# ---------------------------------------------------------------- patterns
def _fail(case_id: str, items: list[tuple[str, str]], day: int) -> CaseFacts:
    findings = tuple(
        Finding(n, f"REPORT_{kind}", kind, "search_service", f"r_{case_id}_{n}", cat, "evidence_1")
        for n, (cat, kind) in enumerate(items, 1)
    )
    return CaseFacts(case_id, "evaluation", "INCOMPLETE", "COMPLETE", T0 + timedelta(days=day),
                     findings, (), tuple([0.0] * len(FEATURES)), ())


def test_dbscan_groups_recurring_signatures_and_flags_the_rare_one() -> None:
    common = [("SEARCH_INDEX_ENTRY", "REMAINING_RECORD")]
    other = [("SUPPORT_MESSAGE", "EXPOSED_PII"), ("ANALYTICS_PROFILE", "EXPOSED_PII")]
    rare = [("ACCOUNT_TOMBSTONE", "EXPOSED_PII")]
    cases = [_fail(f"a{i:02d}", common, i) for i in range(40)]
    cases += [_fail(f"b{i:02d}", other, 40 + i) for i in range(8)]
    cases += [_fail("z00", rare, 60)]
    report = patterns.discover(cases, {})
    assert report.assignment["a00"] == report.assignment["a39"] != patterns.NOISE
    assert report.assignment["b00"] == report.assignment["b07"] != report.assignment["a00"]
    assert report.assignment["z00"] == patterns.NOISE
    assert "z00" in report.novel
    assert "a05" not in report.novel  # inside the warm-up window
    again = patterns.discover(cases, {})
    assert again.assignment == report.assignment and again.novel == report.novel


# ---------------------------------------------------------------- explanations
def _payload() -> dict[str, Any]:
    facts = CaseFacts(
        "case_9", "evaluation", "INCOMPLETE", "COMPLETE", T0, (
            Finding(1, "REPORT_REMAINING_RECORD", "REMAINING_RECORD", "search_service",
                    "search_9", "SEARCH_INDEX_ENTRY", "evidence_7"),
        ),
        (
            Step(step_no=1, phase=Phase.FINDING, system_id="search_service", resource_id="search_9",
                 operation=Operation.REPORT_REMAINING_RECORD, state=StepState.PRESENT,
                 evidence_id="evidence_7"),
            Step(step_no=2, phase=Phase.REMEDIATION, system_id="search_service",
                 resource_id="search_9", operation=Operation.DELETE_RECORD,
                 state=StepState.ABSENT, evidence_id=""),
            Step(step_no=3, phase=Phase.VERIFICATION, system_id="search_service",
                 resource_id="search_9", operation=Operation.VERIFY_RECORD_ABSENT,
                 state=StepState.ABSENT, evidence_id=""),
        ),
        tuple([0.0] * len(FEATURES)), (),
    )
    return explain.case_payload(
        facts,
        policy={"SEARCH_INDEX_ENTRY": "DELETE (rule_03)"},
        risk={"p_failure": 0.8, "drivers": []},
        pattern={"id": "P1", "label": "x", "cases": 5, "novel_at_audit": False},
        paths=[["integration_service", "search_service"]],
    )


def _good(payload: dict[str, Any]) -> explain.CaseExplanation:
    return explain.CaseExplanation(
        why_failed="Reported COMPLETE, but evidence_7 shows search_9 present in search_service.",
        risk_drivers=[],
        recreation_risk="integration_service can write to search_service; a risk to check.",
        runbook=[explain.RunbookEntry(step_no=2, action="Delete search_9 in search_service.",
                                      precondition="none",
                                      risk_if_skipped="Record stays reachable.")],
        verification_note="Verification proves search_9 is absent (policy rule_03).",
    )


def test_payload_contains_ids_and_numbers_only() -> None:
    payload = _payload()
    assert set(payload) == {"case_id", "reported_status", "audit_status", "audit_date", "findings",
                            "plan", "risk_model", "pattern", "recreation_paths"}
    text = explain.build_prompt(payload)
    assert "request_text" not in text and "@" not in text
    assert [s["step_no"] for s in payload["plan"]] == [2, 3]  # findings are not in the plan


def test_grounding_accepts_the_facts_and_rejects_inventions() -> None:
    payload = _payload()
    systems = [*SYSTEMS, "support_platform"]
    assert explain.check_grounding(_good(payload), payload, systems) is None
    wrong_steps = _good(payload).model_copy(update={"runbook": []})
    assert "remediation steps" in (explain.check_grounding(wrong_steps, payload, systems) or "")
    invented_id = _good(payload).model_copy(update={"why_failed": "See evidence_99 for details."})
    assert "evidence_99" in (explain.check_grounding(invented_id, payload, systems) or "")
    foreign = _good(payload).model_copy(update={"verification_note": "Check support_platform too."})
    assert "support_platform" in (explain.check_grounding(foreign, payload, systems) or "")


def test_rule_based_text_always_passes_its_own_check() -> None:
    payload = _payload()
    assert explain.check_grounding(explain.rule_based(payload), payload, SYSTEMS) is None


def test_model_reply_is_used_when_grounded_and_replaced_when_not(tmp_path: Path) -> None:
    payload = _payload()
    cache = explain.ExplanationCache(tmp_path / "c.json")
    good, bad = _good(payload), _good(payload).model_copy(update={"runbook": []})

    run = explain.explain_all([payload], ["case_9"], provider=FakeModelProvider([good]),
                              cache=cache, all_systems=SYSTEMS)
    assert run.results["case_9"].source == "llm"

    cache_bad = explain.ExplanationCache(None)
    run = explain.explain_all([payload], ["case_9"], provider=FakeModelProvider([bad]),
                              cache=cache_bad, all_systems=SYSTEMS)
    assert run.results["case_9"].source == "rule-based"
    assert "rejected" in run.results["case_9"].note

    unselected = explain.explain_all([payload], [], provider=FakeModelProvider([good]),
                                     cache=cache_bad, all_systems=SYSTEMS)
    assert unselected.results["case_9"].note == "not selected for a model call"


def test_second_run_is_served_from_the_cache(tmp_path: Path) -> None:
    payload = _payload()
    cache = explain.ExplanationCache(tmp_path / "c.json")
    explain.explain_all([payload], ["case_9"], provider=FakeModelProvider([_good(payload)]),
                        cache=cache, all_systems=SYSTEMS)
    silent = FakeModelProvider([])  # would raise if it were called
    run = explain.explain_all([payload], ["case_9"], provider=silent,
                              cache=explain.ExplanationCache(tmp_path / "c.json"),
                              all_systems=SYSTEMS)
    assert silent.calls == 0 and run.results["case_9"].cache_hit


def test_provider_failures_degrade_to_rule_based_and_a_budget_stop_ends_the_calls() -> None:
    payload = _payload()
    other = {**payload, "case_id": "case_10"}
    flaky = FakeModelProvider([ModelMalformedResponseError("junk")])
    run = explain.explain_all([payload], ["case_9"], provider=flaky,
                              cache=explain.ExplanationCache(None), all_systems=SYSTEMS)
    assert run.results["case_9"].source == "rule-based" and run.stopped is None

    capped = FakeModelProvider([ModelBudgetError("call ceiling reached")])
    run = explain.explain_all([payload, other], ["case_9", "case_10"], provider=capped,
                              cache=explain.ExplanationCache(None), all_systems=SYSTEMS)
    assert capped.calls == 1  # no further call after the ceiling
    assert run.stopped and {r.source for r in run.results.values()} == {"rule-based"}


def test_selection_respects_the_budget_and_is_deterministic() -> None:
    cases = [_fail(f"c{i:03d}", [("SEARCH_INDEX_ENTRY", "REMAINING_RECORD")], i) for i in range(60)]
    report = patterns.discover(cases, {})
    risks = {c.case_id: predict.CaseRisk(c.case_id, 0.5, (), {}, None) for c in cases}
    chosen = select_for_llm(cases, report, risks, 7)
    assert len(chosen) == 7 == len(set(chosen))
    assert chosen == select_for_llm(cases, report, risks, 7)
    assert select_for_llm(cases, report, risks, 0) == []


# ---------------------------------------------------------------- graph
def _topology() -> graph.Topology:
    nodes = {n: {"label": n, "tier": ""} for n in
             ["account_service", "integration_service", "search_service",
              "analytics_platform", "backup_service"]}
    links = (
        graph.Link("account_service", "integration_service", "inferred", "", True, False),
        graph.Link("integration_service", "search_service", "observed", "SYNC_RECORD", True, False),
        graph.Link("integration_service", "analytics_platform", "inferred", "", True, False),
        graph.Link("backup_service", "search_service", "observed", "RESTORE_BACKUP", True, True),
        graph.Link("account_service", "search_service", "observed", "INDEX_RECORD", False, False),
    )
    return graph.Topology(nodes=nodes, links=links)


def test_recreation_paths_follow_active_links_only() -> None:
    nx_graph = graph.NetworkxGraph(_topology())
    assert nx_graph.paths_into("search_service") == [
        ("backup_service", "search_service"),
        ("integration_service", "search_service"),
        ("account_service", "integration_service", "search_service"),
    ]
    assert nx_graph.paths_into("account_service") == []  # nothing active writes to it
    assert nx_graph.blast_radius("account_service") == 3
    assert nx_graph.paths_into("not_a_system") == []


def test_missing_topology_file_names_the_fix(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=re.escape("build_data.py")):
        graph.load_topology(tmp_path / "nope.json")


def test_without_a_server_the_analysis_reports_networkx_and_why() -> None:
    settings = Settings(NEO4J_URI=None)  # type: ignore[call-arg]
    report = graph.analyse(_topology(), ["search_service"], [], settings)
    assert report.engine == "networkx" and report.crosscheck is None
    assert report.neo4j["reachable"] is False and not report.neo4j["configured"]


def test_neo4j_and_networkx_agree_when_a_server_is_configured() -> None:
    settings = Settings()
    if not settings.neo4j_uri or settings.neo4j_password is None:
        pytest.skip("no Neo4j server configured (docker compose --profile graph up -d neo4j)")
    store, status = graph.connect_neo4j(settings)
    if store is None:
        pytest.skip(f"Neo4j not reachable: {status['detail']}")
    try:
        topology = _topology()
        store.load(topology)
        reference = graph.NetworkxGraph(topology)
        for target in topology.nodes:
            assert store.paths_into(target) == reference.paths_into(target)
        for source in topology.nodes:
            assert store.blast_radius(source) == reference.blast_radius(source)
    finally:
        store.close()
