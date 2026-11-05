"""Measured sync experiments and bounded header recovery, scoped to local copies."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from slam.evaluation.improvement.recovery import RecoveryAction, RecoveryPolicy, run_recovery

from . import remediation, workflow

router = APIRouter(prefix="/api/workflow/experiments")


class SyncBody(BaseModel):
    sandbox_id: str
    system_id: str
    resource_id: str


@router.post("/sync")
def sync(body: SyncBody) -> dict[str, Any]:
    sandbox = remediation.get_sandbox(body.sandbox_id)
    if not sandbox.lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for execution to finish")
    try:
        target = next(
            (
                a
                for a in sandbox.actions
                if a["operation"] == "DELETE_RECORD"
                and a["system_id"] == body.system_id
                and a["resource_id"] == body.resource_id
            ),
            None,
        )
        if target is None or target["status"] != "verified":
            raise HTTPException(409, "Choose a row whose deletion has been verified")
        state = next(
            r
            for r in sandbox.run.contexts[sandbox.case_id].resource_states
            if r.system_id == body.system_id and r.resource_id == body.resource_id
        )
        payload = remediation.payload_for(sandbox.run, sandbox.case_id, state)
        branches = []
        experiment_id = uuid.uuid4().hex
        for enabled in (True, False):
            path = (
                sandbox.directory
                / f"sync-{experiment_id}-{'enabled' if enabled else 'disabled'}.sqlite"
            )
            with sqlite3.connect(sandbox.database) as source, sqlite3.connect(path) as db:
                source.backup(db)
                db.execute("CREATE TABLE sync_control(enabled INTEGER)")
                db.execute("INSERT INTO sync_control VALUES(?)", (int(enabled),))
                before = db.execute(
                    "SELECT count(*) FROM records WHERE system_id=? AND resource_id=?",
                    (body.system_id, body.resource_id),
                ).fetchone()[0]
                # The same worker runs in both independently cloned branches.
                if db.execute("SELECT enabled FROM sync_control").fetchone()[0]:
                    db.execute(
                        "INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
                        (body.system_id, body.resource_id, state.state, json.dumps(payload)),
                    )
                db.commit()
            with sqlite3.connect(path) as db:
                after = db.execute(
                    "SELECT count(*) FROM records WHERE system_id=? AND resource_id=?",
                    (body.system_id, body.resource_id),
                ).fetchone()[0]
            branches.append(
                {
                    "sync_enabled": enabled,
                    "before_rows": before,
                    "after_rows": after,
                    "recreated": before == 0 and after > 0,
                }
            )
        result = {
            "id": experiment_id,
            "at": datetime.now(UTC).isoformat(),
            "resource_id": body.resource_id,
            "system_id": body.system_id,
            "scope": "Controlled replay using the selected imported row as the upstream payload",
            "branches": branches,
            "protected": branches[1]["after_rows"] == 0,
            "sandbox_id": sandbox.id,
        }
        content = json.dumps(result, indent=2)
        result["sha256"] = hashlib.sha256(content.encode()).hexdigest()
        (sandbox.directory / f"sync-{experiment_id}.json").write_text(content, encoding="utf-8")
        return result
    finally:
        sandbox.lock.release()


class HealBody(BaseModel):
    csv_text: str


def normalize_headers(text: str) -> tuple[bool, dict[str, Any] | None, int]:
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    normalized = [f.strip().lower().replace(" ", "_") for f in fields]
    aliases = {"email_address": "email", "customer_email": "email", "record_id": "resource_id"}
    names = [aliases.get(f, f) for f in normalized]
    if len(names) != len(set(names)) or not {"email", "resource_id"}.issubset(names):
        return False, None, 0
    rows = list(reader)
    if not rows or any(
        not row.get(fields[names.index("email")]) or not row.get(fields[names.index("resource_id")])
        for row in rows
    ):
        return False, None, 0
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    writer.writerows([[row.get(field, "") for field in fields] for row in rows])
    return True, {"csv": out.getvalue(), "rows": len(rows), "headers": names}, 0


@router.post("/recovery")
def heal(body: HealBody) -> dict[str, Any]:
    if len(body.csv_text) > 100000:
        raise HTTPException(413, "Recovery input exceeds the limit")
    reader = csv.DictReader(io.StringIO(body.csv_text))
    before = set(reader.fieldnames or [])
    missing = sorted({"email", "resource_id"} - before)
    result = run_recovery(
        {
            RecoveryAction.REPARSE_SOURCE: lambda _deadline, _tokens: normalize_headers(
                body.csv_text
            )
        },
        RecoveryPolicy(
            allowed_actions=(RecoveryAction.REPARSE_SOURCE,), max_attempts=1, time_budget_seconds=2
        ),
    )
    # Independent cases gate the named adapter; no model-generated code is executed.
    development = [
        "Email Address,Record ID\na@example.test,r1\n",
        "email,resource_id\nb@example.test,r2\n",
    ]
    heldout = [
        " Customer Email , Resource ID \nc@example.test,r3\n",
        "email,resource_id\nd@example.test,r4\n",
    ]
    negative = ["email,email,resource_id\na,b,r1\n", "name,id\nx,r1\n"]
    passed = sum(normalize_headers(s)[0] for s in development + heldout) + sum(
        not normalize_headers(s)[0] for s in negative
    )
    status = "recovered" if result.succeeded else "unresolved"
    record = {
        "id": uuid.uuid4().hex,
        "component": "CSV header adapter",
        "adapter_version": "header-aliases/1.0.0",
        "missing_before": missing,
        "status": status,
        "attempts": [asdict(a) for a in result.attempts],
        "validated_payload": result.result,
        "development_passed": 2 if passed == 6 else None,
        "heldout_passed": 2 if passed == 6 else None,
        "collision_rejections": 2 if passed == 6 else None,
        "checks_passed": passed,
        "checks_total": 6,
        "promotion": "eligible_for_review" if result.succeeded and passed == 6 else "blocked",
        "scope": (
            "Explicit recovery experiment using your supplied snippet; "
            "production adapter requires review"
        ),
    }
    directory = workflow.STORAGE / "recovery"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{record['id']}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
