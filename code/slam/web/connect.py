"""Read-only SQLite uploads and explicit table mapping to participant evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from . import workflow

router = APIRouter(prefix="/api/workflow/databases")
DATABASES: dict[str, Path] = {}


def quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def inspect_database(path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return [
            {
                "name": name,
                "columns": [r[1] for r in db.execute(f"PRAGMA table_info({quote(name)})")],
                "rows": db.execute(f"SELECT count(*) FROM {quote(name)}").fetchone()[0],
            }
            for name in names
        ]


@router.post("")
async def upload(request: Request) -> dict[str, Any]:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 32 * 1024 * 1024:
            raise HTTPException(413, "SQLite file exceeds 32 MiB")
    if not content.startswith(b"SQLite format 3\x00"):
        raise HTTPException(422, "Choose a SQLite database file")
    identifier = uuid.uuid4().hex
    path = workflow.STORAGE / "connections" / identifier / "source.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    try:
        tables = inspect_database(path)
    except sqlite3.DatabaseError as exc:
        raise HTTPException(422, "SQLite schema could not be inspected") from exc
    DATABASES[identifier] = path
    return {
        "id": identifier,
        "tables": tables,
        "source_sha256": hashlib.sha256(content).hexdigest(),
    }


class TableMapping(BaseModel):
    table: str
    key: str
    email: str
    subject: str | None = None
    category: str = "USER_PROFILE"
    action: str = "DELETE"


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: list[TableMapping]


def write_table(root: Path, name: str, fields: list[str], values: list[dict[str, Any]]) -> None:
    with (root / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


@router.post("/{database_id}/map")
def map_database(database_id: str, mapping: Mapping) -> dict[str, Any]:
    if database_id not in DATABASES:
        raise HTTPException(404, "Connect the database again")
    path = DATABASES[database_id]
    schema = {t["name"]: t for t in inspect_database(path)}
    if not mapping.tables or len({m.table for m in mapping.tables}) != len(mapping.tables):
        raise HTTPException(422, "Choose each table once")
    root = path.parent / uuid.uuid4().hex
    root.mkdir()
    at = datetime.now(UTC).isoformat()
    identities: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    rules: dict[str, str] = {}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        for m in mapping.tables:
            columns = schema.get(m.table, {}).get("columns", [])
            if any(c not in columns for c in [m.key, m.email, *([m.subject] if m.subject else [])]):
                raise HTTPException(422, "Choose columns present in the inspected schema")
            if m.action not in {"DELETE", "REDACT", "ANONYMIZE", "RETAIN"}:
                raise HTTPException(422, "Unsupported policy action")
            if m.category in rules and rules[m.category] != m.action:
                raise HTTPException(422, "A category must have one consistent policy action")
            rules[m.category] = m.action
            keys = set()
            for row in db.execute(f"SELECT * FROM {quote(m.table)}"):
                if len(records) >= 20000:
                    raise HTTPException(413, "Mapped database exceeds 20,000 rows")
                key, email = str(row[m.key] or ""), str(row[m.email] or "").strip()
                if not key or key in keys or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                    raise HTTPException(
                        422, "Every mapped row needs a unique stable key and valid email"
                    )
                keys.add(key)
                user = (
                    str(row[m.subject])
                    if m.subject and row[m.subject]
                    else "subject_" + hashlib.sha256(email.lower().encode()).hexdigest()[:16]
                )
                identities.setdefault(
                    user,
                    {
                        "user_id": user,
                        "name": str(dict(row).get("name", user)),
                        "email": email,
                        "phone": str(dict(row).get("phone", "")),
                        "email_hash": hashlib.sha256(email.lower().encode()).hexdigest(),
                        "updated_at": at,
                    },
                )
                payload = {
                    k: v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
                    for k, v in dict(row).items()
                }
                records.append(
                    {
                        "resource_id": f"{m.table}/{key}",
                        "record_type": m.category,
                        "system": m.table,
                        "recorded_at": at,
                        "result": "PRESENT",
                        "user_id": user,
                        "email": email,
                        "row": payload,
                    }
                )
    write_table(
        root,
        "user_identities.csv",
        ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
        list(identities.values()),
    )
    write_table(
        root,
        "user_audit_log.csv",
        ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"],
        [],
    )
    write_table(
        root,
        "system_activity.csv",
        [
            "activity_id",
            "event_time",
            "event_type",
            "source_system",
            "target_system",
            "resource_id",
            "reported_result",
            "details",
        ],
        [],
    )
    write_table(
        root,
        "deletion_rules.csv",
        ["rule_id", "data_category", "condition", "required_action"],
        [
            {
                "rule_id": f"mapped_{i}",
                "data_category": cat,
                "condition": "User-supplied mapping",
                "required_action": action,
            }
            for i, (cat, action) in enumerate(rules.items())
        ],
    )
    write_table(
        root,
        "deletion_requests.csv",
        [
            "case_id",
            "email",
            "requested_at",
            "reported_status",
            "reported_at",
            "audit_at",
            "request_text",
        ],
        [
            {
                "case_id": f"connected_{i}",
                "email": v["email"],
                "requested_at": at,
                "reported_at": at,
                "audit_at": at,
                "reported_status": "NOT_STARTED",
                "request_text": "Please delete my account and personal data.",
            }
            for i, v in enumerate(identities.values())
        ],
    )
    (root / "records.json").write_text(json.dumps({"records": records}), encoding="utf-8")
    write_table(
        root,
        "evidence_files.csv",
        ["file_id", "file_path", "origin", "captured_at"],
        [
            {
                "file_id": "connected_snapshot",
                "file_path": "records.json",
                "origin": "Read-only SQLite snapshot",
                "captured_at": at,
            }
        ],
    )
    return workflow.register_input(root, "Connected SQLite snapshot").public()
