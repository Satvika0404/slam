"""Who owns which resource: exact identifier co-occurrence (tier L1) from the evidence itself.

A resource belongs to a person when an observation (or an activity's own text) names the
resource together with one of that person's exact identifiers: email, email hash, phone or
user id, current or historical. Nothing here knows a system name, a category or an id
prefix; it works for any resource id in any bundle. Names never establish ownership.

Every link carries the evidence that created it and the moment that evidence became
available, so a case can ignore links that did not yet exist at its ``audit_at``.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from slam.contracts import EvidenceBundle

from .identity import normalize_identifier, normalize_phone
from .timeline import _canonical_values

_TOKEN = re.compile(r"[\w.+-]+@[\w.-]+\.\w+|\b[0-9a-f]{64}\b|\+\d[\d ()\-]{7,}\d|\buser_\w+")


@dataclass(frozen=True, slots=True)
class OwnerLink:
    evidence_ids: tuple[str, ...]
    established_at: datetime


OwnerIndex = dict[str, dict[str, OwnerLink]]  # resource_id -> user_id -> link


def identifier_index(bundle: EvidenceBundle) -> dict[str, str]:
    """Normalized identifier -> the one user who ever held it (ambiguous values are dropped)."""

    seen: dict[str, set[str]] = defaultdict(set)

    def add(kind: str, value: str | None, user: str) -> None:
        if value and value.strip():
            seen[normalize_identifier(kind, value)].add(user)

    for identity in bundle.current_identities:
        for kind, value in (
            ("user_id", identity.user_id),
            ("email", identity.email),
            ("phone", identity.phone),
            ("email_hash", identity.email_hash),
        ):
            add(kind, value, identity.user_id)
    for event in bundle.identity_changes:
        kind = event.field_name.casefold()
        if kind in {"email", "phone", "email_hash"}:
            add(kind, event.old_value, event.user_id)
            add(kind, event.new_value, event.user_id)
    return {value: next(iter(users)) for value, users in seen.items() if len(users) == 1}


def _lookup(index: dict[str, str], value: str) -> str | None:
    for variant in (value, value.strip(), value.casefold(), normalize_phone(value)):
        user = index.get(variant)
        if user is not None:
            return user
    return None


def build_owner_index(bundle: EvidenceBundle) -> OwnerIndex:
    index = identifier_index(bundle)
    captured = {source.source_id: source.captured_at for source in bundle.sources}
    owners: OwnerIndex = defaultdict(dict)

    def record(resource: str, user: str, evidence: tuple[str, ...], when: datetime) -> None:
        known = owners[resource].get(user)
        if known is None:
            owners[resource][user] = OwnerLink(evidence, when)
        else:
            owners[resource][user] = OwnerLink(
                tuple(sorted({*known.evidence_ids, *evidence})),
                min(known.established_at, when),
            )

    for observation in bundle.observations:
        if observation.category == "SNAPSHOT_SCOPE":
            continue
        users = {u for v in _canonical_values(observation) if (u := _lookup(index, v))}
        if not users:
            continue
        evidence = tuple(sorted({span.source_id for span in observation.spans}))
        when = max([observation.effective_time, *(captured[s] for s in evidence if s in captured)])
        for user in users:
            record(observation.resource_id, user, evidence, when)

    # An activity that names a person in its own text attests who owns its resource
    # (a catalog "linked X to <email>" entry). Activities without such text say nothing.
    for activity in bundle.activities:
        if not activity.resource_id:
            continue
        text = json.dumps(activity.attributes, default=str)
        users = {u for token in _TOKEN.findall(text) if (u := _lookup(index, token))}
        for user in users:
            record(activity.resource_id, user, (activity.activity_id,), activity.occurred_at)
    return {resource: dict(links) for resource, links in owners.items()}


def owners_as_of(index: OwnerIndex, resource: str, when: datetime) -> frozenset[str]:
    return frozenset(
        user for user, link in index.get(resource, {}).items() if link.established_at <= when
    )


def owned_by(index: OwnerIndex, user: str, when: datetime) -> dict[str, OwnerLink]:
    """Resources whose only owner at ``when`` is ``user`` (a shared resource is nobody's alone)."""

    return {
        resource: links[user]
        for resource, links in index.items()
        if user in links and owners_as_of(index, resource, when) == {user}
    }
