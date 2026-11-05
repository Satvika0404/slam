import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slam.reconstruction.request_intent import IntentProposal
from slam.runtime.events import emit, observe
from slam.runtime.fake_provider import FakeModelProvider
from slam.runtime.metering import UsageLedger
from slam.runtime.provider import ModelBudgetError
from slam.web import api
from slam.web.live import ObservedProvider

client = TestClient(api.app)


def test_actual_provider_metadata_and_call_limits_are_observed_without_prompts():
    provider = FakeModelProvider([{"intent": "DELETION", "supporting_excerpt": "delete"}])
    ledger = UsageLedger()
    wrapped = ObservedProvider(provider, ledger, 1)
    events = []
    with observe(lambda kind, payload: events.append((kind, payload))):
        result = wrapped.generate(
            prompt="secret-request-content", prompt_version="test-v1", response_model=IntentProposal
        )
        with pytest.raises(ModelBudgetError):
            wrapped.generate(
                prompt="secret-request-content",
                prompt_version="test-v1",
                response_model=IntentProposal,
            )
    assert result.metadata.request_id == "fake-1"
    assert [e[0] for e in events] == ["model.started", "model.completed", "model.blocked"]
    assert ledger.summary()["actual_calls"] == 1 and provider.calls == 1
    assert "secret-request-content" not in json.dumps(events)


def run(**body):
    response = client.post("/api/runs/stream", json=body)
    assert response.status_code == 200
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_real_run_emits_ordered_events_and_the_same_engine_answer():
    expected = client.get("/api/cases/demo_024").json()
    events = run(case_id="demo_024")
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert [e["elapsed_ms"] for e in events] == sorted(e["elapsed_ms"] for e in events)
    stages = [e["payload"]["stage"] for e in events if e["event"] == "stage.started"]
    assert stages == [
        "ingestion",
        "linking",
        "intent",
        "identity",
        "ownership",
        "timeline",
        "graph",
        "planning",
        "validation",
    ]
    final = events[-1]
    assert final["event"] == "run.completed"
    assert final["payload"]["answers"][0] == expected["answer"]
    assert final["payload"]["output_csv"].startswith("case_id,deletion_status,steps_json\n")
    assert final["payload"]["usage"]["actual_calls"] == 0
    validated = next(
        e
        for e in events
        if e["event"] == "stage.completed" and e["payload"].get("stage") == "validation"
    )
    assert validated["payload"]["case_csv"] == final["payload"]["output_csv"]
    assert not any(e["event"].startswith("model.") for e in events)
    identity = next(
        e
        for e in events
        if e["payload"].get("stage") == "identity" and e["event"] == "stage.completed"
    )
    assert {e["id"] for e in identity["payload"]["snapshot"]["identity_edges"]}.issubset(
        {e["id"] for e in expected["identity_edges"]}
    )
    assert identity["payload"]["snapshot"]["answer"]["deletion_status"] is None
    assert not identity["payload"]["snapshot"]["answer"]["ready_for_export"]


def test_uncertain_and_batch_runs_never_certify_complete():
    single = run(case_id="demo_026")[-1]["payload"]
    assert single["answers"][0]["deletion_status"] == "INCOMPLETE"
    assert single["answers"][0]["trace"]["not_certified_because"]
    batch = run(scope="all")[-1]["payload"]
    assert batch["processed"] == 3
    assert batch["output_csv"].startswith("case_id,deletion_status,steps_json")
    assert [a["case_id"] for a in batch["answers"]] == ["demo_024", "demo_025", "demo_026"]


def test_non_deletion_skips_unexecuted_timeline_and_graph(monkeypatch):
    from slam.web.demo import corpus

    request, bundle, documents = corpus("demo_024")
    request = request.model_copy(update={"request_text": "Please export a copy of my data."})
    monkeypatch.setattr("slam.web.live.corpus", lambda key: (request, bundle, documents))
    events = run()
    skipped = {e["payload"]["stage"] for e in events if e["event"] == "stage.skipped"}
    assert skipped == {"ownership", "timeline", "graph"}
    assert not any(
        e["event"] == "stage.started" and e["payload"].get("stage") in skipped for e in events
    )
    assert events[-1]["payload"]["answers"][0]["deletion_status"] == "NOT_APPLICABLE"


def test_missing_dataset_and_invalid_cutoff_are_explicit(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api, "ROOT", tmp_path)
    events = run(mode="dataset")
    assert events[-1]["event"] == "run.failed"
    assert events[-1]["payload"]["error_type"] == "FileNotFoundError"
    assert not any(e["event"] == "run.completed" for e in events)
    assert (
        client.post("/api/runs/stream", json={"cutoff": "2026-10-21T08:00:00"}).status_code == 422
    )
    assert (
        client.post(
            "/api/runs/stream", json={"scope": "all", "cutoff": "2026-10-21T08:00:00Z"}
        ).status_code
        == 422
    )


def test_model_is_opt_in_and_configuration_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("SLAM_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-must-never-appear")
    response = client.post("/api/runs/stream", json={"use_model": True})
    assert response.status_code == 422
    info = client.get("/api/runtime")
    assert not info.json()["model_available"]
    assert "secret-must-never-appear" not in info.text + response.text


def test_observers_are_isolated_across_threads_and_reset_after_use():
    def worker(name):
        received = []
        with observe(lambda kind, payload: received.append((kind, payload))):
            emit(name, source=name)
        emit("after_observer_removed")
        return received

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(worker, ["one", "two"]))
    assert a == [("one", {"source": "one"})] and b == [("two", {"source": "two"})]


def test_relationship_history_and_sources_do_not_claim_entity_deletion():
    view = client.get("/api/cases/demo_024").json()
    historical = next(e for e in view["identity_edges"] if e["relationship"] == "historical_email")
    assert historical["lifecycle_event"]["kind"] == "ended"
    assert historical["lifecycle_event"]["at"] == historical["valid_to"]
    assert historical["evidence"][0]["origin"] == "Identity audit log"
    assert historical["evidence"][0]["eligible"]
    assert all(
        e["lifecycle_event"] is None or e["lifecycle_event"]["kind"] != "deleted"
        for e in view["identity_edges"]
    )
    assert all("entity_state" not in n for n in view["identity_nodes"])
