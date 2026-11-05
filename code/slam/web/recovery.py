"""Recover allowlisted tabular header failures in a separate, validated input copy."""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slam.evaluation.improvement.recovery import RecoveryAction, RecoveryPolicy, run_recovery
from slam.ingestion.tables import TABLE_SPECS, load_table

VERSION = "table-header-aliases/1.0.0"
ALIASES = {"email_address": "email", "customer_email": "email", "record_id": "resource_id"}


def recover_tables(
    root: Path, destination: Path, send: Callable[..., None]
) -> tuple[Path, list[dict[str, Any]]]:
    recovered = []
    working = root
    for name in (
        "user_identities",
        "user_audit_log",
        "system_activity",
        "deletion_rules",
        "deletion_requests",
    ):
        spec = TABLE_SPECS[name]
        original = (root / spec.filename).read_bytes()
        text = original.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fields = list(reader.fieldnames or [])
        missing = sorted(set(spec.columns) - set(fields))
        if not missing:
            continue
        send("stage.started", stage="recovery")
        send("recovery.started", component=spec.filename, missing=missing, adapter_version=VERSION)
        names = [
            ALIASES.get(f.strip().lower().replace(" ", "_"), f.strip().lower().replace(" ", "_"))
            for f in fields
        ]
        rows = list(reader)

        def attempt(
            _deadline: float,
            _tokens: int,
            *,
            name: str = name,
            names: list[str] = names,
            fields: list[str] = fields,
            rows: list[dict[str | None, Any]] = rows,
        ) -> tuple[bool, object | None, int]:
            spec = TABLE_SPECS[name]
            if len(names) != len(set(names)) or not set(spec.columns).issubset(names):
                return False, None, 0
            if any(None in row or any(v is None for v in row.values()) for row in rows):
                return False, None, 0
            if not destination.exists():
                shutil.copytree(root, destination)
            with (destination / spec.filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(names)
                writer.writerows([[row[f] for f in fields] for row in rows])
            result = load_table(destination, name)
            valid = not any(issue.severity == "error" for issue in result.issues)
            return valid, {"rows": len(result.rows)}, 0

        result = run_recovery(
            {RecoveryAction.REPARSE_SOURCE: attempt},
            RecoveryPolicy(
                allowed_actions=(RecoveryAction.REPARSE_SOURCE,),
                max_attempts=1,
                time_budget_seconds=2,
            ),
        )
        record = {
            "component": spec.filename,
            "status": "recovered" if result.succeeded else "unresolved",
            "adapter_version": VERSION,
            "missing_before": missing,
            "checks": "Required columns, unique names, row shape and ingestion row validation",
            "attempts": [
                {"action": a.action.value, "outcome": a.outcome, "elapsed_ms": a.elapsed_ms}
                for a in result.attempts
            ],
            "scope": "Validated input copy only; original source unchanged",
            "promoted": False,
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "recovered_sha256": hashlib.sha256(
                (destination / spec.filename).read_bytes()
            ).hexdigest()
            if result.succeeded
            else None,
        }
        recovered.append(record)
        send("recovery.completed", **record)
        send("stage.completed", stage="recovery", status=record["status"])
        if not result.succeeded:
            raise ValueError(f"Unsupported or invalid headers in {spec.filename}; recovery blocked")
        working = destination
    return working, recovered
