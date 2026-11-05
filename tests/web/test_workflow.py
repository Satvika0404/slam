"""Evidence-bound, input-immutable workflow and actual isolated SQLite execution."""

import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from slam.contracts import (
    AuditRequest,
    CaseContext,
    CurrentIdentity,
    EvidenceBundle,
    GraphEdge,
    Observation,
    PolicyRule,
    ResourceState,
    SourceRecord,
    SourceSpan,
)
from slam.planning.engine import plan_case
from slam.web import remediation, workflow
from slam.web.api import app

client = TestClient(app)
AT = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "STORAGE", tmp_path / "artifacts")
    workflow.RUNS.clear()
    workflow.INPUTS.clear()
    remediation.SANDBOXES.clear()
    yield
    workflow.RUNS.clear()
    workflow.INPUTS.clear()
    remediation.SANDBOXES.clear()


def frames(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def input_zip(unsafe=False, alias_header=False):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        if unsafe:
            archive.writestr("../../outside.txt", "invalid")
        tables = {
            "deletion_requests.csv": [
                (
                    "case_id",
                    "email",
                    "requested_at",
                    "reported_status",
                    "reported_at",
                    "audit_at",
                    "request_text",
                ),
                (
                    "request_a",
                    "pat@example.test",
                    "2026-10-01T00:00:00Z",
                    "COMPLETE",
                    "2026-10-02T00:00:00Z",
                    "2026-10-04T00:00:00Z",
                    "Please delete my account.",
                ),
            ],
            "user_identities.csv": [
                ("user_id", "name", "email", "phone", "email_hash", "updated_at"),
                (
                    "user_1",
                    "Pat",
                    "pat@example.test",
                    "+155501001",
                    "a" * 64,
                    "2026-10-01T00:00:00Z",
                ),
            ],
            "user_audit_log.csv": [
                ("audit_id", "user_id", "event_time", "field_name", "old_value", "new_value")
            ],
            "system_activity.csv": [
                (
                    "activity_id",
                    "event_time",
                    "event_type",
                    "source_system",
                    "target_system",
                    "resource_id",
                    "reported_result",
                    "details",
                )
            ],
            "deletion_rules.csv": [
                ("rule_id", "data_category", "condition", "required_action"),
                ("rule_1", "USER_PROFILE", "Always", "DELETE"),
            ],
            "evidence_files.csv": [
                ("file_id", "file_path", "origin", "captured_at"),
                ("file_1", "evidence/account.json", "account_service", "2026-10-03T00:00:00Z"),
            ],
        }
        for name, rows in tables.items():
            if alias_header and name == "user_identities.csv":
                rows[0] = tuple(("contact" if alias_header == "unsupported" else "Email Address") if field == "email" else field for field in rows[0])
            text = io.StringIO(newline="")
            csv.writer(text).writerows(rows)
            archive.writestr("dataset/" + name, text.getvalue())
        archive.writestr(
            "dataset/evidence/account.json",
            json.dumps(
                {
                    "records": [
                        {
                            "resource_id": "account_1",
                            "record_type": "USER_PROFILE",
                            "system": "account_service",
                            "result": "PRESENT",
                            "recorded_at": "2026-10-03T00:00:00Z",
                            "user_id": "user_1",
                            "email": "pat@example.test",
                        }
                    ]
                }
            ),
        )
    return content.getvalue()


def test_one_uploaded_input_is_pinned_to_every_case_and_export():
    uploaded = client.post(
        "/api/workflow/input", content=input_zip(), headers={"Content-Type": "application/zip"}
    )
    assert uploaded.status_code == 200, uploaded.text
    item = uploaded.json()
    assert item["requests"] == item["sources"] == 1
    events = frames(client.post("/api/workflow/runs", json={"input_id": item["id"]}))
    assert events[-1]["event"] == "run.completed", events
    run_id = events[0]["payload"]["run_id"]
    assert events[0]["payload"]["input"]["fingerprint"] == item["fingerprint"]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    view = client.get(f"/api/workflow/runs/{run_id}/cases/request_a").json()
    assert view["mode"] == "dataset"
    assert view["answer"]["deletion_status"] == "INCOMPLETE"
    assert client.get(f"/api/workflow/runs/{run_id}/export").status_code == 200
    assert client.get(f"/api/workflow/runs/{run_id}/evidence/file_1").json()["id"] == "file_1"
    assert client.get(f"/api/workflow/runs/{run_id}/evidence/unknown").status_code == 404
    # Changing the bytes invalidates this input instead of quietly mixing data between views.
    root = workflow.INPUTS[item["id"]].root
    (root / "evidence/account.json").write_text("{}")
    assert client.post("/api/workflow/runs", json={"input_id": item["id"]}).status_code == 409


def test_header_parser_recovers_during_the_actual_audit_without_source_changes():
    item = client.post("/api/workflow/input", content=input_zip(alias_header=True)).json()
    root = workflow.INPUTS[item["id"]].root
    original = (root / "user_identities.csv").read_bytes()
    events = frames(client.post("/api/workflow/runs", json={"input_id": item["id"]}))
    assert events[-1]["event"] == "run.completed"
    recovery = next(e["payload"] for e in events if e["event"] == "recovery.completed")
    assert recovery["status"] == "recovered"
    assert recovery["component"] == "user_identities.csv"
    assert recovery["attempts"][0]["outcome"] == "recovered"
    assert recovery["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert recovery["source_sha256"] != recovery["recovered_sha256"]
    assert not recovery["promoted"]
    assert (root / "user_identities.csv").read_bytes() == original
    run_id = events[0]["payload"]["run_id"]
    run = client.get(f"/api/workflow/runs/{run_id}").json()
    assert run["intelligence"]["recoveries"][0]["status"] == "recovered"


def test_unsupported_parser_header_stays_unresolved_and_never_reaches_execution():
    item = client.post("/api/workflow/input", content=input_zip(alias_header="unsupported")).json()
    root = workflow.INPUTS[item["id"]].root
    original = (root / "user_identities.csv").read_bytes()
    events = frames(client.post("/api/workflow/runs", json={"input_id": item["id"]}))
    assert events[-1]["event"] == "run.failed"
    recovery = next(e["payload"] for e in events if e["event"] == "recovery.completed")
    assert recovery["status"] == "unresolved"
    assert recovery["recovered_sha256"] is None
    assert not any(e["event"] == "case.completed" for e in events)
    assert (root / "user_identities.csv").read_bytes() == original


def test_upload_rejects_traversal_before_extracting(tmp_path):
    result = client.post("/api/workflow/input", content=input_zip(unsafe=True))
    assert result.status_code == 422
    assert not (tmp_path / "outside.txt").exists()
    assert client.post("/api/workflow/input", content=b"not a zip").status_code == 422


def prepared_run(tmp_path: Path, *, conflict=False, non_deletion=False):
    from slam.contracts import RequestIntent

    source = SourceRecord(
        source_id="proof",
        kind="json",
        origin="test",
        path="evidence.json",
        captured_at=AT,
        sha256="b" * 64,
        parse_status="parsed",
    )
    request = AuditRequest(
        case_id="request_1",
        email="pat@example.test",
        requested_at=AT,
        reported_status="COMPLETE",
        reported_at=AT,
        audit_at=AT,
        request_text="Delete my personal data",
    )
    identity = CurrentIdentity(
        user_id="user_1",
        name="Pat Example",
        email=request.email,
        email_normalized=request.email,
        phone="+155501001",
        email_hash="a" * 64,
        updated_at=AT,
        source_id="proof",
    )
    kinds = [
        ("account_service", "account_1", "USER_PROFILE", "PRESENT", "DELETE"),
        ("integration_service", "data_flow_1", "DATA_FLOW", "ACTIVE", "RETAIN"),
        ("backup_service", "backup_1", "BACKUP_ARCHIVE", "RESTORABLE", "RETAIN"),
        ("support_platform", "support_1", "SUPPORT_MESSAGE", "IDENTIFIABLE", "REDACT"),
        ("analytics_platform", "analytics_1", "ANALYTICS_PROFILE", "IDENTIFIABLE", "ANONYMIZE"),
        ("security_service", "audit_record_1", "SECURITY_AUDIT_LOG", "PRESENT", "RETAIN"),
    ]
    observations = tuple(
        Observation(
            observation_id=f"{i:064x}",
            subject_hints=("user_1",),
            system_id=system,
            resource_id=resource,
            category=category,
            observed_state=state,
            effective_time=AT,
            source_kind="json",
            identifiers={"email": request.email},
            fields={
                "source": {
                    "email": request.email,
                    "user_id": "user_1",
                    "message": "Contact pat@example.test",
                }
            },
            spans=(SourceSpan(source_id="proof", json_path=f"$.rows[{i}]"),),
        )
        for i, (system, resource, category, state, _) in enumerate(kinds)
    )
    rules = tuple(
        PolicyRule(rule_id=f"r{i}", category=category, required_action=action)
        for i, (_, _, category, _, action) in enumerate(kinds)
    )
    bundle = EvidenceBundle(
        sources=(source,),
        observations=observations,
        policy_rules=rules,
        current_identities=(identity,),
    )
    context = CaseContext(
        request=request,
        request_intent=RequestIntent.NON_DELETION if non_deletion else RequestIntent.DELETION,
        subject_id="user_1",
        policy_rules=rules,
        resource_states=tuple(
            ResourceState(
                system_id=system,
                resource_id=resource,
                category=category,
                state=state,
                at=AT,
                supporting_evidence_ids=("proof",),
            )
            for system, resource, category, state, _ in kinds
        ),
        eligible_observation_ids=tuple(o.observation_id for o in observations),
        evidence_captured_at={"proof": AT},
        active_flows=(
            GraphEdge(
                source="resource:integration_service:data_flow_1",
                target="resource:account_service:account_1",
                relationship="sync",
                evidence_ids=("proof",),
                active=True,
            ),
        ),
        restore_risks=(
            GraphEdge(
                source="resource:backup_service:backup_1",
                target="resource:account_service:account_1",
                relationship="restore",
                evidence_ids=("proof",),
                active=True,
            ),
        ),
        unresolved_conflicts=("conflicting source",) if conflict else (),
    )
    item = workflow.Input("input_1", tmp_path, "Fictional test input", "c" * 64, 1, 1, {"json": 1})
    run = workflow.Run(
        "run_1",
        item,
        status="completed",
        bundle=bundle,
        requests={request.case_id: request},
        contexts={request.case_id: context},
        answers={request.case_id: plan_case(context, bundle)},
    )
    workflow.RUNS[run.id] = run
    return run


def test_real_deletion_scrubbing_flow_controls_and_fresh_policy_verification(tmp_path):
    run = prepared_run(tmp_path)
    original = run.answers["request_1"].model_dump_json()
    sandbox = remediation.create_sandbox(run, "request_1")
    assert len(sandbox.actions) == 5
    assert sandbox.actions[0]["operation"] == "DISABLE_DATA_FLOW"
    assert sandbox.actions[1]["operation"] == "BLOCK_RESTORE"
    initial = sandbox.database.read_bytes()
    events = frames(client.post(f"/api/workflow/sandboxes/{sandbox.id}/execute"))
    assert events[-1]["event"] == "run.completed", events
    assert sandbox.database.read_bytes() != initial
    assert remediation.read_record(sandbox, "account_service", "account_1") is None
    retained = remediation.read_record(sandbox, "security_service", "audit_record_1")
    assert (
        retained is not None and retained["payload"]["identifiers"]["email"] == "pat@example.test"
    )
    for system, resource in [
        ("support_platform", "support_1"),
        ("analytics_platform", "analytics_1"),
    ]:
        assert "pat@example.test" not in json.dumps(
            remediation.read_record(sandbox, system, resource)
        )
    assert (
        remediation.read_record(sandbox, "integration_service", "data_flow_1")["payload"]["enabled"]
        is False
    )
    assert (
        remediation.read_record(sandbox, "backup_service", "backup_1")["payload"]["restore_allowed"]
        is False
    )
    assert sandbox.after["answer"]["deletion_status"] == "COMPLETE"
    assert sandbox.after["remaining_flows"] == sandbox.after["remaining_restores"] == 0
    assert all(a["status"] == "verified" for a in sandbox.actions)
    assert run.answers["request_1"].model_dump_json() == original
    assert len(sandbox.receipts) == 5
    # Idempotent repeat: no second deletion or duplicate action receipt.
    frames(client.post(f"/api/workflow/sandboxes/{sandbox.id}/execute"))
    assert len(sandbox.receipts) == 5
    assert client.get(
        f"/api/workflow/sandboxes/{sandbox.id}/evidence/{sandbox.receipts[0]['id']}"
    ).json()["verified"]
    with sqlite3.connect(sandbox.database) as connection:
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 5


@pytest.mark.parametrize("option", ["conflict", "non_deletion"])
def test_unresolved_or_unauthorized_request_cannot_execute(tmp_path, option):
    prepared_run(tmp_path, **{option: True})
    response = client.post(
        "/api/workflow/sandboxes", json={"run_id": "run_1", "case_id": "request_1"}
    )
    assert response.status_code == 409
    assert not remediation.SANDBOXES


def test_failed_control_stops_dependent_deletion(tmp_path, monkeypatch):
    run = prepared_run(tmp_path)
    sandbox = remediation.create_sandbox(run, "request_1")

    def fail(*_args):
        raise ValueError("Controlled failed read-back")

    monkeypatch.setattr(remediation, "perform", fail)
    events = frames(client.post(f"/api/workflow/sandboxes/{sandbox.id}/execute"))
    assert events[-1]["event"] == "run.failed"
    assert any(e["event"] == "action.failed" for e in events)
    assert remediation.read_record(sandbox, "account_service", "account_1") is not None
    assert sandbox.after is None
    assert sandbox.actions[1]["status"] == "pending"


def test_required_retained_record_missing_in_readback_cannot_certify_complete(tmp_path):
    run = prepared_run(tmp_path)
    sandbox = remediation.create_sandbox(run, "request_1")
    with sqlite3.connect(sandbox.database) as connection:
        connection.execute("DELETE FROM records WHERE resource_id='audit_record_1'")
    frames(client.post(f"/api/workflow/sandboxes/{sandbox.id}/execute"))
    assert sandbox.after["answer"]["deletion_status"] == "INCOMPLETE"
    assert any(
        "required-retained-record-missing" in reason
        for reason in sandbox.after["answer"]["trace"]["not_certified_because"]
    )


def test_execution_cannot_manufacture_proof_from_an_uncited_resource(tmp_path):
    run = prepared_run(tmp_path)
    context = run.contexts["request_1"]
    run.contexts["request_1"] = context.model_copy(
        update={
            "resource_states": (
                context.resource_states[0].model_copy(update={"supporting_evidence_ids": ()}),
                *context.resource_states[1:],
            )
        }
    )
    result = client.post(
        "/api/workflow/sandboxes", json={"run_id": "run_1", "case_id": "request_1"}
    )
    assert result.status_code == 409
    assert not remediation.SANDBOXES
