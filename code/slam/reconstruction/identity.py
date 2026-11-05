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


_SNAPSHOT_FIELDS = ("email", "phone", "email_hash", "name")


def _rolled_back(
    identity: CurrentIdentity, later: list[IdentityChangeEvent]
) -> tuple[CurrentIdentity, frozenset[str]]:
    """The snapshot as it stood at the cutoff, plus the fields that had to be rolled back.

    The identity snapshot is the *latest* state. A change made after ``audit_at`` is
    undone by restoring its ``old_value``, newest change first, so a value that only
    became true after the audit is never used to match or link anything.
    """

    values = {
        "email": identity.email,
        "phone": identity.phone,
        "email_hash": identity.email_hash,
        "name": identity.name,
    }
    restored: set[str] = set()
    for event in sorted(later, key=lambda item: (item.changed_at, item.audit_id), reverse=True):
        field_name = event.field_name.casefold()
        if field_name in values:
            values[field_name] = event.old_value or ""
            restored.add(field_name)
    if not restored:
        return identity, frozenset()
    return (
        identity.model_copy(
            update={**values, "email_normalized": normalize_email(values["email"])}
        ),
        frozenset(restored),
    )


def _as_of_view(
    request: AuditRequest, bundle: EvidenceBundle
) -> tuple[list[CurrentIdentity], dict[str, frozenset[str]], list[IdentityChangeEvent]]:
    """Identity data restricted to what was true at ``audit_at``.

    Returns the rolled-back snapshots, which fields were rolled back per user, and only
    the change events dated at or before the cutoff. Events after the cutoff are neither
    used nor cited.
    """

    visible = [e for e in bundle.identity_changes if e.changed_at <= request.audit_at]
    later: dict[str, list[IdentityChangeEvent]] = defaultdict(list)
    for event in bundle.identity_changes:
        if event.changed_at > request.audit_at:
            later[event.user_id].append(event)
    identities: list[CurrentIdentity] = []
    restored: dict[str, frozenset[str]] = {}
    for identity in bundle.current_identities:
        view, fields = _rolled_back(identity, later.get(identity.user_id, []))
        identities.append(view)
        if fields:
            restored[identity.user_id] = fields
    return identities, restored, visible


def _email_candidates(
    request: AuditRequest,
    identities: list[CurrentIdentity],
    events: list[IdentityChangeEvent],
) -> set[str]:
    wanted = normalize_email(request.email)
    candidates = {
        identity.user_id
        for identity in identities
        if identity.email_normalized.casefold() == wanted
        or normalize_email(identity.email) == wanted
    }
    for event in events:
        if event.field_name.casefold() != "email":
            continue
        values = (event.old_value, event.new_value)
        if any(value is not None and normalize_email(value) == wanted for value in values):
            candidates.add(event.user_id)
    return candidates


def _current_links(
    identity: CurrentIdentity, restored: frozenset[str] = frozenset()
) -> list[IdentityLink]:
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
                # A rolled-back value is derived from the audit history, not read directly
                # from the snapshot, so it is corroborated rather than exact.
                confidence=(
                    ConfidenceClass.CORROBORATED if kind in restored else ConfidenceClass.EXACT
                ),
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

    identities, restored, events = _as_of_view(request, bundle)
    candidates = _email_candidates(request, identities, events)
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
    current = [identity for identity in identities if identity.user_id == subject_id]
    changes = [event for event in events if event.user_id == subject_id]
    links = _deduplicate(
        [
            link
            for identity in current
            for link in _current_links(identity, restored.get(identity.user_id, frozenset()))
        ]
        + _change_links(changes)
    )

    # Identifiers that may attach *evidence* to this subject. A person's name is deliberately
    # absent: two different people can share an exact name, and a name alone is not
    # corroboration. Names stay in `links` as facts about the subject.
    values: set[str] = {subject_id, normalize_email(request.email)}
    for identity in current:
        for kind, value in (
            ("email", identity.email),
            ("phone", identity.phone),
            ("email_hash", identity.email_hash),
        ):
            if value.strip():
                values.add(normalize_identifier(kind, value))
    for event in changes:
        change_kind = event.field_name.casefold()
        if change_kind == "name":
            continue
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
