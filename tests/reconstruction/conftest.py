"""Deterministic reconstruction fixtures; no network or API credentials."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from slam.contracts import (
    AuditRequest,
    CurrentIdentity,
    EvidenceBundle,
    IdentityChangeEvent,
    Observation,
    SourceKind,
    SourceRecord,
    SourceSpan,
)


def when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def request(
    *,
    email: str = "old@example.test",
    text: str = "Please permanently delete my account",
    audit_at: datetime | None = None,
) -> AuditRequest:
    return AuditRequest(
        case_id="case-1",
        email=email,
        requested_at=datetime(2026, 1, 1, tzinfo=UTC),
        reported_status="COMPLETE",
        reported_at=datetime(2026, 1, 2, tzinfo=UTC),
        audit_at=audit_at or datetime(2026, 2, 1, tzinfo=UTC),
        request_text=text,
    )


def current(
    *,
    user_id: str = "user_1",
    email: str = "new@example.test",
    source_id: str = "identity_1",
) -> CurrentIdentity:
    return CurrentIdentity(
        user_id=user_id,
        name="Example Person",
        email=email,
        email_normalized=email.casefold(),
        phone="+1 202 555 0101",
        email_hash="a" * 64,
        updated_at=datetime(2026, 1, 10, tzinfo=UTC),
        source_id=source_id,
    )


def change(
    *,
    user_id: str = "user_1",
    old: str = "old@example.test",
    new: str = "new@example.test",
    at: datetime | None = None,
    audit_id: str = "audit_1",
) -> IdentityChangeEvent:
    return IdentityChangeEvent(
        audit_id=audit_id,
        user_id=user_id,
        field_name="email",
        old_value=old,
        new_value=new,
        changed_at=at or datetime(2026, 1, 5, tzinfo=UTC),
        source_id=audit_id,
    )


def source(source_id: str = "evidence_1", *, captured_at: datetime | None = None) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        kind=SourceKind.JSON,
        origin="test",
        path=f"evidence/{source_id}.json",
        captured_at=captured_at or datetime(2026, 1, 20, tzinfo=UTC),
        sha256=digest(source_id),
        parse_status="parsed",
    )


def observation(
    label: str,
    *,
    source_id: str = "evidence_1",
    system: str = "account_service",
    resource: str = "account_1",
    category: str = "USER_PROFILE",
    state: str = "PRESENT",
    effective_time: datetime | None = None,
    email: str = "old@example.test",
    fields: dict[str, object] | None = None,
) -> Observation:
    identifiers = {"email": email, "email_normalized": email.casefold()} if email else {}
    hints = (email.casefold(),) if email else ()
    return Observation(
        observation_id=digest(label),
        subject_hints=hints,
        system_id=system,
        resource_id=resource,
        category=category,
        observed_state=state,
        effective_time=effective_time or datetime(2026, 1, 20, tzinfo=UTC),
        source_kind=SourceKind.JSON,
        identifiers=identifiers,
        fields={"evidence_nature": "observation", "source": {}, **(fields or {})},
        spans=(SourceSpan(source_id=source_id, json_path=f"$.{label}"),),
    )


@pytest.fixture
def base_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        sources=(source(),),
        current_identities=(current(),),
        identity_changes=(change(),),
    )
