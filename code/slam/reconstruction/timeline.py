"""Time-cutoff filtering and deterministic event-sourced resource reconstruction."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from slam.contracts import AuditRequest, EvidenceBundle, Observation, ResourceState

from .identity import normalize_identifier

_ABSENT_STATES = frozenset({"ABSENT", "DELETED", "REMOVED", "PURGED"})
_DIRECT_NATURE = frozenset({"observation", "direct", "snapshot"})


@dataclass(frozen=True, slots=True)
class TimelineResult:
    eligible: tuple[Observation, ...]
    excluded_future: tuple[Observation, ...]
    states: tuple[ResourceState, ...]
    coverage_issues: tuple[str, ...]
    conflicts: tuple[str, ...]


def _canonical_values(observation: Observation) -> set[str]:
    values = {value.strip() for value in observation.subject_hints if value.strip()}
    for kind, value in observation.identifiers.items():
        if value.strip():
            base_kind = kind.removesuffix("_normalized")
            values.add(normalize_identifier(base_kind, value))
    extras = observation.fields.get("identifiers_all")
    if isinstance(extras, dict):
        for kind, listed in extras.items():
            if isinstance(listed, list):
                values.update(
                    normalize_identifier(str(kind), value)
                    for value in listed
                    if isinstance(value, str) and value.strip()
                )
    return values


def observation_matches(
    observation: Observation, identifiers: frozenset[str], subject_id: str | None
) -> bool:
    if subject_id and subject_id in observation.subject_hints:
        return True
    return bool(_canonical_values(observation) & identifiers)


def _source_capture_times(bundle: EvidenceBundle) -> dict[str, datetime]:
    return {source.source_id: source.captured_at for source in bundle.sources}


def _captured_at(observation: Observation, source_times: dict[str, datetime]) -> datetime:
    times = [
        source_times[span.source_id] for span in observation.spans if span.source_id in source_times
    ]
    return max(times, default=observation.effective_time)


def _evidence_ids(observations: list[Observation]) -> tuple[str, ...]:
    return tuple(
        sorted({span.source_id for observation in observations for span in observation.spans})
    )


def _nature_rank(observation: Observation) -> int:
    nature = str(observation.fields.get("evidence_nature", "observation")).casefold()
    return 1 if nature in _DIRECT_NATURE else 0


def _state(observation: Observation, scoped_sources: set[tuple[str, str]]) -> tuple[str, bool]:
    state = observation.observed_state.strip().upper()
    if state in _ABSENT_STATES:
        return "ABSENT", bool(observation.fields.get("uncertain"))
    if state == "NOT_FOUND":
        has_scope = any(
            (observation.system_id, span.source_id) in scoped_sources for span in observation.spans
        )
        return ("ABSENT", False) if has_scope else ("NOT_FOUND", True)
    uncertain = bool(observation.fields.get("uncertain"))
    return state, uncertain


def _build_state(
    observations: list[Observation],
    request: AuditRequest,
    source_times: dict[str, datetime],
    scoped_sources: set[tuple[str, str]],
) -> tuple[ResourceState, str | None]:
    direct = [observation for observation in observations if _nature_rank(observation) == 1]
    candidates = direct or observations
    latest_time = max(observation.effective_time for observation in candidates)
    latest = [
        observation for observation in candidates if observation.effective_time == latest_time
    ]
    latest_capture = max(_captured_at(observation, source_times) for observation in latest)
    terminal = [
        observation
        for observation in latest
        if _captured_at(observation, source_times) == latest_capture
    ]

    by_state: dict[str, list[Observation]] = defaultdict(list)
    uncertain = False
    for observation in terminal:
        state, item_uncertain = _state(observation, scoped_sources)
        by_state[state].append(observation)
        uncertain = uncertain or item_uncertain

    selected_state = sorted(by_state)[0]
    selected = by_state[selected_state]
    conflicting = [
        observation
        for state, items in sorted(by_state.items())
        if state != selected_state
        for observation in items
    ]
    conflict: str | None = None
    if conflicting:
        uncertain = True
        conflict = (
            f"resource:{selected[0].system_id}:{selected[0].resource_id}:"
            f"conflicting terminal states:{','.join(sorted(by_state))}"
        )

    first = selected[0]
    return (
        ResourceState(
            system_id=first.system_id,
            resource_id=first.resource_id,
            category=first.category,
            state=selected_state,
            at=request.audit_at,
            supporting_evidence_ids=_evidence_ids(selected),
            conflicting_evidence_ids=_evidence_ids(conflicting),
            uncertain=uncertain,
        ),
        conflict,
    )


def _cross_system_conflicts(
    states: list[ResourceState],
) -> tuple[list[ResourceState], list[str]]:
    by_resource: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, state in enumerate(states):
        by_resource[(state.resource_id, state.category)].append(index)

    conflicts: list[str] = []
    for (resource_id, category), indices in sorted(by_resource.items()):
        systems = {states[index].system_id for index in indices}
        values = {states[index].state for index in indices}
        present = bool(values & {"PRESENT", "ACTIVE", "RESTORABLE", "IDENTIFIABLE"})
        absent = "ABSENT" in values
        if len(systems) > 1 and present and absent:
            conflicts.append(
                f"replica:{resource_id}:{category}:conflicting states:{','.join(sorted(values))}"
            )
            for index in indices:
                states[index] = states[index].model_copy(update={"uncertain": True})
    return states, conflicts


def _issue_text(severity: str, code: str, source_id: str | None) -> str:
    return f"ingestion:{severity}:{code}:{source_id or 'global'}"


def reconstruct_timeline(
    request: AuditRequest,
    bundle: EvidenceBundle,
    identifiers: frozenset[str],
    subject_id: str | None,
    owned_resources: frozenset[str] = frozenset(),
) -> TimelineResult:
    """Filter subject observations by cutoff and fold them into resource state.

    ``owned_resources`` is resource-id closure (tier L2): once a resource is known to belong to
    the subject, every observation of it belongs too, even one that carries no identifier (a
    later 404 lookup, an anonymized readback).
    """

    source_times = _source_capture_times(bundle)
    matched_by_id = {
        observation.observation_id: observation
        for observation in bundle.observations
        if observation_matches(observation, identifiers, subject_id)
        or (observation.resource_id in owned_resources and observation.category != "SNAPSHOT_SCOPE")
    }
    matched = list(matched_by_id.values())
    eligible: list[Observation] = []
    future: list[Observation] = []
    for observation in matched:
        capture = _captured_at(observation, source_times)
        if observation.effective_time <= request.audit_at and capture <= request.audit_at:
            eligible.append(observation)
        else:
            future.append(observation)

    sort_key = lambda item: (  # noqa: E731
        item.effective_time,
        item.system_id,
        item.resource_id,
        item.observation_id,
    )
    eligible.sort(key=sort_key)
    future.sort(key=sort_key)

    global_scope = [
        observation
        for observation in bundle.observations
        if observation.category == "SNAPSHOT_SCOPE"
        and observation.effective_time <= request.audit_at
        and _captured_at(observation, source_times) <= request.audit_at
    ]
    scoped_sources = {
        (observation.system_id, span.source_id)
        for observation in global_scope
        for span in observation.spans
    }

    groups: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for observation in eligible:
        if observation.category != "SNAPSHOT_SCOPE":
            groups[(observation.system_id, observation.resource_id)].append(observation)

    states: list[ResourceState] = []
    conflicts: list[str] = []
    for key in sorted(groups):
        state, conflict = _build_state(groups[key], request, source_times, scoped_sources)
        states.append(state)
        if conflict:
            conflicts.append(conflict)
    states, replica_conflicts = _cross_system_conflicts(states)
    conflicts.extend(replica_conflicts)

    # Only sources this case can actually rely on. Evidence captured after the cutoff (the
    # `future` list) must not change the answer, not even through its parse problems.
    relevant_sources = {span.source_id for observation in eligible for span in observation.spans}
    postdated_sources = {sid for sid, taken in source_times.items() if taken > request.audit_at}
    coverage: list[str] = []
    for issue in bundle.issues:
        if issue.source_id in postdated_sources:
            continue
        # Planning must treat every coverage issue as blocking certification, so only issues
        # that can hide evidence qualify: any error, and warnings on sources this case uses.
        # Info notes (for example uninterpreted log noise) are the producer saying "nothing
        # is missing" and must not stop an otherwise complete case.
        severity = issue.severity.value
        if severity == "error" or (severity == "warning" and issue.source_id in relevant_sources):
            coverage.append(_issue_text(severity, issue.code, issue.source_id))
    for observation in eligible:
        if observation.fields.get("uncertain"):
            coverage.append(f"observation:{observation.observation_id}:uncertain")
    for source in bundle.sources:
        if source.parse_status.value != "parsed" and source.source_id in relevant_sources:
            coverage.append(f"source:{source.source_id}:{source.parse_status.value}")
    if not eligible:
        coverage.append("evidence:no eligible subject observations at audit cutoff")

    return TimelineResult(
        eligible=tuple(eligible),
        excluded_future=tuple(future),
        states=tuple(sorted(states, key=lambda item: (item.system_id, item.resource_id))),
        coverage_issues=tuple(sorted(set(coverage))),
        conflicts=tuple(sorted(set(conflicts))),
    )
