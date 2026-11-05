"""Deterministic fictional participant-like inputs for development evaluation.

ScenarioEvidence deliberately has no expected status, answer, or truth label.
Expected outcomes belong in test-only oracle code and are never passed to an
audit function.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from slam.contracts import (
    Activity,
    AuditRequest,
    CurrentIdentity,
    EvidenceBundle,
    IdentityChangeEvent,
    Observation,
    ParseStatus,
    PolicyRule,
    SourceKind,
    SourceRecord,
    SourceSpan,
)


class EventKind(StrEnum):
    IDENTITY_CHANGE = "identity_change"
    DELETION = "deletion"
    REDACTION = "redaction"
    ANONYMIZATION = "anonymization"
    RETENTION = "retention"
    SYNC_IMPORT = "sync_import"
    REPLICATION = "replication"
    BACKUP = "backup"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class ScenarioEvent:
    event_id: str
    kind: EventKind
    fictional_subject: str
    system_id: str
    resource_id: str
    occurred_at: datetime
    source_ref: str
    detail: str


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    """Inputs visible to an audit implementation; intentionally unlabeled."""

    scenario_id: str
    seed: int
    audit_at: datetime
    events: tuple[ScenarioEvent, ...]
    request: AuditRequest
    bundle: EvidenceBundle


_DETAILS: dict[EventKind, tuple[str, ...]] = {
    EventKind.IDENTITY_CHANGE: ("fictional alias updated", "fictional contact rotated"),
    EventKind.DELETION: ("record removal observed", "record still present in snapshot"),
    EventKind.REDACTION: ("direct fields replaced", "redaction confirmation recorded"),
    EventKind.ANONYMIZATION: ("linkable fields removed", "aggregate retained"),
    EventKind.RETENTION: ("retention rule applies", "retention review recorded"),
    EventKind.SYNC_IMPORT: ("scheduled import completed", "source synchronization observed"),
    EventKind.REPLICATION: ("replica snapshot recorded", "replication lag observed"),
    EventKind.BACKUP: ("backup snapshot created", "archive inventory recorded"),
    EventKind.RESTORE: ("restore job completed", "restore job blocked"),
}


def generate_scenario(seed: int, *, event_count: int = 18) -> ScenarioEvidence:
    """Generate reproducible fictional evidence without exposing an oracle label."""
    if event_count < len(EventKind):
        raise ValueError("event_count must include at least one of every event kind")
    rng = random.Random(seed)
    anchor = datetime(2025, 1, 1, tzinfo=UTC)
    audit_at = anchor + timedelta(days=90)
    digest = hashlib.sha256(f"slam-synthetic:{seed}".encode()).hexdigest()[:12]
    scenario_id = f"synthetic-{digest}"
    events: list[ScenarioEvent] = []
    kinds = list(EventKind)
    kinds.extend(rng.choice(list(EventKind)) for _ in range(event_count - len(kinds)))
    rng.shuffle(kinds)
    for index, kind in enumerate(kinds):
        subject_no = rng.randint(1, 3)
        system_no = rng.randint(1, 5)
        day = 100 if index == len(kinds) - 1 else rng.randint(0, 110)
        occurred_at = anchor + timedelta(days=day, minutes=index)
        events.append(
            ScenarioEvent(
                event_id=f"evt-{digest}-{index:04d}",
                kind=kind,
                fictional_subject=f"fictional-subject-{subject_no}",
                system_id=f"fictional-system-{system_no}",
                resource_id=f"fictional-resource-{rng.randint(1, 12)}",
                occurred_at=occurred_at,
                source_ref=f"fixture-source-{index:04d}",
                detail=rng.choice(_DETAILS[kind]),
            )
        )
    sources: list[SourceRecord] = []
    observations: list[Observation] = []
    changes: list[IdentityChangeEvent] = []
    activities: list[Activity] = []
    emails = {number: f"fictional-{number}@example.test" for number in range(1, 4)}
    state_by_kind = {
        EventKind.DELETION: "ABSENT",
        EventKind.REDACTION: "REDACTED",
        EventKind.ANONYMIZATION: "ANONYMIZED",
        EventKind.RETENTION: "RETAINED",
        EventKind.SYNC_IMPORT: "ACTIVE",
        EventKind.REPLICATION: "PRESENT",
        EventKind.BACKUP: "PRESENT",
        EventKind.RESTORE: "BLOCKED",
    }
    category_by_kind = {
        EventKind.DELETION: "USER_PROFILE",
        EventKind.REDACTION: "SUPPORT_MESSAGE",
        EventKind.ANONYMIZATION: "ANALYTICS_RECORD",
        EventKind.RETENTION: "TRANSACTION_RECORD",
        EventKind.SYNC_IMPORT: "SYNC_FLOW",
        EventKind.REPLICATION: "USER_PROFILE",
        EventKind.BACKUP: "BACKUP_COPY",
        EventKind.RESTORE: "RESTORE_JOB",
    }
    for event in events:
        source_id = event.source_ref
        content_hash = hashlib.sha256(event.detail.encode()).hexdigest()
        sources.append(
            SourceRecord(
                source_id=source_id,
                kind=SourceKind.JSON,
                origin=event.system_id,
                path=f"synthetic/{source_id}.json",
                captured_at=event.occurred_at,
                sha256=content_hash,
                parse_status=ParseStatus.PARSED,
            )
        )
        if event.kind is EventKind.IDENTITY_CHANGE:
            email = emails[int(event.fictional_subject.rsplit("-", 1)[1])]
            changes.append(
                IdentityChangeEvent(
                    audit_id=event.event_id,
                    user_id=event.fictional_subject,
                    field_name="email",
                    old_value=email,
                    new_value=f"updated-{email}",
                    changed_at=event.occurred_at,
                    source_id=source_id,
                )
            )
            continue
        if event.kind in {
            EventKind.SYNC_IMPORT,
            EventKind.REPLICATION,
            EventKind.BACKUP,
            EventKind.RESTORE,
        }:
            activities.append(
                Activity(
                    activity_id=event.event_id,
                    activity_type=event.kind.value,
                    occurred_at=event.occurred_at,
                    system_id=event.system_id,
                    resource_id=event.resource_id,
                    reported_result=event.detail,
                    attributes={
                        "source_id": source_id,
                        "fictional_subject": event.fictional_subject,
                    },
                )
            )
        normalized_state = state_by_kind[event.kind]
        if normalized_state == "ABSENT" and "still present" in event.detail:
            normalized_state = "PRESENT"
        if normalized_state == "ACTIVE" and "completed" in event.detail:
            normalized_state = "PRESENT"
        if normalized_state == "BLOCKED" and "completed" in event.detail:
            normalized_state = "PRESENT"
        email = emails[int(event.fictional_subject.rsplit("-", 1)[1])]
        observations.append(
            Observation(
                observation_id=hashlib.sha256(event.event_id.encode()).hexdigest(),
                subject_hints=(email,),
                system_id=event.system_id,
                resource_id=event.resource_id,
                category=category_by_kind[event.kind],
                observed_state=normalized_state,
                effective_time=event.occurred_at,
                source_kind=SourceKind.JSON,
                identifiers={"email": email},
                fields={"evidence_nature": "observation", "source": {"kind": event.kind.value}},
                spans=(SourceSpan(source_id=source_id, json_path="$.evidence"),),
            )
        )
    identities = tuple(
        CurrentIdentity(
            user_id=f"fictional-subject-{number}",
            name=f"Fictional Person {number}",
            email=email,
            email_normalized=email,
            phone=f"+1-202-555-01{number:02d}",
            email_hash=hashlib.sha256(email.encode()).hexdigest(),
            updated_at=anchor + timedelta(days=20),
            source_id="fixture-source-0000",
        )
        for number, email in emails.items()
    )
    request = AuditRequest(
        case_id=scenario_id,
        email=emails[1],
        requested_at=anchor,
        reported_status="COMPLETE",
        reported_at=anchor + timedelta(days=30),
        audit_at=audit_at,
        request_text="Please delete this fictional account.",
    )
    bundle = EvidenceBundle(
        sources=tuple(sources),
        current_identities=identities,
        identity_changes=tuple(changes),
        activities=tuple(activities),
        observations=tuple(observations),
        policy_rules=(
            PolicyRule(
                rule_id="synthetic-delete", category="USER_PROFILE", required_action="DELETE"
            ),
            PolicyRule(
                rule_id="synthetic-retain",
                category="TRANSACTION_RECORD",
                required_action="RETAIN",
            ),
            PolicyRule(
                rule_id="synthetic-redact", category="SUPPORT_MESSAGE", required_action="REDACT"
            ),
            PolicyRule(
                rule_id="synthetic-anonymize",
                category="ANALYTICS_RECORD",
                required_action="ANONYMIZE",
            ),
        ),
    )
    return ScenarioEvidence(scenario_id, seed, audit_at, tuple(events), request, bundle)
