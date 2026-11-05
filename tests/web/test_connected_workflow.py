import json
import sqlite3

from fastapi.testclient import TestClient
from slam.web import workflow
from slam.web.api import app

client = TestClient(app)


def frames(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_connection_request_two_deletions_and_measured_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "STORAGE", tmp_path / "artifacts")
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE customers(id TEXT PRIMARY KEY,email TEXT,name TEXT)")
        db.executemany(
            "INSERT INTO customers VALUES(?,?,?)",
            [
                ("a", "pat@example.test", "Pat"),
                ("b", "pat@example.test", "Pat"),
                ("c", "other@example.test", "Other"),
            ],
        )
    original = path.read_bytes()
    connection = client.post("/api/workflow/databases", content=original).json()
    assert connection["tables"][0]["rows"] == 3
    mapped = client.post(
        f"/api/workflow/databases/{connection['id']}/map",
        json={
            "tables": [{"table": "customers", "key": "id", "email": "email", "action": "DELETE"}]
        },
    ).json()
    events = frames(
        client.post(
            "/api/workflow/runs",
            json={
                "input_id": mapped["id"],
                "request_text": "Please delete all personal data for pat@example.test",
            },
        )
    )
    assert events[-1]["event"] == "run.completed", events[-1]
    run_id = events[0]["payload"]["run_id"]
    run = client.get(f"/api/workflow/runs/{run_id}").json()
    assert len(run["cases"]) == 1
    case_id = run["cases"][0]["case_id"]
    case = client.get(f"/api/workflow/runs/{run_id}/cases/{case_id}").json()
    assert {r["resource_id"] for r in case["context"]["resource_states"]} == {
        "customers/a",
        "customers/b",
    }
    copy = client.post(
        "/api/workflow/sandboxes", json={"run_id": run_id, "case_id": case_id}
    ).json()
    events = frames(client.post(f"/api/workflow/sandboxes/{copy['id']}/execute"))
    assert events[-1]["payload"]["snapshot"]["after"]["answer"]["deletion_status"] == "COMPLETE"
    result = client.post(
        "/api/workflow/experiments/sync",
        json={"sandbox_id": copy["id"], "system_id": "customers", "resource_id": "customers/a"},
    ).json()
    assert result["branches"][0]["before_rows"] == 0
    assert result["branches"][0]["after_rows"] == 1
    assert result["branches"][1]["after_rows"] == 0
    assert result["protected"]
    assert path.read_bytes() == original


def test_header_recovery_has_measured_success_and_failure():
    recovered = client.post(
        "/api/workflow/experiments/recovery",
        json={"csv_text": "Email Address,Record ID\na@example.test,r1\n"},
    ).json()
    assert recovered["status"] == "recovered"
    assert recovered["validated_payload"]["headers"] == ["email", "resource_id"]
    assert recovered["checks_passed"] == 6
    failed = client.post(
        "/api/workflow/experiments/recovery", json={"csv_text": "email,email,resource_id\na,b,r1\n"}
    ).json()
    assert failed["status"] == "unresolved"
    assert failed["promotion"] == "blocked"


def test_unknown_table_and_non_database_input_are_rejected():
    assert client.post("/api/workflow/databases", content=b"bad").status_code == 422
    assert (
        client.post("/api/workflow/databases/missing/map", json={"tables": []}).status_code == 404
    )
