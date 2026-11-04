import json
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from slam.contracts import (
    AuditRequest,
    CaseContext,
    CurrentIdentity,
    EvidenceBundle,
    GraphEdge,
    IdentityChangeEvent,
    Observation,
    RequestIntent,
    SourceRecord,
    SourceSpan,
)
from slam.evaluation.data_quality import (
    analyze_evidence_patterns,
    analyze_evidence_quality,
    estimate_case_coverage,
    render_quality_markdown,
    write_quality_reports,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
OBS_A = "c" * 64
OBS_B = "d" * 64


def source(source_id: str, sha256: str = SHA_A, parse_status: str = "parsed") -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        kind="json",
        origin="test",
        path=f"evidence/{source_id}.json",
        captured_at=NOW,
        sha256=sha256,
        parse_status=parse_status,
    )


def observation(
    observation_id: str,
    state: str,
    source_id: str,
    *,
    system: str = "accounts",
    resource: str = "r-1",
    category: str = "PROFILE",
    at=NOW,
    fields=None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        system_id=system,
        resource_id=resource,
        category=category,
        observed_state=state,
        effective_time=at,
        source_kind="json",
        spans=(SourceSpan(source_id=source_id, json_path="$.record"),),
        fields=fields or {},
    )


def test_quality_report_finds_missing_and_duplicate_sources_conflicts_and_identity_collisions():
    bundle = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_A, "partial"), source("s3", SHA_B, "failed")),
        current_identities=(
            CurrentIdentity(
                user_id="u1",
                name="A",
                email="same@example.test",
                email_normalized="same@example.test",
                phone="+1 (222)",
                email_hash=SHA_A,
                updated_at=NOW,
                source_id="s1",
            ),
            CurrentIdentity(
                user_id="u2",
                name="B",
                email="same@example.test",
                email_normalized="same@example.test",
                phone="1222",
                email_hash=SHA_A,
                updated_at=NOW,
                source_id="s1",
            ),
        ),
        identity_changes=(
            IdentityChangeEvent(
                audit_id="a1",
                user_id="u3",
                field_name="email",
                old_value="same@example.test",
                changed_at=NOW,
                source_id="s1",
            ),
        ),
        observations=(
            observation(OBS_A, "PRESENT", "s1"),
            observation(OBS_B, "ABSENT", "s1"),
        ),
    )

    report = analyze_evidence_quality(bundle, expected_source_ids=("s1", "s2", "missing"))

    assert report.expected_sources == 3
    assert report.accounted_sources == 2
    assert report.source_accounting_fraction == 2 / 3
    assert report.parsed_sources == 1
    assert report.partial_sources == 1
    assert report.failed_sources == 0
    assert report.duplicate_content_groups == 1
    assert report.conflicting_observation_groups == 1
    assert report.identity_collision_groups >= 1
    assert {issue.code for issue in report.issues} >= {
        "MANIFEST_SOURCE_MISSING",
        "DUPLICATE_SOURCE_CONTENT",
        "CONFLICTING_RESOURCE_OBSERVATIONS",
        "IDENTIFIER_LINKED_TO_MULTIPLE_USERS",
    }
    assert "IDENTITY_COLLISION" in {finding.code for finding in report.findings}


def test_quality_report_detects_unresolved_observation_provenance():
    bundle = EvidenceBundle(
        sources=(source("s1"),),
        observations=(observation(OBS_A, "PRESENT", "not-in-source-inventory"),),
    )
    report = analyze_evidence_quality(bundle)
    assert report.observation_provenance_fraction == 0.0
    assert any(issue.code == "OBSERVATION_SOURCE_UNRESOLVED" for issue in report.issues)


def test_case_coverage_is_an_explicit_proxy_not_probability():
    request = AuditRequest(
        case_id="case_1",
        email="a@example.test",
        requested_at=NOW,
        reported_status="COMPLETE",
        reported_at=NOW,
        audit_at=NOW,
        request_text="delete my account",
    )
    context = CaseContext(
        request=request,
        request_intent=RequestIntent.DELETION,
        subject_id="u1",
        eligible_observation_ids=(OBS_A,),
        coverage_issues=("some parser failed",),
    )
    estimate = estimate_case_coverage(context)
    assert estimate.dimensions_checked == 6
    assert estimate.dimensions_supported == 4
    assert estimate.coverage_fraction == 4 / 6
    assert "no_declared_coverage_gaps" in estimate.missing_or_uncertain_dimensions
    assert estimate.interpretation.startswith("evidence coverage proxy")


def test_diagnostics_detect_planted_defects_and_report_expected_codes():
    # Independently specified positive oracle: one conflict, duplicate bytes, dangling
    # provenance, unaccounted manifest source, an active edge and an active cycle.
    a = observation(OBS_A, "PRESENT", "s1")
    b = observation(OBS_B, "ABSENT", "s1")
    edge1 = observation(
        "e" * 64,
        "ACTIVE",
        "s2",
        resource="flow-1",
        category="DATA_FLOW",
        fields={
            "source": {
                "source_system": "accounts",
                "source_resource_id": "r-1",
                "target_system": "warehouse",
                "target_resource_id": "copy-1",
            }
        },
    )
    edge2 = observation(
        "f" * 64,
        "ACTIVE",
        "s3",
        system="warehouse",
        resource="flow-2",
        category="DATA_FLOW",
        fields={
            "source": {
                "source_system": "warehouse",
                "source_resource_id": "copy-1",
                "target_system": "accounts",
                "target_resource_id": "r-1",
            }
        },
    )
    orphan = observation("9" * 64, "PRESENT", "missing-source", resource="unlinked")
    bundle = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_A), source("s3", "c" * 64)),
        observations=(a, b, edge1, edge2, orphan, edge1),
    )
    findings, impact = analyze_evidence_patterns(
        bundle, expected_source_ids=("s1", "s2", "s3", "manifest-only")
    )
    codes = [finding.code for finding in findings]
    expected = {
        "INCOMPATIBLE_OBSERVATIONS",
        "DUPLICATE_CONTENT",
        "MISSING_PROVENANCE",
        "UNACCOUNTED_SOURCE",
        "ACTIVE_RECREATION_PATH",
        "RECREATION_CYCLE",
        "DUPLICATE_FACT",
    }
    assert set(codes) >= expected
    assert len({item.stable_id for item in findings}) == len(findings)
    assert all(item.detection_rule_version == "1.0.0" for item in findings)
    assert impact.evidence_coverage_gaps


def test_replica_and_temporal_differences_are_not_conflicts():
    bundle = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_B), source("s3", "c" * 64)),
        observations=(
            observation(OBS_A, "PRESENT", "s1", system="primary"),
            observation(OBS_B, "ABSENT", "s2", system="replica"),
            observation("e" * 64, "ABSENT", "s3", system="primary", at=NOW.replace(day=2)),
            observation("8" * 64, "ABSENT", "s3", system="primary", fields={"scope": "regional"}),
        ),
    )
    findings, _ = analyze_evidence_patterns(bundle)
    assert "INCOMPATIBLE_OBSERVATIONS" not in {item.code for item in findings}


def test_reports_are_deterministic_and_include_rule_and_impact(tmp_path):
    bundle = EvidenceBundle(
        sources=(source("s1"),),
        observations=(
            observation(OBS_A, "PRESENT", "s1"),
            observation(OBS_B, "ABSENT", "s1"),
        ),
    )
    first = analyze_evidence_quality(bundle)
    second = analyze_evidence_quality(bundle)
    assert first.to_dict() == second.to_dict()
    assert render_quality_markdown(first) == render_quality_markdown(second)
    write_quality_reports(first, tmp_path / "a.json", tmp_path / "a.md")
    write_quality_reports(second, tmp_path / "b.json", tmp_path / "b.md")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    assert (tmp_path / "a.md").read_bytes() == (tmp_path / "b.md").read_bytes()
    assert "not a probability" in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_finding_order_is_independent_of_input_order():
    first = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_B)),
        observations=(
            observation(OBS_A, "PRESENT", "s1"),
            observation(OBS_B, "ABSENT", "s2"),
        ),
    )
    second = EvidenceBundle(
        sources=tuple(reversed(first.sources)),
        observations=tuple(reversed(first.observations)),
    )
    first_findings, _ = analyze_evidence_patterns(first)
    second_findings, _ = analyze_evidence_patterns(second)
    assert first_findings == second_findings


def test_checked_in_report_examples_match_synthetic_fixture():
    captured_at = datetime(2026, 1, 1, tzinfo=UTC)
    source_record = SourceRecord(
        source_id="synthetic-a",
        kind="json",
        origin="fixture",
        path="synthetic/a.json",
        captured_at=captured_at,
        sha256=SHA_A,
        parse_status="parsed",
    )

    def example_observation(observation_id: str, state: str) -> Observation:
        return Observation(
            observation_id=observation_id * 64,
            system_id="accounts",
            resource_id="synthetic-user",
            category="PROFILE",
            observed_state=state,
            effective_time=captured_at,
            source_kind="json",
            spans=(SourceSpan(source_id="synthetic-a", json_path="$.record"),),
        )

    report = analyze_evidence_quality(
        EvidenceBundle(
            sources=(source_record,),
            observations=(
                example_observation("1", "PRESENT"),
                example_observation("2", "ABSENT"),
            ),
        )
    )
    examples = Path(__file__).parent / "examples"
    assert (
        json.loads((examples / "data_quality_report.json").read_text(encoding="utf-8"))
        == report.to_dict()
    )
    assert (examples / "data_quality_report.md").read_text(
        encoding="utf-8"
    ) == render_quality_markdown(report)


def test_run_writes_diagnostic_reports_next_to_output(tmp_path, monkeypatch):
    import slam.pipeline as pipeline

    requests_file = tmp_path / "requests.csv"
    requests_file.write_text(
        "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "ingest", lambda *args, **kwargs: EvidenceBundle())
    monkeypatch.setattr(
        pipeline,
        "answer_cases",
        lambda requests, bundle, **kwargs: ([], {}),
    )
    summary = pipeline.run(
        tmp_path,
        tmp_path / "result.csv",
        requests_file=requests_file,
    )
    assert summary.diagnostic_json_path is not None
    assert summary.diagnostic_markdown_path is not None
    assert summary.diagnostic_json_path.is_file()
    assert summary.diagnostic_markdown_path.is_file()


def test_synthetic_oracle_precision_recall_and_cost_measurement():
    bundle = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_B)),
        observations=(
            observation(OBS_A, "PRESENT", "s1"),
            observation(OBS_B, "ABSENT", "s1"),
            observation("e" * 64, "PRESENT", "s2", system="replica"),
        ),
    )
    expected = {"INCOMPATIBLE_OBSERVATIONS"}
    tracemalloc.start()
    started = perf_counter()
    findings, _ = analyze_evidence_patterns(bundle)
    elapsed = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    observed = {item.code for item in findings}
    true_positive = len(expected & observed)
    false_positive = len(observed - expected)
    false_negative = len(expected - observed)
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    )
    assert precision == 1.0
    assert recall == 1.0
    assert false_positive == 0
    assert elapsed >= 0 and peak >= 0  # measured for delivery-note reporting
    print(
        "synthetic diagnostics: "
        f"precision={precision:.3f} recall={recall:.3f} false_positives={false_positive} "
        f"runtime_ms={elapsed * 1000:.3f} peak_bytes={peak}"
    )


def test_identity_collision_requires_overlapping_validity_intervals():
    bundle = EvidenceBundle(
        sources=(source("s1"), source("s2", SHA_B)),
        current_identities=(
            CurrentIdentity(
                user_id="u1",
                name="A",
                email="same@example.test",
                email_normalized="same@example.test",
                phone="111",
                email_hash=SHA_A,
                updated_at=NOW.replace(day=3),
                source_id="s1",
            ),
            CurrentIdentity(
                user_id="u2",
                name="B",
                email="other@example.test",
                email_normalized="other@example.test",
                phone="222",
                email_hash=SHA_B,
                updated_at=NOW.replace(day=3),
                source_id="s2",
            ),
        ),
        identity_changes=(
            IdentityChangeEvent(
                audit_id="a1",
                user_id="u2",
                field_name="email",
                old_value="same@example.test",
                new_value="other@example.test",
                changed_at=NOW.replace(day=2),
                source_id="s2",
            ),
        ),
    )
    findings, _ = analyze_evidence_patterns(bundle)
    # u1 starts owning the value after u2 stopped using it, so no overlap.
    assert "IDENTITY_COLLISION" not in {item.code for item in findings}


def test_future_evidence_and_unknown_graph_endpoints_are_reported():
    from slam.contracts import ResourceState

    request = AuditRequest(
        case_id="c1",
        email="a@example.test",
        requested_at=NOW,
        reported_status="COMPLETE",
        reported_at=NOW,
        audit_at=NOW,
        request_text="delete my account",
    )
    context = CaseContext(
        request=request,
        request_intent=RequestIntent.DELETION,
        excluded_future_observation_ids=(OBS_A,),
        resource_states=(
            ResourceState(
                system_id="accounts", resource_id="r1", category="PROFILE", state="PRESENT", at=NOW
            ),
        ),
        active_flows=(
            GraphEdge(
                source="system:unknown",
                target="resource:warehouse:r1",
                relationship="data_flow",
                evidence_ids=("future-source",),
                active=True,
            ),
        ),
    )
    future_source = source("future-source").model_copy(update={"captured_at": NOW.replace(day=2)})
    future_observation = observation(OBS_A, "PRESENT", "future-source", at=NOW.replace(day=2))
    findings, _ = analyze_evidence_patterns(
        EvidenceBundle(sources=(future_source,), observations=(future_observation,)),
        contexts=(context,),
    )
    assert {"FUTURE_EVIDENCE", "UNKNOWN_GRAPH_ENDPOINT", "ACTIVE_RECREATION_PATH"} <= {
        item.code for item in findings
    }
    _, impact = analyze_evidence_patterns(
        EvidenceBundle(sources=(future_source,), observations=(future_observation,)),
        contexts=(context,),
    )
    assert impact.directly_affected_cases == ("c1",)
