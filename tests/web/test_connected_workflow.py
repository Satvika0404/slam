import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from slam.web import workflow
from slam.web.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "STORAGE", tmp_path / "artifacts")


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
    assert run["request_count"] == 1


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


def test_field_preview_matches_committed_redaction_and_preserves_shared_content(tmp_path):
    path = tmp_path / "support.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE support(id TEXT,email TEXT,body TEXT)")
        db.execute("INSERT INTO support VALUES('m1','pat@example.test','Keep shared context')")
    connection = client.post("/api/workflow/databases", content=path.read_bytes()).json()
    item = client.post(
        f"/api/workflow/databases/{connection['id']}/map",
        json={
            "tables": [
                {
                    "table": "support",
                    "key": "id",
                    "email": "email",
                    "action": "REDACT",
                    "category": "SUPPORT_MESSAGE",
                }
            ]
        },
    ).json()
    events = frames(
        client.post(
            "/api/workflow/runs",
            json={
                "input_id": item["id"],
                "request_text": "Please delete personal data for pat@example.test",
            },
        )
    )
    assert events[-1]["event"] == "run.completed"
    run_id = events[0]["payload"]["run_id"]
    run = client.get(f"/api/workflow/runs/{run_id}").json()
    case_id = run["cases"][0]["case_id"]
    case = client.get(f"/api/workflow/runs/{run_id}/cases/{case_id}").json()
    preview = case["record_previews"][0]
    assert preview["operation"] == "REDACT_RECORD"
    assert "record.row.email" in preview["changed_fields"]
    assert preview["fields"]["record.row.body"] == preview["proposed_fields"]["record.row.body"]
    sandbox = client.post(
        "/api/workflow/sandboxes", json={"run_id": run_id, "case_id": case_id}
    ).json()
    execution = frames(client.post(f"/api/workflow/sandboxes/{sandbox['id']}/execute"))
    snapshot = execution[-1]["payload"]["snapshot"]
    record = snapshot["records"][0]
    assert record["present"] and record["state"] == "REDACTED"
    assert "record.row.email" not in record["fields"]
    assert record["fields"]["record.row.body"] == "Keep shared context"
    assert any(
        c["path"] == "record.row.email" and c["after"] is None
        for c in snapshot["receipts"][0]["field_changes"]
    )


def test_unknown_table_and_non_database_input_are_rejected():
    assert client.post("/api/workflow/databases", content=b"bad").status_code == 422
    assert (
        client.post("/api/workflow/databases/missing/map", json={"tables": []}).status_code == 404
    )


@pytest.mark.parametrize(
    "text",
    [
        "email,resource_id\nnot-an-email,r1\n",
        "email,resource_id\na@example.test,r1,extra\n",
        "email,resource_id\na@example.test\n",
        "email,resource_id\na@example.test,r1\nb@example.test,r1\n",
    ],
)
def test_recovery_never_drops_malformed_or_ambiguous_rows(text):
    response = client.post("/api/workflow/experiments/recovery", json={"csv_text": text})
    assert response.status_code == 200
    assert response.json()["status"] == "unresolved"
    assert response.json()["validated_payload"] is None


def test_connected_request_authorization_and_ambiguous_identity_are_blocked(tmp_path):
    path = tmp_path / "ambiguous.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE profiles(id TEXT,email TEXT,user_id TEXT)")
        db.executemany(
            "INSERT INTO profiles VALUES(?,?,?)",
            [
                ("a", "shared@example.test", "first"),
                ("b", "shared@example.test", "second"),
            ],
        )
    connection = client.post("/api/workflow/databases", content=path.read_bytes()).json()
    mapped = client.post(
        f"/api/workflow/databases/{connection['id']}/map",
        json={
            "tables": [{"table": "profiles", "key": "id", "email": "email", "subject": "user_id"}]
        },
    ).json()
    assert client.post("/api/workflow/runs", json={"input_id": mapped["id"]}).status_code == 422
    assert (
        client.post(
            "/api/workflow/runs",
            json={
                "input_id": mapped["id"],
                "request_text": "delete a@example.test and b@example.test",
            },
        ).status_code
        == 422
    )
    for text, status in [
        ("Please export my data for shared@example.test", "NOT_APPLICABLE"),
        ("Please delete my data for shared@example.test", None),
    ]:
        events = frames(
            client.post("/api/workflow/runs", json={"input_id": mapped["id"], "request_text": text})
        )
        assert events[-1]["event"] == "run.completed"
        run_id = events[0]["payload"]["run_id"]
        run = client.get(f"/api/workflow/runs/{run_id}").json()
        case = run["cases"][0]
        if status:
            assert case["status"] == status
        assert not case["executable"]
        assert (
            client.post(
                "/api/workflow/sandboxes", json={"run_id": run_id, "case_id": case["case_id"]}
            ).status_code
            == 409
        )
