"""Evidence quality checks and transparent coverage proxies.

These diagnostics describe input coverage and contradictions. They are not
probabilities that an audit answer is correct and never change case decisions.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, cast

import networkx as nx  # type: ignore[import-untyped]

from slam.contracts import CaseContext, EvidenceBundle

DETECTION_RULE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    code: str
    severity: str
    message: str
    source_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    stable_id: str = ""
    detection_rule_version: str = DETECTION_RULE_VERSION
    affected_resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceQualityReport:
    expected_sources: int
    accounted_sources: int
    source_accounting_fraction: float
    parsed_sources: int
    partial_sources: int
    failed_sources: int
    parse_success_fraction: float
    observations: int
    observations_with_source_links: int
    observation_provenance_fraction: float
    duplicate_content_groups: int
    conflicting_observation_groups: int
    identity_collision_groups: int
    ingestion_issue_counts: dict[str, int]
    issues: tuple[DataQualityIssue, ...]
    findings: tuple[DiagnosticFinding, ...] = ()
    impact: EvidenceImpactEstimate | None = None

    def to_dict(self) -> dict[str, Any]:
        # JSON round-trip also converts immutable tuples to report-native arrays.
        return cast(dict[str, Any], json.loads(json.dumps(asdict(self), default=str)))


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    stable_id: str
    code: str
    severity: str
    explanation: str
    source_references: tuple[str, ...] = ()
    observation_references: tuple[str, ...] = ()
    affected_resources: tuple[str, ...] = ()
    detection_rule_version: str = DETECTION_RULE_VERSION


@dataclass(frozen=True, slots=True)
class EvidenceImpactEstimate:
    """Observed counts and graph reachability; never a probability estimate."""

    directly_affected_cases: tuple[str, ...]
    directly_affected_resources: tuple[str, ...]
    potentially_reachable_systems: tuple[str, ...]
    potentially_reachable_resources: tuple[str, ...]
    evidence_coverage_gaps: tuple[str, ...]
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseCoverageEstimate:
    case_id: str
    dimensions_checked: int
    dimensions_supported: int
    coverage_fraction: float
    supported_dimensions: tuple[str, ...]
    missing_or_uncertain_dimensions: tuple[str, ...]
    interpretation: str = "evidence coverage proxy; not probability of answer correctness"


def analyze_evidence_quality(
    bundle: EvidenceBundle,
    *,
    expected_source_ids: tuple[str, ...] | None = None,
    contexts: tuple[CaseContext, ...] = (),
) -> EvidenceQualityReport:
    """Summarize parse coverage and flag duplicate/conflicting evidence patterns."""

    sources_by_id: dict[str, list[Any]] = defaultdict(list)
    for source in bundle.sources:
        sources_by_id[source.source_id].append(source)

    expected_ids = (
        set(expected_source_ids) if expected_source_ids is not None else set(sources_by_id)
    )
    accounted_ids = set(sources_by_id) & expected_ids
    parsed = sum(
        1
        for source_id in accounted_ids
        for source in sources_by_id[source_id]
        if source.parse_status.value == "parsed"
    )
    partial = sum(
        1
        for source_id in accounted_ids
        for source in sources_by_id[source_id]
        if source.parse_status.value == "partial"
    )
    failed = sum(
        1
        for source_id in accounted_ids
        for source in sources_by_id[source_id]
        if source.parse_status.value == "failed"
    )
    expected_count = len(expected_ids)
    source_accounting = len(accounted_ids) / expected_count if expected_count else 1.0
    parse_fraction = parsed / expected_count if expected_count else 1.0

    issues: list[DataQualityIssue] = []
    missing_ids = tuple(sorted(expected_ids - set(sources_by_id)))
    if missing_ids:
        issues.append(
            DataQualityIssue(
                code="MANIFEST_SOURCE_MISSING",
                severity="error",
                message=f"{len(missing_ids)} expected manifest source(s) have no SourceRecord",
                source_ids=missing_ids,
            )
        )
    repeated_source_ids = tuple(
        sorted(source_id for source_id, entries in sources_by_id.items() if len(entries) > 1)
    )
    if repeated_source_ids:
        issues.append(
            DataQualityIssue(
                code="DUPLICATE_SOURCE_ID",
                severity="error",
                message="A source_id is represented by multiple SourceRecord entries",
                source_ids=repeated_source_ids,
            )
        )

    content_groups: dict[str, list[str]] = defaultdict(list)
    for source in bundle.sources:
        content_groups[source.sha256].append(source.source_id)
    duplicate_groups = [tuple(sorted(ids)) for ids in content_groups.values() if len(set(ids)) > 1]
    for ids in duplicate_groups:
        issues.append(
            DataQualityIssue(
                code="DUPLICATE_SOURCE_CONTENT",
                severity="warning",
                message="Different source IDs have identical source content hashes",
                source_ids=ids,
            )
        )

    findings, impact = analyze_evidence_patterns(
        bundle, expected_source_ids=expected_source_ids, contexts=contexts
    )
    resource_groups: dict[tuple[str, str, str, str, str], list[Any]] = defaultdict(list)
    for observation in bundle.observations:
        key = (
            observation.system_id,
            observation.resource_id,
            observation.category,
            _scope_key(observation.fields),
            observation.effective_time.isoformat(),
        )
        resource_groups[key].append(observation)
    conflict_groups = 0
    for _key, observations in resource_groups.items():
        states = {observation.observed_state for observation in observations}
        if len(states) > 1:
            conflict_groups += 1
            issues.append(
                DataQualityIssue(
                    code="CONFLICTING_RESOURCE_OBSERVATIONS",
                    severity="error",
                    message=(
                        "Same system/resource/category/time has multiple observed states: "
                        + ", ".join(sorted(states))
                    ),
                    source_ids=tuple(
                        sorted(
                            {
                                span.source_id
                                for observation in observations
                                for span in observation.spans
                            }
                        )
                    ),
                    observation_ids=tuple(
                        sorted(observation.observation_id for observation in observations)
                    ),
                )
            )

    collisions = [finding for finding in findings if finding.code == "IDENTITY_COLLISION"]
    for finding in collisions:
        issues.append(
            DataQualityIssue(
                code="IDENTIFIER_LINKED_TO_MULTIPLE_USERS",
                severity="error",
                message=finding.explanation,
                subject_ids=tuple(
                    item.removeprefix("subject:") for item in finding.affected_resources
                ),
                stable_id=finding.stable_id,
                detection_rule_version=finding.detection_rule_version,
                affected_resources=finding.affected_resources,
            )
        )

    observation_count = len(bundle.observations)
    linked_count = sum(
        1
        for observation in bundle.observations
        if observation.spans and all(span.source_id in sources_by_id for span in observation.spans)
    )
    provenance_fraction = linked_count / observation_count if observation_count else 1.0
    if linked_count < observation_count:
        issues.append(
            DataQualityIssue(
                code="OBSERVATION_SOURCE_UNRESOLVED",
                severity="error",
                message=(
                    f"{observation_count - linked_count} observation(s) have a span whose "
                    "source_id is absent from the source inventory"
                ),
                observation_ids=tuple(
                    sorted(
                        observation.observation_id
                        for observation in bundle.observations
                        if any(span.source_id not in sources_by_id for span in observation.spans)
                    )
                ),
            )
        )

    severity_counts = Counter(issue.severity.value for issue in bundle.issues)
    return EvidenceQualityReport(
        expected_sources=expected_count,
        accounted_sources=len(accounted_ids),
        source_accounting_fraction=source_accounting,
        parsed_sources=parsed,
        partial_sources=partial,
        failed_sources=failed,
        parse_success_fraction=parse_fraction,
        observations=observation_count,
        observations_with_source_links=linked_count,
        observation_provenance_fraction=provenance_fraction,
        duplicate_content_groups=len(duplicate_groups),
        conflicting_observation_groups=conflict_groups,
        identity_collision_groups=len(collisions),
        ingestion_issue_counts=dict(sorted(severity_counts.items())),
        issues=tuple(issues),
        findings=findings,
        impact=impact,
    )


def analyze_evidence_patterns(
    bundle: EvidenceBundle,
    *,
    expected_source_ids: tuple[str, ...] | None = None,
    contexts: tuple[CaseContext, ...] = (),
) -> tuple[tuple[DiagnosticFinding, ...], EvidenceImpactEstimate]:
    """Find evidence defects and recreation patterns without changing source evidence.

    Incompatible facts are compared only for one system/resource/category/scope at the
    same effective instant. Separate replicas and snapshots at different times remain
    distinct. All output ordering and IDs are deterministic.
    """
    findings: list[DiagnosticFinding] = []

    def add(
        code: str,
        severity: str,
        explanation: str,
        *,
        sources: tuple[str, ...] = (),
        observations: tuple[str, ...] = (),
        resources: tuple[str, ...] = (),
    ) -> None:
        sources, observations, resources = (
            tuple(sorted(set(sources))),
            tuple(sorted(set(observations))),
            tuple(sorted(set(resources))),
        )
        seed = json.dumps(
            [DETECTION_RULE_VERSION, code, sources, observations, resources], separators=(",", ":")
        )
        stable_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        findings.append(
            DiagnosticFinding(
                stable_id, code, severity, explanation, sources, observations, resources
            )
        )

    source_ids = {item.source_id for item in bundle.sources}
    expected = set(expected_source_ids) if expected_source_ids is not None else source_ids
    for sid in sorted(expected - source_ids):
        add(
            "UNACCOUNTED_SOURCE",
            "error",
            "Expected manifest source has no SourceRecord.",
            sources=(sid,),
        )

    source_records = Counter(item.source_id for item in bundle.sources)
    for sid, count in sorted(source_records.items()):
        if count > 1:
            add(
                "DUPLICATE_SOURCE_ID",
                "error",
                "A source identifier is represented by multiple source records.",
                sources=(sid,),
            )
    for issue in bundle.issues:
        if issue.code == "SOURCE_NOT_IN_MANIFEST":
            reference = issue.locator or issue.source_id
            add(
                "UNACCOUNTED_SOURCE",
                "warning",
                "Evidence file exists outside the manifest and was not ingested.",
                sources=(reference,) if reference else (),
            )
    for source in bundle.sources:
        if source.parse_status.value != "parsed":
            add(
                "SOURCE_PARSE_INCOMPLETE",
                "error" if source.parse_status.value == "failed" else "warning",
                "Source parsing status is "
                f"{source.parse_status.value}; its content coverage may be incomplete.",
                sources=(source.source_id,),
            )

    duplicate_facts: dict[str, list[Any]] = defaultdict(list)
    for obs in bundle.observations:
        fact_payload = {
            "system": obs.system_id,
            "resource": obs.resource_id,
            "category": obs.category,
            "state": obs.observed_state.strip().casefold(),
            "scope": _scope_key(obs.fields),
            "effective_time": obs.effective_time.isoformat(),
            "identifiers": obs.identifiers,
            "fields": obs.fields,
        }
        fact_key = json.dumps(fact_payload, sort_keys=True, separators=(",", ":"), default=str)
        duplicate_facts[fact_key].append(obs)
        missing = tuple(span.source_id for span in obs.spans if span.source_id not in source_ids)
        if missing:
            add(
                "MISSING_PROVENANCE",
                "error",
                "Observation provenance references a source absent from the inventory.",
                sources=missing,
                observations=(obs.observation_id,),
                resources=(_resource_key(obs.system_id, obs.resource_id),),
            )
    for observations in duplicate_facts.values():
        if len(observations) > 1:
            add(
                "DUPLICATE_FACT",
                "warning",
                "The same scoped fact and effective time are supported by multiple observations.",
                sources=tuple(span.source_id for obs in observations for span in obs.spans),
                observations=tuple(obs.observation_id for obs in observations),
                resources=tuple(
                    _resource_key(obs.system_id, obs.resource_id) for obs in observations
                ),
            )

    groups: dict[tuple[str, str, str, str, datetime], list[Any]] = defaultdict(list)
    for obs in bundle.observations:
        groups[
            (
                obs.system_id,
                obs.resource_id,
                obs.category,
                _scope_key(obs.fields),
                obs.effective_time,
            )
        ].append(obs)
    for (system, resource, _category, _scope, instant), entries in sorted(groups.items()):
        states = {obs.observed_state.strip().casefold() for obs in entries}
        if len(states) > 1:
            add(
                "INCOMPATIBLE_OBSERVATIONS",
                "error",
                f"Different states share system/resource/category/scope at {instant.isoformat()}.",
                sources=tuple(span.source_id for obs in entries for span in obs.spans),
                observations=tuple(obs.observation_id for obs in entries),
                resources=(_resource_key(system, resource),),
            )

    hashes: dict[str, list[str]] = defaultdict(list)
    for source in bundle.sources:
        hashes[source.sha256].append(source.source_id)
    for source_ids_with_hash in hashes.values():
        unique = tuple(sorted(set(source_ids_with_hash)))
        if len(unique) > 1:
            add(
                "DUPLICATE_CONTENT",
                "warning",
                "Distinct source records have identical content hashes.",
                sources=unique,
            )

    _identity_collision_findings(bundle, add)
    observations_by_id: dict[str, list[Any]] = defaultdict(list)
    for observation in bundle.observations:
        observations_by_id[observation.observation_id].append(observation)
    for context in contexts:
        future_observations = tuple(sorted(set(context.excluded_future_observation_ids)))
        future_sources = tuple(
            sorted(
                {
                    span.source_id
                    for observation_id in future_observations
                    for observation in observations_by_id.get(observation_id, ())
                    for span in observation.spans
                }
            )
        )
        # The context omits post-cutoff timestamps from its citation map. Its explicit
        # exclusion list is the safe provenance trail for evidence that was filtered.
        if future_observations:
            add(
                "FUTURE_EVIDENCE",
                "warning",
                "Evidence captured or effective after audit_at was excluded for case "
                f"{context.request.case_id}.",
                sources=future_sources,
                observations=future_observations,
                resources=tuple(
                    _resource_key(state.system_id, state.resource_id)
                    for state in context.resource_states
                ),
            )

    # Build a deterministic directed graph from latest flow/archive observations and
    # case-reconstructed edges. An observed active edge is a potential path, not proof
    # that data actually moved.
    edges: list[tuple[str, str, str, bool, tuple[str, ...]]] = []
    latest: dict[tuple[str, str], datetime] = {}
    for obs in bundle.observations:
        if obs.category.upper() in {"DATA_FLOW", "BACKUP_ARCHIVE"}:
            key = (obs.system_id, obs.resource_id)
            latest[key] = max(latest.get(key, obs.effective_time), obs.effective_time)
    for obs in bundle.observations:
        kind = obs.category.upper()
        if (
            kind not in {"DATA_FLOW", "BACKUP_ARCHIVE"}
            or obs.effective_time != latest[(obs.system_id, obs.resource_id)]
        ):
            continue
        data = obs.fields.get("source")
        data = data if isinstance(data, dict) else {}
        src_system = (
            _first_text(data, "source_system", "origin_system", "upstream_system", "from_system")
            or obs.system_id
        )
        src_resource = (
            _first_text(data, "source_resource_id", "upstream_resource_id", "from_resource_id")
            or obs.resource_id
        )
        dst_system = (
            _first_text(
                data, "target_system", "destination_system", "downstream_system", "to_system"
            )
            or obs.system_id
        )
        dst_resource = (
            _first_text(data, "target_resource_id", "downstream_resource_id", "to_resource_id")
            or obs.resource_id
        )
        active = obs.observed_state.upper() not in {
            "DISABLED",
            "INACTIVE",
            "STOPPED",
            "FAILED",
            "BLOCKED",
            "DENIED",
            "ERROR",
        }
        if kind == "BACKUP_ARCHIVE" and obs.observed_state.upper() not in {
            "RESTORABLE",
            "ACTIVE",
            "PRESENT",
        }:
            active = False
        edges.append(
            (
                _resource_key(src_system, src_resource),
                _resource_key(dst_system, dst_resource),
                kind,
                active,
                tuple(sorted({span.source_id for span in obs.spans})),
            )
        )
    for context in contexts:
        for edge in (*context.active_flows, *context.restore_risks):
            edges.append(
                (edge.source, edge.target, edge.relationship, edge.active, tuple(edge.evidence_ids))
            )
    graph = nx.DiGraph()
    for left, right, kind, active, refs in sorted(set(edges)):
        graph.add_edge(left, right, kind=kind, active=active, refs=refs)
        if active:
            add(
                "ACTIVE_RECREATION_PATH",
                "warning",
                f"Active {kind} edge may copy or recreate data.",
                sources=refs,
                resources=(left, right),
            )
        if "unknown" in left.casefold() or "unknown" in right.casefold():
            add(
                "UNKNOWN_GRAPH_ENDPOINT",
                "warning",
                "A recreation edge has an endpoint with unknown identity.",
                sources=refs,
                resources=(left, right),
            )
    active_graph = graph.edge_subgraph(
        [(u, v) for u, v, data in graph.edges(data=True) if data["active"]]
    ).copy()
    components = [
        tuple(sorted(part))
        for part in nx.strongly_connected_components(active_graph)
        if len(part) > 1
    ]
    for component in sorted(components):
        in_cycle = [
            (u, v, data)
            for u, v, data in active_graph.edges(data=True)
            if u in component and v in component
        ]
        add(
            "RECREATION_CYCLE",
            "error",
            "Active recreation graph contains a directed cycle.",
            sources=tuple(ref for _, _, data in in_cycle for ref in data["refs"]),
            resources=component,
        )

    findings.sort(key=lambda f: (f.code, f.stable_id))
    direct = tuple(
        sorted({resource for finding in findings for resource in finding.affected_resources})
    )
    cases = tuple(
        sorted(
            {
                ctx.request.case_id
                for ctx in contexts
                if (f"subject:{ctx.subject_id}" in direct if ctx.subject_id else False)
                or any(
                    _resource_key(s.system_id, s.resource_id) in direct for s in ctx.resource_states
                )
            }
        )
    )
    seeds = {item for item in direct if item in graph}
    reachable = {node for seed in sorted(seeds) for node in nx.descendants(graph, seed)}
    potential_resources = tuple(sorted(reachable - set(direct)))
    potential_systems = tuple(
        sorted(
            {
                parts[1]
                for item in reachable
                if (parts := item.split(":", 2))[0] == "resource" and len(parts) == 3
            }
        )
    )
    coverage = tuple(
        sorted(
            f"{f.code}:{f.stable_id}"
            for f in findings
            if f.code
            in {
                "MISSING_PROVENANCE",
                "UNACCOUNTED_SOURCE",
                "SOURCE_PARSE_INCOMPLETE",
            }
        )
    )
    impact = EvidenceImpactEstimate(
        cases,
        direct,
        potential_systems,
        potential_resources,
        coverage,
        (
            "Reachability follows explicit active edges only.",
            "A finding is diagnostic evidence, not a policy or deletion decision.",
            "Identity validity uses change timestamps and current snapshot update times.",
        ),
        (
            "Case attribution requires supplied CaseContext objects.",
            "Unobserved systems and missing graph edges cannot be inferred.",
        ),
    )
    return tuple(findings), impact


def render_quality_markdown(report: EvidenceQualityReport) -> str:
    lines = [
        "# Evidence pattern diagnostics",
        "",
        f"Detection-rule version: `{DETECTION_RULE_VERSION}`",
        "",
        f"Findings: {len(report.findings)}",
        "",
        "Findings are advisory; heuristic reachability is not a probability.",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No configured rules produced findings.")
    for finding in report.findings:
        lines.extend(
            [
                f"### {finding.code} ({finding.severity})",
                "",
                finding.explanation,
                f"- Stable ID: `{finding.stable_id}`",
                f"- Sources: {', '.join(finding.source_references) or 'none'}",
                f"- Observations: {', '.join(finding.observation_references) or 'none'}",
                f"- Resources: {', '.join(finding.affected_resources) or 'none'}",
                "",
            ]
        )
    if report.impact is not None:
        impact = report.impact
        lines.extend(
            [
                "## Impact estimate",
                "",
                f"Direct cases: {', '.join(impact.directly_affected_cases) or 'unknown'}",
                f"Direct resources: {', '.join(impact.directly_affected_resources) or 'none'}",
                f"Potential systems: {', '.join(impact.potentially_reachable_systems) or 'none'}",
                "Potential resources: "
                f"{', '.join(impact.potentially_reachable_resources) or 'none'}",
                f"Coverage gaps: {', '.join(impact.evidence_coverage_gaps) or 'none'}",
                "",
                "### Assumptions",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in impact.assumptions)
        lines.extend(["", "### Unknowns", ""])
        lines.extend(f"- {item}" for item in impact.unknowns)
    return "\n".join(lines).rstrip() + "\n"


def write_quality_reports(
    report: EvidenceQualityReport, json_path: Any, markdown_path: Any
) -> None:
    """Write stable, UTF-8 JSON and Markdown reports."""
    from pathlib import Path

    js, md = Path(json_path), Path(markdown_path)
    js.parent.mkdir(parents=True, exist_ok=True)
    md.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md.write_text(render_quality_markdown(report), encoding="utf-8")


def _resource_key(system: str, resource: str) -> str:
    return f"resource:{system}:{resource}"


def _scope_key(fields: dict[str, Any]) -> str:
    for key in ("scope", "snapshot_scope", "table_scope", "region"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return "unspecified"


def _first_text(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _identity_collision_findings(bundle: EvidenceBundle, add: Any) -> None:
    intervals: dict[tuple[str, str], list[tuple[str, datetime | None, datetime | None, str]]] = (
        defaultdict(list)
    )
    for identity in bundle.current_identities:
        for kind, raw in (
            ("email", identity.email_normalized),
            ("phone", identity.phone),
            ("email_hash", identity.email_hash),
        ):
            value = _normalize_identifier(kind, raw)
            if value:
                intervals[(kind, value)].append(
                    (identity.user_id, identity.updated_at, None, identity.source_id)
                )
    histories: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in bundle.identity_changes:
        kind = event.field_name.casefold()
        if kind in {"email", "phone", "email_hash"}:
            histories[(event.user_id, kind)].append(event)
    for (user, kind), events in histories.items():
        events.sort(key=lambda event: (event.changed_at, event.audit_id))
        for index, event in enumerate(events):
            stop = events[index + 1].changed_at if index + 1 < len(events) else None
            for raw, start, end in (
                (event.old_value, None, event.changed_at),
                (event.new_value, event.changed_at, stop),
            ):
                value = _normalize_identifier(kind, raw or "")
                if value:
                    intervals[(kind, value)].append((user, start, end, event.audit_id))
    for (kind, _value), entries in sorted(intervals.items()):
        colliding: list[tuple[str, str]] = []
        for index, left in enumerate(entries):
            for right in entries[index + 1 :]:
                if left[0] == right[0]:
                    continue
                start = max((x for x in (left[1], right[1]) if x is not None), default=None)
                end = min((x for x in (left[2], right[2]) if x is not None), default=None)
                if start is None or end is None or start <= end:
                    colliding.extend(((left[0], left[3]), (right[0], right[3])))
        if colliding:
            owners = tuple(sorted({owner for owner, _ in colliding}))
            refs = tuple(sorted({ref for _, ref in colliding}))
            add(
                "IDENTITY_COLLISION",
                "error",
                f"Normalized {kind} identifier has overlapping validity intervals across users.",
                sources=refs,
                resources=tuple(f"subject:{owner}" for owner in owners),
            )


def estimate_case_coverage(context: CaseContext) -> CaseCoverageEstimate:
    """Report explicit evidence/reconstruction coverage dimensions for a case.

    This is a transparent fraction of satisfied checks, not a calibrated
    probability, model confidence, or substitute for the planner's decision.
    """

    dimensions = {
        "request_intent_resolved": context.request_intent.value != "UNCLEAR",
        "subject_resolved": bool(context.subject_id),
        "eligible_observations_present": bool(context.eligible_observation_ids),
        "resource_states_present": bool(context.resource_states),
        "no_unresolved_conflicts": not context.unresolved_conflicts,
        "no_declared_coverage_gaps": not context.coverage_issues,
    }
    supported = tuple(name for name, value in dimensions.items() if value)
    missing = tuple(name for name, value in dimensions.items() if not value)
    total = len(dimensions)
    return CaseCoverageEstimate(
        case_id=context.request.case_id,
        dimensions_checked=total,
        dimensions_supported=len(supported),
        coverage_fraction=len(supported) / total if total else 1.0,
        supported_dimensions=supported,
        missing_or_uncertain_dimensions=missing,
    )


def _normalize_identifier(kind: str, value: str | None) -> str:
    if not value:
        return ""
    if kind.lower() == "phone":
        return _normalize_phone(value)
    return value.strip().lower()


def _normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())
