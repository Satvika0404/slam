"""Synthetic-only tests for the bounded development repair loop."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from slam.evaluation.data_quality import analyze_evidence_quality
from slam.evaluation.improvement.candidates import (
    CandidateMetrics,
    ScenarioPrediction,
    evaluate_candidate,
    evaluate_candidate_sets,
    evaluate_patch_in_isolation,
    score_scenarios,
    validate_patch_paths,
)
from slam.evaluation.improvement.failures import FailureRecord, FailureStore
from slam.evaluation.improvement.loop import ImprovementLoop, LoopStage
from slam.evaluation.improvement.recovery import RecoveryAction, RecoveryPolicy, run_recovery
from slam.evaluation.improvement.reporting import (
    ImprovementReport,
    render_markdown,
    write_improvement_report,
)
from slam.evaluation.improvement.scenarios import EventKind, generate_scenario
from slam.ingestion.parsers.base import SourceContext
from slam.ingestion.parsers.json_parser import parse_json


@given(st.integers(min_value=0, max_value=2**31 - 1))
@example(0)
@settings(max_examples=50, deadline=None, database=None)
def test_scenario_generation_is_reproducible_and_has_no_oracle_field(seed: int) -> None:
    first = generate_scenario(seed)
    second = generate_scenario(seed)
    assert first == second
    assert {event.kind for event in first.events} == set(EventKind)
    assert all(event.fictional_subject.startswith("fictional-") for event in first.events)
    assert not {field.name for field in fields(first)} & {"truth", "expected_status", "label"}


@given(
    seed=st.integers(min_value=0, max_value=10_000),
    available=st.integers(min_value=0, max_value=18),
)
@settings(max_examples=20, deadline=None, database=None)
def test_missing_source_variants_remain_visible_as_coverage_gaps(seed: int, available: int) -> None:
    scenario = generate_scenario(seed)
    kept = scenario.bundle.sources[:available]
    partial_bundle = scenario.bundle.model_copy(update={"sources": kept})
    report = analyze_evidence_quality(
        partial_bundle,
        expected_source_ids=tuple(source.source_id for source in scenario.bundle.sources),
    )
    assert report.expected_sources == len(scenario.bundle.sources)
    assert report.accounted_sources == available


@given(data=st.binary(min_size=0, max_size=64))
@settings(max_examples=25, deadline=None, database=None)
def test_corrupt_json_variants_fail_closed_without_invented_facts(data: bytes) -> None:
    context = SourceContext(
        source_id="synthetic-corrupt-json",
        origin="synthetic",
        captured_at=datetime(2025, 1, 1, tzinfo=UTC),
        rel_path="synthetic/corrupt.json",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    parsed = parse_json(context, data)
    assert parsed.status in {"parsed", "partial", "failed"}
    if parsed.status == "failed":
        assert not parsed.facts
        assert parsed.issues


def test_scenario_contains_only_pre_audit_evidence_when_treated_as_visible() -> None:
    scenario = generate_scenario(42)
    assert scenario.request.case_id == scenario.scenario_id
    assert scenario.request.audit_at == scenario.audit_at
    assert len(scenario.bundle.sources) == len(scenario.events)
    visible = tuple(event for event in scenario.events if event.occurred_at <= scenario.audit_at)
    assert len(visible) < len(scenario.events)
    assert all(event.occurred_at <= scenario.audit_at for event in visible)


def test_synthetic_contract_fixture_is_consumable_by_the_audit_without_truth_labels() -> None:
    from slam.planning.engine import plan_case
    from slam.reconstruction import reconstruct

    scenario = generate_scenario(100)
    context = reconstruct(scenario.request, scenario.bundle)
    answer = plan_case(context, scenario.bundle)
    assert answer.case_id == scenario.scenario_id
    assert not hasattr(scenario, "expected_status")


def test_failure_fingerprint_is_stable_and_store_contains_only_sanitized_metadata(
    tmp_path: Path,
) -> None:
    first = FailureRecord.create(
        failure_kind="assertion_failure",
        software_version="0.1.0",
        seed=10,
        diagnostic_codes=("FUTURE_EVIDENCE", "MISSING_PROVENANCE"),
        sanitized_references=("fixture-10",),
    )
    second = FailureRecord.create(
        failure_kind="assertion_failure",
        software_version="0.1.0",
        seed=10,
        diagnostic_codes=("MISSING_PROVENANCE", "FUTURE_EVIDENCE"),
        sanitized_references=("fixture-10",),
    )
    assert first.fingerprint == second.fingerprint
    store = FailureStore(tmp_path / "failures.jsonl")
    store.append(first)
    assert store.records()[0]["fingerprint"] == first.fingerprint
    raw = store.path.read_text(encoding="utf-8")
    assert "api_key" not in raw.casefold()
    assert "exception_text" not in raw
    with pytest.raises(ValueError, match="sanitized"):
        FailureRecord.create(
            failure_kind="parser_failure",
            software_version="0.1.0",
            seed=11,
            diagnostic_codes=("ERROR",),
            sanitized_references=("C:/Users/person/private.txt",),
        )
    with pytest.raises(ValueError, match="sanitized"):
        FailureRecord.create(
            failure_kind="parser_failure",
            software_version="0.1.0",
            seed=11,
            diagnostic_codes=("API_KEY",),
        )


def test_recovery_logs_allowlisted_retries_and_blocks_at_limits() -> None:
    calls = 0

    def flaky(_deadline: float, _remaining_tokens: int) -> tuple[bool, object | None, int]:
        nonlocal calls
        calls += 1
        return calls == 3, "recovered", 1

    policy = RecoveryPolicy(
        allowed_actions=(RecoveryAction.RETRY_PROVIDER,) * 3,
        max_attempts=3,
        time_budget_seconds=5,
        token_budget=3,
    )
    result = run_recovery({RecoveryAction.RETRY_PROVIDER: flaky}, policy)
    assert result.succeeded and not result.blocked and len(result.attempts) == 3
    assert [entry.outcome for entry in result.attempts] == [
        "not_recovered",
        "not_recovered",
        "recovered",
    ]
    blocked = run_recovery(
        {RecoveryAction.RETRY_PROVIDER: lambda _deadline, _tokens: (False, None, 1)},
        RecoveryPolicy(max_attempts=1, token_budget=0),
    )
    assert blocked.blocked and blocked.reason == "token_budget_exhausted"
    assert blocked.attempts[0].token_units == 1
    with pytest.raises(ValueError, match="at most 3"):
        RecoveryPolicy(max_attempts=4)


@given(failures_before_success=st.integers(min_value=0, max_value=5))
@settings(max_examples=12, deadline=None, database=None)
def test_provider_failure_sequences_are_retried_at_most_three_times(
    failures_before_success: int,
) -> None:
    calls = 0

    def provider_retry(_deadline: float, _remaining_tokens: int) -> tuple[bool, str, int]:
        nonlocal calls
        calls += 1
        if calls <= failures_before_success:
            raise TimeoutError("private API_KEY=never-log-this")
        return True, "ok", 0

    result = run_recovery(
        {RecoveryAction.RETRY_PROVIDER: provider_retry},
        RecoveryPolicy(
            allowed_actions=(RecoveryAction.RETRY_PROVIDER,) * 3,
            max_attempts=3,
            time_budget_seconds=2,
        ),
    )
    assert calls <= 3
    assert result.succeeded is (failures_before_success <= 2)
    assert "never-log-this" not in repr(result.attempts)


def test_metrics_acceptance_uses_false_complete_denominators_and_rejects_regression() -> None:
    baseline = CandidateMetrics(
        cases=20,
        false_complete_count=1,
        status_accuracy=0.9,
        step_accuracy=0.8,
        defect_detection_precision=0.7,
        defect_detection_recall=0.75,
        latency_ms=100,
        fixture_set_id="heldout-v1",
        scenario_ids=tuple(f"case-{index:02d}" for index in range(20)),
        regression_count=0,
    )
    better = CandidateMetrics(
        cases=20,
        false_complete_count=0,
        status_accuracy=0.95,
        step_accuracy=0.82,
        defect_detection_precision=0.8,
        defect_detection_recall=0.85,
        latency_ms=120,
        fixture_set_id="heldout-v1",
        scenario_ids=tuple(f"case-{index:02d}" for index in range(20)),
        regression_count=0,
    )
    result = evaluate_candidate(
        baseline=baseline,
        candidate=better,
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
    )
    assert result.accepted
    assert better.false_complete_rate == 0.0
    unmeasured = CandidateMetrics(
        cases=20,
        false_complete_count=0,
        status_accuracy=0.95,
        step_accuracy=0.82,
        defect_detection_precision=0.8,
        defect_detection_recall=0.85,
        latency_ms=120,
        fixture_set_id="heldout-v1",
        scenario_ids=tuple(f"case-{index:02d}" for index in range(20)),
    )
    unmeasured_result = evaluate_candidate(
        baseline=baseline,
        candidate=unmeasured,
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
    )
    assert not unmeasured_result.accepted
    worse = CandidateMetrics(
        cases=20,
        false_complete_count=2,
        status_accuracy=0.96,
        step_accuracy=0.9,
        defect_detection_precision=0.8,
        defect_detection_recall=0.9,
        latency_ms=120,
        fixture_set_id="heldout-v1",
        scenario_ids=tuple(f"case-{index:02d}" for index in range(20)),
    )
    result = evaluate_candidate(
        baseline=baseline,
        candidate=worse,
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
    )
    assert not result.accepted


def test_scorer_keeps_synthetic_oracle_separate_from_participant_evidence() -> None:
    scenarios = (generate_scenario(1), generate_scenario(2))
    # This reference mapping exists only in the test harness and is never attached to scenarios.
    private_truth = {scenarios[0].scenario_id: "INCOMPLETE", scenarios[1].scenario_id: "COMPLETE"}
    predictions = {
        scenarios[0].scenario_id: ScenarioPrediction("INCOMPLETE", ("report",), ("copy",)),
        scenarios[1].scenario_id: ScenarioPrediction("COMPLETE", ("verify",), ()),
    }
    metrics = score_scenarios(
        predictions=predictions,
        expected_statuses=private_truth,
        expected_steps={
            scenarios[0].scenario_id: ("report",),
            scenarios[1].scenario_id: ("verify",),
        },
        expected_defects={scenarios[0].scenario_id: ("copy",), scenarios[1].scenario_id: ()},
        fixture_set_id="dev-fixtures-v1",
        latency_ms=42,
        baseline_predictions={
            scenarios[0].scenario_id: ScenarioPrediction("INCOMPLETE", (), ()),
            scenarios[1].scenario_id: ScenarioPrediction("COMPLETE", ("verify",), ()),
        },
    )
    assert metrics.status_accuracy == 1.0
    assert metrics.step_accuracy == 1.0
    assert metrics.defect_detection_precision == metrics.defect_detection_recall == 1.0
    assert metrics.false_complete_count == 0
    assert metrics.regression_count == 0
    assert not hasattr(scenarios[0], "expected_status")


def test_dev_and_held_out_evaluation_sets_are_disjoint_and_both_gate_acceptance() -> None:
    def metrics(fixture_id: str, case_id: str, false_complete: int) -> CandidateMetrics:
        return CandidateMetrics(
            cases=1,
            false_complete_count=false_complete,
            status_accuracy=1.0,
            step_accuracy=1.0,
            defect_detection_precision=1.0,
            defect_detection_recall=1.0,
            latency_ms=1,
            fixture_set_id=fixture_id,
            scenario_ids=(case_id,),
            regression_count=0,
        )

    suite = evaluate_candidate_sets(
        development_baseline=metrics("dev-v1", "dev-case", 0),
        development_candidate=metrics("dev-v1", "dev-case", 0),
        held_out_baseline=metrics("hold-v1", "hold-case", 0),
        held_out_candidate=metrics("hold-v1", "hold-case", 1),
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
    )
    assert not suite.accepted
    with pytest.raises(ValueError, match="disjoint"):
        evaluate_candidate_sets(
            development_baseline=metrics("dev-v1", "same-case", 0),
            development_candidate=metrics("dev-v1", "same-case", 0),
            held_out_baseline=metrics("hold-v1", "same-case", 0),
            held_out_candidate=metrics("hold-v1", "same-case", 0),
            reproduced_failure_fixed=True,
            checks_passed=True,
            within_budget=True,
            attempt=1,
        )


def test_patch_allowlist_and_disposable_checkout(tmp_path: Path) -> None:
    patch = (
        "--- /dev/null\n+++ b/tests/evaluation/repair_example.txt\n"
        "@@ -0,0 +1 @@\n+synthetic regression fixture\n"
    )
    assert validate_patch_paths(patch) == ("tests/evaluation/repair_example.txt",)
    outside = "--- a/code/slam/contracts.py\n+++ b/code/slam/contracts.py\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(ValueError, match="outside the allowlist"):
        validate_patch_paths(outside)
    traversal = (
        "--- a/tests/evaluation/../../.env\n+++ b/tests/evaluation/../../.env\n"
        "@@ -1 +1 @@\n-a\n+b\n"
    )
    with pytest.raises(ValueError):
        validate_patch_paths(traversal)

    repo = Path(__file__).resolve().parents[2]
    observed: dict[str, object] = {}

    def fixed_runner(checkout: Path, timeout: int) -> tuple[bool, str]:
        observed["checkout"] = checkout
        observed["timeout"] = timeout
        observed["patch_present"] = (checkout / "tests/evaluation/repair_example.txt").exists()
        observed["original_untouched"] = not (repo / "tests/evaluation/repair_example.txt").exists()
        return True, "fixed synthetic checker passed"

    passed, paths, output = evaluate_patch_in_isolation(
        repository=repo,
        patch=patch,
        check_runner=fixed_runner,
    )
    assert passed and paths == ("tests/evaluation/repair_example.txt",)
    assert "passed" in output
    assert observed["patch_present"] is True and observed["original_untouched"] is True
    assert not Path(str(observed["checkout"])).exists()


def test_loop_records_accept_reject_and_enforces_three_attempts(tmp_path: Path) -> None:
    loop = ImprovementLoop()
    for stage in (
        LoopStage.REPRODUCE,
        LoopStage.GENERATE_SCENARIOS,
        LoopStage.PROPOSE_REPAIR,
        LoopStage.EVALUATE,
    ):
        loop.advance(stage)
    result = evaluate_candidate(
        baseline=CandidateMetrics(
            1, 1, 0, 0, 0, 0, 1, fixture_set_id="one-case", scenario_ids=("one",)
        ),
        candidate=CandidateMetrics(
            1,
            0,
            1,
            1,
            1,
            1,
            1,
            fixture_set_id="one-case",
            scenario_ids=("one",),
            regression_count=0,
        ),
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
    )
    loop.record_candidate(result)
    report = ImprovementReport("synthetic", "a" * 64, 2, 1, result.decision, result)
    loop.write_report(report, tmp_path / "result.json", tmp_path / "result.md")
    assert (tmp_path / "result.json").exists()
    assert (tmp_path / "result.md").exists()
    assert loop.history[-2:] == ["accept", "record"]


class RecoveryBudgetMachine(RuleBasedStateMachine):
    """Property state machine: retries remain explicit and bounded for generated failures."""

    def __init__(self) -> None:
        super().__init__()
        self.requested = 0
        self.executed = 0

    @rule(retries=st.integers(min_value=0, max_value=20))
    def run_generated_failure_sequence(self, retries: int) -> None:
        self.requested = retries
        self.executed = 0

        def fail(_deadline: float, _remaining_tokens: int) -> tuple[bool, None, int]:
            self.executed += 1
            return False, None, 0

        actions = (RecoveryAction.RETRY_PROVIDER,) * min(retries, 3)
        result = run_recovery(
            {RecoveryAction.RETRY_PROVIDER: fail},
            RecoveryPolicy(allowed_actions=actions, max_attempts=min(retries, 3)),
        )
        assert result.blocked

    @invariant()
    def no_more_than_three_retries_execute(self) -> None:
        assert self.executed <= 3


TestRecoveryBudgetMachine = RecoveryBudgetMachine.TestCase
TestRecoveryBudgetMachine.settings = settings(database=None)


def test_report_is_reviewable_and_labels_finite_synthetic_results(tmp_path: Path) -> None:
    scenario_ids = tuple(f"synthetic-case-{index}" for index in range(8))
    baseline = CandidateMetrics(
        8,
        1,
        0.75,
        0.7,
        0.5,
        0.6,
        90,
        fixture_set_id="synthetic-v1",
        scenario_ids=scenario_ids,
    )
    candidate = CandidateMetrics(
        8,
        0,
        0.875,
        0.75,
        0.75,
        0.8,
        100,
        fixture_set_id="synthetic-v1",
        scenario_ids=scenario_ids,
        regression_count=0,
    )
    outcome = evaluate_candidate(
        baseline=baseline,
        candidate=candidate,
        reproduced_failure_fixed=True,
        checks_passed=True,
        within_budget=True,
        attempt=1,
        patch_paths=("tests/evaluation/test_fixture.py",),
    )
    report = ImprovementReport(
        "synthetic",
        "a" * 64,
        123,
        1,
        outcome.decision,
        outcome,
        assumptions=("fixed fixture set",),
        unknowns=("real dataset unavailable",),
    )
    text = render_markdown(report)
    assert "1/8" in text and "0/8" in text
    assert "finite-set measurements" in text
    assert "real dataset unavailable" in text
    json_path, markdown_path = tmp_path / "run.json", tmp_path / "run.md"
    write_improvement_report(report, json_path, markdown_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["scenario_label"] == "synthetic"
    assert markdown_path.read_text(encoding="utf-8") == text
