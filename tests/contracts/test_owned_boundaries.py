import inspect
from pathlib import Path

from slam.contracts import AuditRequest, EvidenceBundle
from slam.ingestion import ingest
from slam.planning import plan
from slam.reconstruction import reconstruct


def test_frozen_signatures_are_available() -> None:
    assert tuple(inspect.signature(ingest).parameters) == ("dataset_dir", "cache_dir", "provider")
    assert tuple(inspect.signature(reconstruct).parameters) == ("request", "bundle", "provider")
    assert tuple(inspect.signature(plan).parameters) == ("context",)


def test_ingestion_fails_loudly_instead_of_returning_a_silent_empty_bundle(
    tmp_path: Path,
) -> None:
    # Ingestion is implemented. A dataset with no manifest must surface an error issue,
    # never look like "a dataset with nothing in it".
    bundle = ingest(tmp_path)
    assert bundle.sources == () and bundle.observations == ()
    assert any(issue.severity.value == "error" for issue in bundle.issues)


def test_reconstruction_empty_evidence_does_not_fabricate_context() -> None:
    request = AuditRequest.model_validate_json(
        '{"case_id":"c","email":"x@y.test","requested_at":"2026-01-01T00:00:00Z",'
        '"reported_status":"COMPLETE","reported_at":"2026-01-01T00:00:00Z",'
        '"audit_at":"2026-01-02T00:00:00Z","request_text":"delete"}'
    )
    context = reconstruct(request, EvidenceBundle())
    assert context.subject_id is None
    assert context.identity_links == ()
    assert context.resource_states == ()
    assert context.active_flows == ()
    assert context.restore_risks == ()
    assert context.coverage_issues
