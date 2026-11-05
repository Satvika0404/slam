from pathlib import Path

from fastapi.testclient import TestClient
from slam.web import api
from slam.web.demo import corpus

client = TestClient(api.app)


def test_non_deletion_does_not_pretend_judge_evidence_verify_was_executed(monkeypatch) -> None:
    request, bundle, documents = corpus("demo_024")
    request = request.model_copy(update={"request_text": "Please export a copy of my data."})
    monkeypatch.setattr(api.service, "inputs", lambda *args: (request, bundle, documents))
    view = client.get("/api/cases/demo_024").json()
    assert view["answer"]["deletion_status"] == "NOT_APPLICABLE"
    assert all(stage["status"] == "NOT EVALUATED" for stage in view["stages"])


def test_snapshot_row_provenance_does_not_require_a_manifest_id(monkeypatch) -> None:
    request, bundle, documents = corpus("demo_024")
    identity = bundle.current_identities[0].model_copy(update={"source_id": "identity_row_024"})
    bundle = bundle.model_copy(update={"current_identities": (identity,)})
    monkeypatch.setattr(api.service, "inputs", lambda *args: (request, bundle, documents))
    response = client.get("/api/evidence/identity_row_024", params={"case_id": "demo_024"})
    assert response.status_code == 200
    assert response.json()["locator"] == "Current identity snapshot row / updated_at"
    view = client.get("/api/cases/demo_024").json()
    assert any(
        edge["state"] == "verified" and "identity_row_024" in edge["evidence_ids"]
        for edge in view["identity_edges"]
    )


def test_demo_cutoff_reconstructs_real_state_and_preserves_later_evidence() -> None:
    before = client.get("/api/cases/demo_024").json()
    assert before["answer"]["deletion_status"] == "INCOMPLETE"
    assert any(not event["eligible"] for event in before["events"])
    after = client.get("/api/cases/demo_024", params={"cutoff": "2026-10-21T15:00:00Z"}).json()
    assert after["answer"]["deletion_status"] == "COMPLETE"
    assert all(
        step["phase"] == "VERIFICATION" and step["evidence_id"] for step in after["answer"]["steps"]
    )
    assert all(
        not step["evidence_id"] for step in before["answer"]["steps"] if step["phase"] != "FINDING"
    )


def test_identity_relations_have_inspectable_sources() -> None:
    view = client.get("/api/cases/demo_024").json()
    for edge in view["identity_edges"]:
        assert edge["evidence_ids"]
        for evidence in edge["evidence_ids"]:
            response = client.get(f"/api/evidence/{evidence}", params={"case_id": "demo_024"})
            assert response.status_code == 200
            assert response.json()["content"]
            raw = client.get(f"/api/evidence/{evidence}/raw", params={"case_id": "demo_024"})
            assert raw.status_code == 200


def test_conflict_is_never_certified_complete() -> None:
    view = client.get("/api/cases/demo_026").json()
    assert view["context"]["unresolved_conflicts"]
    assert view["answer"]["deletion_status"] == "INCOMPLETE"
    assert view["answer"]["trace"]["not_certified_because"]
    assert next(s for s in view["stages"] if s["id"] == "evidence")["status"] == "CONFLICT DETECTED"
    exported = client.get("/api/cases/demo_026/export")
    assert exported.status_code == 200 and "INCOMPLETE" in exported.text


def test_live_dataset_failure_is_explicit_and_never_falls_back_to_demo(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(api, "ROOT", tmp_path)
    assert client.get("/api/cases?mode=dataset").status_code == 503


def test_fts_search_and_original_source_and_csv_export() -> None:
    assert (
        "file_replica_01"
        in client.get("/api/cases/demo_024/search", params={"q": "index_024"}).json()
    )
    assert client.get("/api/cases/demo_024/search", params={"q": '" OR *'}).status_code == 200
    raw = client.get("/api/evidence/file_replica_01/raw", params={"case_id": "demo_024"})
    assert '"state": "PRESENT"' in raw.text
    export = client.get("/api/cases/demo_025/export")
    assert export.status_code == 200
    assert export.text.startswith("case_id,deletion_status,steps_json\n")


def test_naive_cutoff_and_unknown_cases_are_rejected() -> None:
    assert client.get("/api/cases/demo_024?cutoff=2026-10-21T15:00:00").status_code == 422
    assert client.get("/api/cases/not-a-case").status_code == 404
