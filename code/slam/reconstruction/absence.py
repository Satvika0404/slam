"""Absence of an owned record, proven by a complete snapshot that lacks it.

A deleted record leaves no observation of its own, so "it is gone" cannot come from a row. It
comes from a *scoped* snapshot: evidence that a system was captured in full at some time. If an
owned resource is missing from the latest such snapshot at or before ``audit_at``, it was absent
then, and that snapshot is the citation. This is exactly why a finding can cite a file that does
not mention the resource at all.

Nothing is keyed to a particular system or id format: the system comes from the activities on the
resource, and the category from the majority category of the same id-prefix in the bundle.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime

from slam.contracts import AuditRequest, EvidenceBundle, Observation, ResourceState


def _prefix(resource_id: str) -> str:
    return re.sub(r"[_-]?\d+$", "", resource_id)


def category_by_prefix(bundle: EvidenceBundle) -> dict[str, str]:
    """Majority category per resource-id prefix, learned from the bundle (not built in)."""

    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for observation in bundle.observations:
        if observation.category != "SNAPSHOT_SCOPE":
            votes[_prefix(observation.resource_id)][observation.category] += 1
    return {prefix: counts.most_common(1)[0][0] for prefix, counts in sorted(votes.items())}


def infer_absent_states(
    request: AuditRequest,
    bundle: EvidenceBundle,
    owned: set[str],
    existing: tuple[ResourceState, ...],
) -> tuple[ResourceState, ...]:
    """ABSENT states for owned resources that have no observation but a complete snapshot lacks."""

    audit_at = request.audit_at
    captured: dict[str, datetime] = {s.source_id: s.captured_at for s in bundle.sources}
    have = {state.resource_id for state in existing}
    categories = category_by_prefix(bundle)

    scopes: dict[str, set[str]] = defaultdict(set)  # system -> sources that captured it in full
    for observation in bundle.observations:
        if observation.category != "SNAPSHOT_SCOPE" or observation.effective_time > audit_at:
            continue
        for span in observation.spans:
            if span.source_id in captured and captured[span.source_id] <= audit_at:
                scopes[observation.system_id].add(span.source_id)
    listed: dict[str, set[str]] = defaultdict(set)  # source -> resources it actually lists
    for observation in bundle.observations:
        if observation.category == "SNAPSHOT_SCOPE":
            continue
        for span in observation.spans:
            listed[span.source_id].add(observation.resource_id)

    systems: dict[str, set[str]] = defaultdict(set)
    for activity in bundle.activities:
        if (
            activity.resource_id in owned
            and activity.system_id
            and activity.occurred_at <= audit_at
        ):
            systems[activity.resource_id].add(activity.system_id)

    found: list[ResourceState] = []
    for resource in sorted(owned - have):
        category = categories.get(_prefix(resource))
        if category is None or len(systems.get(resource, ())) != 1:
            continue
        (system,) = systems[resource]
        proofs = sorted(
            (src for src in scopes.get(system, ()) if resource not in listed[src]),
            key=lambda src: (captured[src], src),
        )
        latest = max(scopes.get(system, ()), key=lambda src: (captured[src], src), default=None)
        if latest is None or latest not in proofs:
            continue  # the newest complete snapshot lists it, or there is no complete snapshot
        found.append(
            ResourceState(
                system_id=system,
                resource_id=resource,
                category=category,
                state="ABSENT",
                at=audit_at,
                supporting_evidence_ids=(latest,),
            )
        )
    return tuple(found)


def retained_before_cutoff(
    request: AuditRequest,
    late: tuple[Observation, ...],
    retained_categories: frozenset[str],
    existing: tuple[ResourceState, ...],
) -> tuple[ResourceState, ...]:
    """Retained records seen before the cutoff in evidence that was *exported* after it.

    A retention obligation does not depend on when a file was exported: if an event dated at
    or before ``audit_at`` shows a record in a category the policy retains, that record must still
    exist after any remediation. These states carry **no citation** (the file postdates the
    cutoff and may not be cited), so a planner may use them only as future verification steps,
    never as findings and never to certify a case ``COMPLETE``.
    """

    have = {(state.system_id, state.resource_id) for state in existing}
    found: dict[tuple[str, str], ResourceState] = {}
    for observation in late:
        key = (observation.system_id, observation.resource_id)
        if (
            observation.category in retained_categories
            and observation.observed_state.upper() == "PRESENT"
            and observation.effective_time <= request.audit_at
            and key not in have
        ):
            found[key] = ResourceState(
                system_id=observation.system_id,
                resource_id=observation.resource_id,
                category=observation.category,
                state="PRESENT",
                at=request.audit_at,
            )
    return tuple(found[key] for key in sorted(found))
