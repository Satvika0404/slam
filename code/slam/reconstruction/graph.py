"""Bounded dependency and recreation-risk graph construction.

Two rules keep the graph from inverting its own evidence:

* An observation becomes a data-flow or restore edge only when its *category* is exactly
  ``DATA_FLOW`` or ``BACKUP_ARCHIVE``. Plain records such as search-index entries and
  exports are remaining copies, not processes that copy data.
* An activity becomes an edge only when its type names an operation that creates a copy
  (sync, index, export, replicate, restore, ...). Checks, disables and blocks are
  *mitigations* or probes: ``DISABLE_DATA_FLOW`` and ``BLOCK_RESTORE`` must never be read
  as a flow or a restore risk, whatever words they happen to share with one.

Activity edges stay claim-grade (their relationship ends in ``_activity``); only the
``data_flow`` and ``restore_path`` edges rest on an observed state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import networkx as nx  # type: ignore[import-untyped]

from slam.contracts import (
    Activity,
    AuditRequest,
    EvidenceBundle,
    GraphEdge,
    Observation,
    ResourceState,
)

_FLOW_CATEGORY = "DATA_FLOW"
_RESTORE_CATEGORY = "BACKUP_ARCHIVE"
_RESTORABLE_STATES = frozenset({"RESTORABLE", "ACTIVE", "PRESENT"})

# Whole-word tokens of an activity type, e.g. SYNC_RECORD -> {"SYNC", "RECORD"}.
_FLOW_TOKENS = frozenset(
    {"SYNC", "IMPORT", "INDEX", "EXPORT", "REPLICATE", "REPLICATION", "COPY", "CONNECTOR", "FLOW"}
)
_RESTORE_TOKENS = frozenset({"RESTORE"})
# Any of these makes an activity a probe or a mitigation, never a source of recreation.
_NON_CREATING_TOKENS = frozenset(
    {
        "CHECK",
        "DISABLE",
        "BLOCK",
        "STOP",
        "PAUSE",
        "REVOKE",
        "VERIFY",
        "TEST",
        "VALIDATE",
        "INSPECT",
        "AUDIT",
        "READ",
        "LIST",
        "GET",
        "DENY",
        "CANCEL",
        "DELETE",
        "REMOVE",
        "REDACT",
        "ANONYMIZE",
        "RETAIN",
        "CLASSIFY",
        "LINK",
        "UPDATE",
        "REFRESH",
        "SEND",
        "NOTIFY",
    }
)
_INACTIVE = ("DISABLED", "INACTIVE", "STOPPED", "FAILED", "BLOCKED", "DENIED", "ERROR")


def classify_activity(activity_type: str) -> str | None:
    """``"flow"``, ``"restore"`` or ``None`` (not a copy-creating operation)."""

    tokens = {token for token in re.split(r"[^A-Z0-9]+", activity_type.upper()) if token}
    if tokens & _NON_CREATING_TOKENS:
        return None
    if tokens & _RESTORE_TOKENS:
        return "restore"
    if tokens & _FLOW_TOKENS:
        return "flow"
    return None


@dataclass(frozen=True, slots=True)
class GraphResult:
    active_flows: tuple[GraphEdge, ...]
    restore_risks: tuple[GraphEdge, ...]
    coverage_issues: tuple[str, ...]
    conflicts: tuple[str, ...]


def _source_fields(observation: Observation) -> dict[str, Any]:
    source = observation.fields.get("source")
    return dict(source) if isinstance(source, dict) else {}


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _evidence(observation: Observation) -> tuple[str, ...]:
    return tuple(sorted({span.source_id for span in observation.spans}))


def _active(state: str, reported: str | None = None) -> bool:
    material = f"{state} {reported or ''}".upper()
    return not any(word in material for word in _INACTIVE)


def _node(system: str | None, resource: str | None) -> str:
    if system and resource:
        return f"resource:{system}:{resource}"
    if system:
        return f"system:{system}"
    if resource:
        return f"resource:unknown:{resource}"
    return "system:unknown"


def _observation_edge(observation: Observation, relationship: str) -> GraphEdge:
    data = _source_fields(observation)
    source_system = _first(
        data,
        ("source_system", "origin_system", "upstream_system", "from_system", "source"),
    )
    source_resource = _first(
        data,
        ("source_resource_id", "upstream_resource_id", "from_resource_id"),
    )
    target_system = (
        _first(
            data,
            ("target_system", "destination_system", "downstream_system", "to_system"),
        )
        or observation.system_id
    )
    target_resource = (
        _first(
            data,
            ("target_resource_id", "downstream_resource_id", "to_resource_id"),
        )
        or observation.resource_id
    )
    source = _node(
        source_system or observation.system_id,
        source_resource or observation.resource_id,
    )
    target = _node(target_system, target_resource)
    return GraphEdge(
        source=source,
        target=target,
        relationship=relationship,
        evidence_ids=_evidence(observation),
        active=_active(observation.observed_state),
    )


def _activity_relevant(
    activity: Activity,
    resource_ids: set[str],
    identifiers: frozenset[str],
    subject_id: str | None,
) -> bool:
    if activity.resource_id and activity.resource_id in resource_ids:
        return True
    material = json.dumps(activity.attributes, sort_keys=True, default=str).casefold()
    candidates = set(identifiers)
    if subject_id:
        candidates.add(subject_id)
    return any(candidate.casefold() in material for candidate in candidates if candidate)


def _activity_edge(activity: Activity, relationship: str) -> GraphEdge:
    source_system = activity.attributes.get("source_system")
    target_system = activity.attributes.get("target_system") or activity.system_id
    return GraphEdge(
        source=_node(str(source_system) if source_system else None, activity.resource_id),
        target=_node(str(target_system) if target_system else None, activity.resource_id),
        relationship=relationship,
        evidence_ids=(activity.activity_id,),
        active=_active(activity.activity_type, activity.reported_result),
    )


def _merge_edges(edges: list[GraphEdge]) -> tuple[GraphEdge, ...]:
    merged: dict[tuple[str, str, str, bool], set[str]] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.relationship, edge.active)
        merged.setdefault(key, set()).update(edge.evidence_ids)
    return tuple(
        GraphEdge(
            source=source,
            target=target,
            relationship=relationship,
            active=active,
            evidence_ids=tuple(sorted(evidence_ids)),
        )
        for (source, target, relationship, active), evidence_ids in sorted(merged.items())
    )


def build_dependency_graph(
    request: AuditRequest,
    bundle: EvidenceBundle,
    eligible: tuple[Observation, ...],
    states: tuple[ResourceState, ...],
    identifiers: frozenset[str],
    subject_id: str | None,
) -> GraphResult:
    """Build active flow/restore edges and report bounded graph defects."""

    flows: list[GraphEdge] = []
    restores: list[GraphEdge] = []
    coverage: list[str] = []
    resource_ids = {state.resource_id for state in states}

    # A later observation of the same resource supersedes an earlier one: an ACTIVE connector
    # that a later snapshot shows DISABLED is no longer a flow. Ties at the latest time are all
    # kept, so a genuine same-time contradiction still surfaces both sides.
    latest: dict[tuple[str, str], datetime] = {}
    for observation in eligible:
        key = (observation.system_id, observation.resource_id)
        latest[key] = max(latest.get(key, observation.effective_time), observation.effective_time)

    for observation in eligible:
        if observation.effective_time != latest[(observation.system_id, observation.resource_id)]:
            continue
        category = observation.category.upper()
        if category == _FLOW_CATEGORY:
            edge = _observation_edge(observation, "data_flow")
            if edge.active:
                flows.append(edge)
        elif category == _RESTORE_CATEGORY and observation.observed_state.upper() in (
            _RESTORABLE_STATES
        ):
            edge = _observation_edge(observation, "restore_path")
            if edge.active:
                restores.append(edge)

    for activity in sorted(
        bundle.activities,
        key=lambda item: (item.occurred_at, item.activity_id),
    ):
        if activity.occurred_at > request.audit_at:
            continue
        kind = classify_activity(activity.activity_type)
        if kind is None:
            continue
        if not _activity_relevant(activity, resource_ids, identifiers, subject_id):
            continue
        if kind == "restore":
            edge = _activity_edge(activity, "restore_activity")
            if edge.active:
                restores.append(edge)
        else:
            edge = _activity_edge(activity, "data_flow_activity")
            if edge.active:
                flows.append(edge)

    active_flows = _merge_edges(flows)
    restore_risks = _merge_edges(restores)
    graph = nx.DiGraph()
    for edge in (*active_flows, *restore_risks):
        graph.add_edge(edge.source, edge.target, relationship=edge.relationship)

    conflicts: list[str] = []
    cyclic = [
        tuple(sorted(component))
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
    ]
    for component in sorted(cyclic):
        conflicts.append(f"graph:active cycle:{'|'.join(component)}")
    edges = graph_edges(active_flows, restore_risks)
    if any(edge.source == "system:unknown" or edge.target == "system:unknown" for edge in edges):
        coverage.append("graph:active edge has an unknown endpoint")

    return GraphResult(
        active_flows=active_flows,
        restore_risks=restore_risks,
        coverage_issues=tuple(sorted(set(coverage))),
        conflicts=tuple(sorted(set(conflicts))),
    )


def graph_edges(
    active_flows: tuple[GraphEdge, ...], restore_risks: tuple[GraphEdge, ...]
) -> tuple[GraphEdge, ...]:
    return (*active_flows, *restore_risks)
