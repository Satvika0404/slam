"""Real SQLite mutations in isolated per-request copies, followed by fresh policy checks.

There are deliberately no external connectors, arbitrary SQL or input-file writes here.
The original audit remains immutable; this lab verifies only the materialized imported scope.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from slam.contracts import (
    CaseContext,
    EvidenceBundle,
    Observation,
    ParseStatus,
    ResourceState,
    SourceKind,
    SourceRecord,
    SourceSpan,
)
from slam.planning.engine import plan_case
from slam.planning.validation import validate_answer

from . import workflow

ABSENT = {"ABSENT", "DELETED", "REMOVED", "PURGED", "NOT_FOUND"}
ALLOWED = {
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "DELETE_RECORD",
    "REDACT_RECORD",
    "ANONYMIZE_RECORD",
}
DIRECT = {
    "email",
    "email_normalized",
    "email_hash",
    "phone",
    "name",
    "full_name",
    "owner_email",
    "customer_email",
    "requester_email",
    "owner_phone",
    "requester_phone",
}
SUBJECT = {
    "user_id",
    "customer_reference",
    "subject_id",
    "subject_ref",
    "subject_reference",
    "lookup_key",
}


@dataclass
class Sandbox:
    id: str
    run: workflow.Run
    case_id: str
    directory: Path
    actions: list[dict[str, Any]]
    status: str = "ready"
    receipts: list[dict[str, Any]] = field(default_factory=list)
    after: dict[str, Any] | None = None
    proof: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def database(self) -> Path:
        return self.directory / "working-copy.sqlite"

    def snapshot(self) -> dict[str, Any]:
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT i.system_id,i.resource_id,i.category,i.before_state,r.state,r.payload "
                "FROM inventory i LEFT JOIN records r ON i.system_id=r.system_id "
                "AND i.resource_id=r.resource_id ORDER BY i.system_id,i.resource_id"
            ).fetchall()
        records = []
        for row in rows:
            latest = next(
                (
                    r
                    for r in reversed(self.receipts)
                    if r["system_id"] == row["system_id"] and r["resource_id"] == row["resource_id"]
                ),
                None,
            )
            records.append(
                {
                    "system_id": row["system_id"],
                    "resource_id": row["resource_id"],
                    "category": row["category"],
                    "before_state": row["before_state"],
                    "state": row["state"] or "ABSENT",
                    "present": row["state"] is not None,
                    "payload": json.loads(row["payload"]) if row["payload"] else {},
                    "receipt": latest,
                }
            )
        return {
            "id": self.id,
            "run_id": self.run.id,
            "case_id": self.case_id,
            "input_fingerprint": self.run.input.fingerprint,
            "scope": (
                "Isolated SQLite copy of the imported request; "
                "external systems and source files are unchanged"
            ),
            "status": self.status,
            "records": [{k: v for k, v in r.items() if k != "payload"} for r in records],
            "actions": self.actions,
            "receipts": self.receipts,
            "after": self.after,
        }


SANDBOXES: dict[str, Sandbox] = {}


def get_sandbox(sandbox_id: str) -> Sandbox:
    if sandbox_id not in SANDBOXES:
        raise HTTPException(404, "Working copy is unavailable")
    return SANDBOXES[sandbox_id]


def payload_for(run: workflow.Run, case_id: str, state: ResourceState) -> dict[str, Any]:
    assert run.bundle is not None
    eligible = set(run.contexts[case_id].eligible_observation_ids)
    items = [
        o
        for o in run.bundle.observations
        if o.observation_id in eligible
        and o.system_id == state.system_id
        and o.resource_id == state.resource_id
    ]
    if not items:
        return {}
    item = max(items, key=lambda o: o.effective_time)
    return {"record": item.fields.get("source", {}), "identifiers": item.identifiers}


def create_sandbox(run: workflow.Run, case_id: str) -> Sandbox:
    if run.status != "completed" or case_id not in run.answers:
        raise HTTPException(409, "Finish the audit before preparing a working copy")
    answer, context = run.answers[case_id], run.contexts[case_id]
    if context.request_intent.value != "DELETION" or context.subject_id is None:
        raise HTTPException(409, "No resolved, authorized deletion request")
    if (
        context.coverage_issues
        or context.unresolved_conflicts
        or answer.trace.get("not_certified_because")
    ):
        raise HTTPException(409, "Unresolved evidence must be investigated before execution")
    if any(state.uncertain or state.conflicting_evidence_ids for state in context.resource_states):
        raise HTTPException(409, "An uncertain resource cannot be executed")
    if any(not state.supporting_evidence_ids for state in context.resource_states):
        raise HTTPException(409, "Uncited or future-only resources cannot become an execution copy")
    existing = next(
        (s for s in SANDBOXES.values() if s.run.id == run.id and s.case_id == case_id), None
    )
    if existing:
        return existing
    actions = []
    for step in answer.steps:
        if step.phase.value != "REMEDIATION":
            continue
        if step.operation.value not in ALLOWED:
            raise HTTPException(409, "Unsupported remediation operation")
        state = next(
            (
                r
                for r in context.resource_states
                if r.system_id == step.system_id and r.resource_id == step.resource_id
            ),
            None,
        )
        if state is None:
            raise HTTPException(409, "Plan resource is not grounded in the audited state")
        rules = [r for r in context.policy_rules if r.category == state.category]
        if step.operation.value == "DELETE_RECORD" and any(
            r.required_action.upper() == "RETAIN" for r in rules
        ):
            raise HTTPException(409, "Policy requires this record to be retained")
        if len({r.required_action.upper() for r in rules}) > 1:
            raise HTTPException(409, "Conflicting policy actions require investigation")
        actions.append(
            {
                "id": f"action_{step.step_no}",
                **step.model_dump(mode="json"),
                "status": "pending",
                "proof_id": None,
            }
        )
    sid = uuid.uuid4().hex
    directory = workflow.STORAGE / run.id / "sandboxes" / sid
    directory.mkdir(parents=True, exist_ok=True)
    sandbox = Sandbox(sid, run, case_id, directory, actions)
    with sqlite3.connect(sandbox.database) as connection:
        connection.execute(
            "CREATE TABLE inventory(system_id TEXT,resource_id TEXT,category TEXT,"
            "before_state TEXT,PRIMARY KEY(system_id,resource_id))"
        )
        connection.execute(
            "CREATE TABLE records(system_id TEXT,resource_id TEXT,state TEXT,payload TEXT,"
            "PRIMARY KEY(system_id,resource_id))"
        )
        for state in context.resource_states:
            connection.execute(
                "INSERT INTO inventory VALUES(?,?,?,?)",
                (state.system_id, state.resource_id, state.category, state.state),
            )
            if state.state not in ABSENT:
                connection.execute(
                    "INSERT INTO records VALUES(?,?,?,?)",
                    (
                        state.system_id,
                        state.resource_id,
                        state.state,
                        json.dumps(payload_for(run, case_id, state)),
                    ),
                )
    SANDBOXES[sid] = sandbox
    return sandbox


def sensitive_values(sandbox: Sandbox, anonymize: bool) -> set[str]:
    assert sandbox.run.bundle is not None
    subject = sandbox.run.contexts[sandbox.case_id].subject_id
    values: set[str] = set()
    for identity in sandbox.run.bundle.current_identities:
        if identity.user_id == subject:
            values.update((identity.email, identity.phone, identity.email_hash, identity.name))
            if anonymize:
                values.add(identity.user_id)
    for event in sandbox.run.bundle.identity_changes:
        if event.user_id == subject:
            values.update((event.old_value or "", event.new_value or ""))
    return {v for v in values if len(v) > 2}


def scrub(value: Any, needles: set[str], anonymize: bool) -> Any:
    if isinstance(value, dict):
        return {
            k: scrub(v, needles, anonymize)
            for k, v in value.items()
            if k.lower() not in DIRECT and not (anonymize and k.lower() in SUBJECT)
        }
    if isinstance(value, list):
        return [scrub(v, needles, anonymize) for v in value]
    if isinstance(value, str):
        for needle in sorted(needles, key=len, reverse=True):
            value = re.sub(re.escape(needle), "[REMOVED]", value, flags=re.IGNORECASE)
        return value
    return value


def read_record(sandbox: Sandbox, system: str, resource: str) -> dict[str, Any] | None:
    with sqlite3.connect(sandbox.database) as connection:
        row = connection.execute(
            "SELECT state,payload FROM records WHERE system_id=? AND resource_id=?",
            (system, resource),
        ).fetchone()
    return {"state": row[0], "payload": json.loads(row[1])} if row else None


def perform(sandbox: Sandbox, action: dict[str, Any]) -> dict[str, Any]:
    system, resource, operation = action["system_id"], action["resource_id"], action["operation"]
    before = read_record(sandbox, system, resource)
    target = action["state"]
    with sqlite3.connect(sandbox.database) as connection:
        if operation == "DELETE_RECORD":
            connection.execute(
                "DELETE FROM records WHERE system_id=? AND resource_id=?", (system, resource)
            )
        else:
            if before is None:
                raise ValueError("Expected record is missing; execution stopped")
            payload = before["payload"]
            if operation == "DISABLE_DATA_FLOW":
                payload = {**payload, "enabled": False}
            if operation == "BLOCK_RESTORE":
                payload = {**payload, "restore_allowed": False}
            if operation in {"REDACT_RECORD", "ANONYMIZE_RECORD"}:
                payload = scrub(
                    payload,
                    sensitive_values(sandbox, operation == "ANONYMIZE_RECORD"),
                    operation == "ANONYMIZE_RECORD",
                )
            connection.execute(
                "UPDATE records SET state=?,payload=? WHERE system_id=? AND resource_id=?",
                (target, json.dumps(payload), system, resource),
            )
    # Independent connection observes the committed result, not the command's return code.
    after = read_record(sandbox, system, resource)
    verified = (
        after is None
        if operation == "DELETE_RECORD"
        else after is not None and after["state"] == target
    )
    if after and operation in {"REDACT_RECORD", "ANONYMIZE_RECORD"}:
        anonymize = operation == "ANONYMIZE_RECORD"
        verified = verified and after["payload"] == scrub(
            after["payload"], sensitive_values(sandbox, anonymize), anonymize
        )
    if after and operation == "DISABLE_DATA_FLOW":
        verified = verified and after["payload"].get("enabled") is False
    if after and operation == "BLOCK_RESTORE":
        verified = verified and after["payload"].get("restore_allowed") is False
    if not verified:
        raise ValueError("Committed read-back did not match the intended state")
    at = datetime.now(UTC).isoformat()
    proof_id = "execution_" + uuid.uuid4().hex
    proof = {
        "id": proof_id,
        "scope": "isolated SQLite working copy",
        "operation": operation,
        "system_id": system,
        "resource_id": resource,
        "at": at,
        "before": before,
        "after": after,
        "verified": True,
    }
    content = json.dumps(proof, indent=2, sort_keys=True)
    (sandbox.directory / f"{proof_id}.json").write_text(content, encoding="utf-8")
    receipt = {
        "id": proof_id,
        "system_id": system,
        "resource_id": resource,
        "operation": operation,
        "at": at,
        "before_state": before["state"] if before else "ABSENT",
        "state": after["state"] if after else "ABSENT",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "verified": True,
    }
    sandbox.proof[proof_id] = {**proof, "sha256": receipt["sha256"]}
    sandbox.receipts.append(receipt)
    return receipt


def re_audit(sandbox: Sandbox) -> dict[str, Any]:
    run, original = sandbox.run, sandbox.run.contexts[sandbox.case_id]
    at = datetime.now(UTC)
    request = run.requests[sandbox.case_id].model_copy(update={"audit_at": at})
    sid = "readback_" + uuid.uuid4().hex
    result = []
    states, observations = [], []
    for index, state in enumerate(original.resource_states):
        record = read_record(sandbox, state.system_id, state.resource_id)
        value = record["state"] if record else "ABSENT"
        payload = record["payload"] if record else {}
        result.append(
            {
                "system_id": state.system_id,
                "resource_id": state.resource_id,
                "state": value,
                "payload": payload,
            }
        )
        states.append(
            state.model_copy(
                update={
                    "state": value,
                    "at": at,
                    "supporting_evidence_ids": (sid,),
                    "conflicting_evidence_ids": (),
                }
            )
        )
        identifiers = payload.get("identifiers", {})
        observations.append(
            Observation(
                observation_id=hashlib.sha256(f"{sid}:{index}".encode()).hexdigest(),
                subject_hints=(original.subject_id,) if original.subject_id else (),
                system_id=state.system_id,
                resource_id=state.resource_id,
                category=state.category,
                observed_state=value,
                effective_time=at,
                source_kind=SourceKind.JSON,
                identifiers={k: v for k, v in identifiers.items() if isinstance(v, str)},
                fields={
                    "source": payload,
                    "evidence_nature": "observation",
                    "scope": "sandbox SQLite read-back",
                },
                spans=(SourceSpan(source_id=sid, json_path=f"$.records[{index}]"),),
            )
        )
    content = json.dumps(
        {"scope": "isolated SQLite read-back", "captured_at": at.isoformat(), "records": result},
        indent=2,
        sort_keys=True,
    )
    (sandbox.directory / f"{sid}.json").write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode()).hexdigest()
    sandbox.proof[sid] = {
        "id": sid,
        "at": at.isoformat(),
        "sha256": digest,
        "content": content,
        "scope": "Fresh read of the materialized request only",
    }

    def open_edge(edge: Any, blocked_state: str) -> bool:
        return not any(
            s.state == blocked_state
            and (s.resource_id in edge.source.split(":") or s.resource_id in edge.target.split(":"))
            for s in states
        )

    context: CaseContext = original.model_copy(
        update={
            "request": request,
            "resource_states": tuple(states),
            "eligible_observation_ids": tuple(o.observation_id for o in observations),
            "excluded_future_observation_ids": (),
            "evidence_captured_at": {sid: at},
            "active_flows": tuple(e for e in original.active_flows if open_edge(e, "DISABLED")),
            "restore_risks": tuple(e for e in original.restore_risks if open_edge(e, "BLOCKED")),
        }
    )
    retained_categories = {
        rule.category for rule in original.policy_rules if rule.required_action.upper() == "RETAIN"
    }
    gaps = list(original.coverage_issues)
    gaps += [
        f"required-retained-record-missing:{state.system_id}:{state.resource_id}"
        for state in states
        if state.category in retained_categories and state.state in ABSENT
    ]
    if context.active_flows or context.restore_risks:
        gaps.append("recreation paths remain open or their control mapping is unverified")
    context = context.model_copy(update={"coverage_issues": tuple(gaps)})
    bundle = EvidenceBundle(
        sources=(
            SourceRecord(
                source_id=sid,
                kind=SourceKind.JSON,
                origin="Isolated SQLite read-back",
                path=f"sandbox/{sid}.json",
                captured_at=at,
                sha256=digest,
                parse_status=ParseStatus.PARSED,
            ),
        ),
        observations=tuple(observations),
        policy_rules=original.policy_rules,
    )
    answer = validate_answer(plan_case(context, bundle), eligible_evidence_ids={sid})
    sandbox.after = {
        "at": at.isoformat(),
        "answer": answer.model_dump(mode="json"),
        "resources": [s.model_dump(mode="json") for s in states],
        "proof_id": sid,
        "source_sha256": digest,
        "remaining_flows": len(context.active_flows),
        "remaining_restores": len(context.restore_risks),
        "scope": (
            "Imported resources in this isolated working copy; not external production systems"
        ),
    }
    return sandbox.after


def execute(sandbox: Sandbox) -> Response:
    def work(send: Callable[..., None], stopped: threading.Event) -> None:
        if not sandbox.lock.acquire(blocking=False):
            send("run.failed", message="This working copy already has an active execution")
            return
        try:
            sandbox.status = "running"
            send(
                "execution.started",
                sandbox_id=sandbox.id,
                case_id=sandbox.case_id,
                snapshot=sandbox.snapshot(),
            )
            for action in sandbox.actions:
                if stopped.is_set():
                    sandbox.status = "stopped"
                    return
                if action["status"] == "verified":
                    continue
                action["status"] = "running"
                send("action.started", action=action.copy(), snapshot=sandbox.snapshot())
                try:
                    receipt = perform(sandbox, action)
                except Exception as exc:
                    action["status"] = "failed"
                    sandbox.status = "failed"
                    send(
                        "action.failed",
                        action=action.copy(),
                        error_type=type(exc).__name__,
                        message="Read-back failed; dependent actions were stopped",
                        snapshot=sandbox.snapshot(),
                    )
                    send("run.failed", message="Read-back failed; dependent actions were stopped")
                    return
                action["status"], action["proof_id"] = "verified", receipt["id"]
                send(
                    "action.verified",
                    action=action.copy(),
                    receipt=receipt,
                    snapshot=sandbox.snapshot(),
                )
            send("verification.started", sandbox_id=sandbox.id)
            result = re_audit(sandbox)
            sandbox.status = (
                "verified" if result["answer"]["deletion_status"] == "COMPLETE" else "incomplete"
            )
            send("verification.completed", snapshot=sandbox.snapshot())
            send("run.completed", snapshot=sandbox.snapshot(), api_calls=0)
        finally:
            if sandbox.status == "running":
                sandbox.status = "stopped"
            sandbox.lock.release()

    return workflow.event_stream(work)


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    case_id: str


router = APIRouter(prefix="/api/workflow/sandboxes", tags=["Isolated remediation"])


@router.post("")
def prepare(body: PrepareBody) -> dict[str, Any]:
    return create_sandbox(workflow.get_run(body.run_id), body.case_id).snapshot()


@router.get("/{sandbox_id}")
def snapshot(sandbox_id: str) -> dict[str, Any]:
    return get_sandbox(sandbox_id).snapshot()


@router.post("/{sandbox_id}/execute")
def execute_plan(sandbox_id: str) -> Response:
    return execute(get_sandbox(sandbox_id))


@router.get("/{sandbox_id}/evidence/{evidence_id}")
def proof(sandbox_id: str, evidence_id: str) -> dict[str, Any]:
    sandbox = get_sandbox(sandbox_id)
    if evidence_id not in sandbox.proof:
        raise HTTPException(404, "Proof does not belong to this working copy")
    return sandbox.proof[evidence_id]


@router.get("/{sandbox_id}/export")
def report(sandbox_id: str) -> Response:
    sandbox = get_sandbox(sandbox_id)
    return Response(
        json.dumps(sandbox.snapshot(), indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sandbox-execution-report.json"'},
    )
