"""Fictional demonstration corpus. All decisions are computed by the real engine."""

import hashlib
import json
from datetime import datetime

from slam.contracts import (
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


def at(clock: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-21T{clock}:00+00:00")


def corpus(case_id: str) -> tuple[AuditRequest, EvidenceBundle, dict[str, str]]:
    if case_id not in {"demo_024", "demo_025", "demo_026"}:
        raise KeyError(case_id)
    sources: list[SourceRecord] = []
    observations: list[Observation] = []
    documents: dict[str, str] = {}

    def source(identifier: str, clock: str, content: str, origin: str) -> None:
        documents[identifier] = content
        sources.append(
            SourceRecord(
                source_id=identifier,
                kind=SourceKind.JSON,
                origin=origin,
                path=f"demo/{identifier}.json",
                captured_at=at(clock),
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                parse_status=ParseStatus.PARSED,
            )
        )

    source(
        "file_identity",
        "08:40",
        json.dumps(
            {
                "user_id": "usr_mara_024",
                "name": "Mara Vale",
                "email": "mara@atlas.example",
                "previous_email": "m.vale@atlas.example",
                "changed_at": at("08:40").isoformat(),
                "audit_id": "audit_email_024",
            },
            indent=2,
        ),
        "Identity directory",
    )

    def observation(
        identifier: str, clock: str, system: str, resource: str, category: str, state: str
    ) -> None:
        content = json.dumps(
            {
                "system_id": system,
                "resource_id": resource,
                "subject_id": "usr_mara_024",
                "state": state,
                "observed_at": at(clock).isoformat(),
                "note": "Fictional demonstration evidence; no external system was modified.",
            },
            indent=2,
        )
        source(identifier, clock, content, system)
        observations.append(
            Observation(
                observation_id=hashlib.sha256((identifier + content).encode()).hexdigest(),
                subject_hints=("usr_mara_024",),
                system_id=system,
                resource_id=resource,
                category=category,
                observed_state=state,
                effective_time=at(clock),
                source_kind=SourceKind.JSON,
                spans=(SourceSpan(source_id=identifier, json_path="$"),),
                fields={"evidence_nature": "observation", "source": json.loads(content)},
            )
        )

    observation("file_primary_01", "09:05", "primary_database", "account_024", "PROFILE", "PRESENT")
    observation(
        "file_support_01", "09:10", "support_archive", "ticket_882", "SUPPORT", "IDENTIFIABLE"
    )
    observation("file_primary_02", "10:15", "primary_database", "account_024", "PROFILE", "ABSENT")
    observation("file_replica_01", "11:05", "search_replica", "index_024", "PROFILE", "PRESENT")
    observation("file_support_02", "12:00", "support_archive", "ticket_882", "SUPPORT", "REDACTED")
    observation("file_replica_02", "14:00", "search_replica", "index_024", "PROFILE", "ABSENT")
    if case_id == "demo_026":
        observation(
            "file_conflict_01", "12:00", "support_archive", "ticket_882", "SUPPORT", "IDENTIFIABLE"
        )
    cutoff = "15:00" if case_id == "demo_025" else "13:30"
    request = AuditRequest(
        case_id=case_id,
        email="m.vale@atlas.example",
        requested_at=at("09:00"),
        reported_status="COMPLETE",
        reported_at=at("10:20"),
        audit_at=at(cutoff),
        request_text="Please delete my account and personal data, including older copies.",
    )
    bundle = EvidenceBundle(
        sources=tuple(sources),
        observations=tuple(observations),
        current_identities=(
            CurrentIdentity(
                user_id="usr_mara_024",
                name="Mara Vale",
                email="mara@atlas.example",
                email_normalized="mara@atlas.example",
                phone="+1 202 555 0148",
                email_hash=hashlib.sha256(b"mara@atlas.example").hexdigest(),
                updated_at=at("08:40"),
                source_id="file_identity",
            ),
        ),
        identity_changes=(
            IdentityChangeEvent(
                audit_id="audit_email_024",
                user_id="usr_mara_024",
                field_name="email",
                old_value="m.vale@atlas.example",
                new_value="mara@atlas.example",
                changed_at=at("08:40"),
                source_id="file_identity",
            ),
        ),
        policy_rules=(
            PolicyRule(rule_id="policy_profile", category="PROFILE", required_action="DELETE"),
            PolicyRule(rule_id="policy_support", category="SUPPORT", required_action="REDACT"),
        ),
    )
    return request, bundle, documents
