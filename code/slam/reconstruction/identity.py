"""Exact, time-aware identity resolution with participant-visible provenance."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from slam.contracts import (
    AuditRequest,
    ConfidenceClass,
    CurrentIdentity,
    EvidenceBundle,
    IdentityChangeEvent,
    IdentityLink,
)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def normalize_phone(value: str) -> str:
    return re.sub(r"[^\d+]", "", value.strip())


def normalize_identifier(kind: str, value: str) -> str:
    if kind == "email":
        return normalize_email(value)
    if kind == "phone":
        return normalize_phone(value)
    if kind in {"email_hash", "name"}:
        return value.strip().casefold()
    return value.strip()


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    subject_id: str | None
    links: tuple[IdentityLink, ...]
    match_values: frozenset[str]
    coverage_issues: tuple[str, ...]
    conflicts: tuple[str, ...]


def _email_candidates(request: AuditRequest, bundle: EvidenceBundle) -> set[str]:
    wanted = normalize_email(request.email)
    candidates = {
        identity.user_id
        for identity in bundle.current_identities
        if identity.updated_at <= request.audit_at
        and (
            identity.email_normalized.casefold() == wanted
            or normalize_email(identity.email) == wanted
        )
    }
    for event in bundle.identity_changes:
        if event.changed_at > request.audit_at:
            continue
        if event.field_name.casefold() != "email":
            continue
        values = (event.old_value, event.new_value)
        if any(value is not None and normalize_email(value) == wanted for value in values):
            candidates.add(event.user_id)
    return candidates


def _current_links(identity: CurrentIdentity) -> list[IdentityLink]:
    links: list[IdentityLink] = []
    values = (
        ("email", identity.email),
        ("phone", identity.phone),
        ("email_hash", identity.email_hash),
        ("name", identity.name),
    )
    for kind, value in values:
        if not value.strip():
            continue
        links.append(
            IdentityLink(
                left_identifier=identity.user_id,
                right_identifier=value,
                relationship=f"current_{kind}",
                evidence_ids=(identity.source_id,),
                confidence=ConfidenceClass.EXACT,
            )
        )
    return links


def _change_links(events: list[IdentityChangeEvent]) -> list[IdentityLink]:
    links: list[IdentityLink] = []
    by_field: dict[str, list[IdentityChangeEvent]] = defaultdict(list)
    for event in events:
        by_field[event.field_name.casefold()].append(event)

    for field_name, changes in sorted(by_field.items()):
        ordered = sorted(changes, key=lambda event: (event.changed_at, event.audit_id))
        for index, event in enumerate(ordered):
            next_time: datetime | None = (
                ordered[index + 1].changed_at if index + 1 < len(ordered) else None
            )
            if event.old_value and event.old_value.strip():
                links.append(
                    IdentityLink(
                        left_identifier=event.user_id,
                        right_identifier=event.old_value,
                        relationship=f"historical_{field_name}",
                        valid_to=event.changed_at,
                        evidence_ids=(event.audit_id,),
                        confidence=ConfidenceClass.EXACT,
                    )
                )
            if event.new_value and event.new_value.strip():
                links.append(
                    IdentityLink(
                        left_identifier=event.user_id,
                        right_identifier=event.new_value,
                        relationship=f"changed_{field_name}",
                        valid_from=event.changed_at,
                        valid_to=next_time,
                        evidence_ids=(event.audit_id,),
                        confidence=ConfidenceClass.EXACT,
                    )
                )
            if event.old_value and event.new_value:
                links.append(
                    IdentityLink(
                        left_identifier=event.old_value,
                        right_identifier=event.new_value,
                        relationship=f"{field_name}_change",
                        valid_from=event.changed_at,
                        evidence_ids=(event.audit_id,),
                        confidence=ConfidenceClass.EXACT,
                    )
                )
    return links


def _deduplicate(links: list[IdentityLink]) -> tuple[IdentityLink, ...]:
    unique: dict[tuple[object, ...], IdentityLink] = {}
    for link in links:
        key = (
            link.left_identifier,
            link.right_identifier,
            link.relationship,
            link.valid_from,
            link.valid_to,
            link.evidence_ids,
            link.confidence,
        )
        unique[key] = link
    return tuple(
        sorted(
            unique.values(),
            key=lambda link: (
                link.relationship,
                link.left_identifier.casefold(),
                link.right_identifier.casefold(),
                link.valid_from.isoformat() if link.valid_from else "",
            ),
        )
    )


def resolve_identity(request: AuditRequest, bundle: EvidenceBundle) -> IdentityResolution:
    """Resolve the request email exactly against current and historical identities."""

    candidates = _email_candidates(request, bundle)
    if not candidates:
        return IdentityResolution(
            subject_id=None,
            links=(),
            match_values=frozenset({normalize_email(request.email)}),
            coverage_issues=("identity:no exact current or historical email match",),
            conflicts=(),
        )
    if len(candidates) > 1:
        listed = ",".join(sorted(candidates))
        return IdentityResolution(
            subject_id=None,
            links=(),
            match_values=frozenset({normalize_email(request.email)}),
            coverage_issues=(),
            conflicts=(f"identity:request email matches multiple subjects:{listed}",),
        )

    subject_id = next(iter(candidates))
    current = [
        identity
        for identity in bundle.current_identities
        if identity.user_id == subject_id and identity.updated_at <= request.audit_at
    ]
    changes = [
        event
        for event in bundle.identity_changes
        if event.user_id == subject_id and event.changed_at <= request.audit_at
    ]
    links = _deduplicate(
        [link for identity in current for link in _current_links(identity)] + _change_links(changes)
    )

    values: set[str] = {subject_id, normalize_email(request.email)}
    for identity in current:
        for kind, value in (
            ("email", identity.email),
            ("phone", identity.phone),
            ("email_hash", identity.email_hash),
            ("name", identity.name),
        ):
            if value.strip():
                values.add(normalize_identifier(kind, value))
    for event in changes:
        change_kind = event.field_name.casefold()
        for changed_value in (event.old_value, event.new_value):
            if changed_value and changed_value.strip():
                values.add(normalize_identifier(change_kind, changed_value))

    return IdentityResolution(
        subject_id=subject_id,
        links=links,
        match_values=frozenset(values),
        coverage_issues=(),
        conflicts=(),
    )
