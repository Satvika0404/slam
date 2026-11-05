"""Append-only storage for reproducible, sanitized failure fingerprints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from slam.contracts import CONTRACT_VERSION

_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_SECRET_LIKE = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|credential|authorization|bearer|cookie)"
)


def _safe_values(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    cleaned = tuple(sorted(set(values)))
    for value in cleaned:
        if not _SAFE_REFERENCE.fullmatch(value) or _SECRET_LIKE.search(value):
            raise ValueError(f"{label} must contain sanitized opaque references only")
    return cleaned


@dataclass(frozen=True, slots=True)
class FailureRecord:
    fingerprint: str
    failure_kind: str
    software_version: str
    schema_version: str
    seed: int
    diagnostic_codes: tuple[str, ...]
    sanitized_references: tuple[str, ...]
    rule_version: str

    @classmethod
    def create(
        cls,
        *,
        failure_kind: str,
        software_version: str,
        seed: int,
        diagnostic_codes: tuple[str, ...],
        sanitized_references: tuple[str, ...] = (),
        schema_version: str = CONTRACT_VERSION,
        rule_version: str = "improvement-v1",
    ) -> FailureRecord:
        safe_kind = _safe_values((failure_kind,), "failure_kind")[0]
        safe_codes = _safe_values(diagnostic_codes, "diagnostic_codes")
        safe_refs = _safe_values(sanitized_references, "sanitized_references")
        safe_version = _safe_values((software_version,), "software_version")[0]
        safe_schema = _safe_values((schema_version,), "schema_version")[0]
        safe_rule = _safe_values((rule_version,), "rule_version")[0]
        identity = {
            "failure_kind": safe_kind,
            "software_version": safe_version,
            "schema_version": safe_schema,
            "seed": seed,
            "diagnostic_codes": safe_codes,
            "sanitized_references": safe_refs,
            "rule_version": safe_rule,
        }
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(
            fingerprint=fingerprint,
            failure_kind=safe_kind,
            software_version=safe_version,
            schema_version=safe_schema,
            seed=seed,
            diagnostic_codes=safe_codes,
            sanitized_references=safe_refs,
            rule_version=safe_rule,
        )


class FailureStore:
    """JSONL registry; stores metadata only and never stores exception text or evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: FailureRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True, separators=(",", ":")))
            handle.write("\n")

    def records(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        with self.path.open(encoding="utf-8") as handle:
            return tuple(json.loads(line) for line in handle if line.strip())
