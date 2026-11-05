"""Public reconstruction interface for Manya's deterministic subsystem."""

from collections.abc import Mapping
from datetime import datetime

from slam.contracts import (
    AuditRequest,
    CaseContext,
    ConfidenceClass,
    EvidenceBundle,
    GraphEdge,
    IdentityLink,
    ResourceState,
)
from slam.runtime.events import emit
from slam.runtime.provider import ModelProvider

from .absence import infer_absent_states, retained_before_cutoff
from .graph import build_dependency_graph
from .identity import resolve_identity
from .linking import Attribution, CaseLinks, LinkModel
from .ownership import OwnerLink, build_owner_index, owned_by
from .request_intent import interpret_request
from .timeline import reconstruct_timeline


def _cited_evidence_times(
    bundle: EvidenceBundle,
    audit_at: datetime,
    states: tuple[ResourceState, ...],
    edges: tuple[GraphEdge, ...],
    identity_evidence: tuple[str, ...],
) -> dict[str, datetime]:
    """Capture time of every participant-visible id this context cites, never after the cutoff.

    Contract 1.1.0 lets a planner check citations from the context alone. Only ids that exist
    at ``audit_at`` are included, so an id that is absent here cannot be cited.
    """

    times: dict[str, datetime] = {}
    times.update({s.source_id: s.captured_at for s in bundle.sources})
    times.update({a.activity_id: a.occurred_at for a in bundle.activities})
    times.update({c.audit_id: c.changed_at for c in bundle.identity_changes})
    cited = {
        *identity_evidence,
        *(
            i
            for state in states
            for i in (*state.supporting_evidence_ids, *state.conflicting_evidence_ids)
        ),
        *(i for edge in edges for i in edge.evidence_ids),
    }
    return {i: times[i] for i in sorted(cited) if i in times and times[i] <= audit_at}


def reconstruct(
    request: AuditRequest,
    bundle: EvidenceBundle,
    *,
    provider: ModelProvider | None = None,
) -> CaseContext:
    """Frozen interface: explicit ownership (L1) and its closure (L2) only."""

    return reconstruct_with_links(request, bundle, None, provider=provider)


def reconstruct_with_links(
    request: AuditRequest,
    bundle: EvidenceBundle,
    link_model: LinkModel | None,
    *,
    provider: ModelProvider | None = None,
) -> CaseContext:
    """Convert one request and evidence bundle into a grounded cutoff context.

    ``link_model`` (from ``linking.fit``) adds tier-L3 attribution of resources that carry no
    identifier. With ``None`` only explicit ownership (L1) and its closure (L2) apply.
    """

    emit("stage.started", stage="intent")
    intent = interpret_request(request.request_text, provider)
    emit(
        "stage.completed",
        stage="intent",
        intent=intent.intent.value,
        basis=intent.basis,
        provider_issue=intent.provider_issue,
    )
    emit("stage.started", stage="identity")
    identity = resolve_identity(request, bundle)
    emit(
        "stage.completed",
        stage="identity",
        subject_id=identity.subject_id,
        identity_links=[link.model_dump(mode="json") for link in identity.links],
        evidence_times={
            k: v.isoformat()
            for k, v in _cited_evidence_times(
                bundle,
                request.audit_at,
                (),
                (),
                tuple(i for link in identity.links for i in link.evidence_ids),
            ).items()
        },
        coverage_issues=list(identity.coverage_issues),
        conflicts=list(identity.conflicts),
    )

    if intent.intent.value == "NON_DELETION":
        coverage = (intent.provider_issue,) if intent.provider_issue else ()
        return CaseContext(
            request=request,
            request_intent=intent.intent,
            policy_rules=bundle.policy_rules,
            subject_id=identity.subject_id,
            identity_links=identity.links,
            evidence_captured_at=_cited_evidence_times(
                bundle,
                request.audit_at,
                (),
                (),
                tuple(i for link in identity.links for i in link.evidence_ids),
            ),
            coverage_issues=tuple(sorted(set((*identity.coverage_issues, *coverage)))),
            unresolved_conflicts=identity.conflicts,
        )

    emit("stage.started", stage="ownership")
    index = link_model.owner_index if link_model else build_owner_index(bundle)
    explicit = owned_by(index, identity.subject_id, request.audit_at) if identity.subject_id else {}
    case_links = link_model.for_case(request.case_id) if link_model else None
    inferred = {a.resource_id: a for a in case_links.attributed} if case_links else {}
    owned = frozenset(explicit) | frozenset(inferred)
    emit(
        "stage.completed",
        stage="ownership",
        explicit_resources=sorted(explicit),
        attributed_resources=sorted(inferred),
        owned_resources=sorted(owned),
        candidate_count=len(case_links.candidates) if case_links else 0,
    )
    emit("stage.started", stage="timeline")
    timeline = reconstruct_timeline(
        request,
        bundle,
        identity.match_values,
        identity.subject_id,
        owned,
    )
    absent = infer_absent_states(request, bundle, set(owned), timeline.states)
    retained = frozenset(
        rule.category for rule in bundle.policy_rules if rule.required_action.upper() == "RETAIN"
    )
    late = retained_before_cutoff(
        request, timeline.excluded_future, retained, (*timeline.states, *absent)
    )
    all_states = tuple(
        sorted(
            (*timeline.states, *absent, *late), key=lambda item: (item.system_id, item.resource_id)
        )
    )
    ownership_links = _ownership_links(identity.subject_id, explicit, inferred, case_links)
    emit(
        "stage.completed",
        stage="timeline",
        resource_states=[s.model_dump(mode="json") for s in all_states],
        eligible_observation_ids=[o.observation_id for o in timeline.eligible],
        excluded_future_observation_ids=[o.observation_id for o in timeline.excluded_future],
        coverage_issues=list(timeline.coverage_issues),
        conflicts=list(timeline.conflicts),
    )
    emit("stage.started", stage="graph")
    graph = build_dependency_graph(
        request,
        bundle,
        timeline.eligible,
        all_states,
        identity.match_values,
        identity.subject_id,
    )
    emit(
        "stage.completed",
        stage="graph",
        active_flows=[e.model_dump(mode="json") for e in graph.active_flows],
        restore_risks=[e.model_dump(mode="json") for e in graph.restore_risks],
        ownership_links=[e.model_dump(mode="json") for e in ownership_links],
        evidence_times={
            k: v.isoformat()
            for k, v in _cited_evidence_times(
                bundle,
                request.audit_at,
                all_states,
                (*graph.active_flows, *graph.restore_risks),
                tuple(i for link in (*identity.links, *ownership_links) for i in link.evidence_ids),
            ).items()
        },
        coverage_issues=list(graph.coverage_issues),
        conflicts=list(graph.conflicts),
    )
    provider_issues = (intent.provider_issue,) if intent.provider_issue else ()
    coverage = tuple(
        sorted(
            set(
                (
                    *identity.coverage_issues,
                    *timeline.coverage_issues,
                    *graph.coverage_issues,
                    *provider_issues,
                )
            )
        )
    )
    conflicts = tuple(sorted(set((*identity.conflicts, *timeline.conflicts, *graph.conflicts))))
    return CaseContext(
        request=request,
        request_intent=intent.intent,
        policy_rules=bundle.policy_rules,
        subject_id=identity.subject_id,
        identity_links=(*identity.links, *ownership_links),
        evidence_captured_at=_cited_evidence_times(
            bundle,
            request.audit_at,
            all_states,
            (*graph.active_flows, *graph.restore_risks),
            tuple(i for link in (*identity.links, *ownership_links) for i in link.evidence_ids),
        ),
        eligible_observation_ids=tuple(
            observation.observation_id for observation in timeline.eligible
        ),
        excluded_future_observation_ids=tuple(
            observation.observation_id for observation in timeline.excluded_future
        ),
        resource_states=all_states,
        active_flows=graph.active_flows,
        restore_risks=graph.restore_risks,
        coverage_issues=coverage,
        unresolved_conflicts=conflicts,
    )


def _ownership_links(
    subject_id: str | None,
    explicit: Mapping[str, OwnerLink],
    inferred: Mapping[str, Attribution],
    case_links: CaseLinks | None,
) -> tuple[IdentityLink, ...]:
    """One link per owned resource, graded by how the ownership was established."""

    if subject_id is None:
        return ()
    links = [
        IdentityLink(
            left_identifier=subject_id,
            right_identifier=resource,
            relationship="owns_resource",
            evidence_ids=link.evidence_ids,
            confidence=ConfidenceClass.EXACT,
        )
        for resource, link in sorted(explicit.items())
    ]
    links += [
        _derived(subject_id, attribution, ConfidenceClass.CORROBORATED)
        for resource, attribution in sorted(inferred.items())
        if resource not in explicit
    ]
    if case_links is not None:
        links += [
            _derived(subject_id, candidate, ConfidenceClass.CANDIDATE)
            for candidate in case_links.candidates
        ]
    return tuple(links)


def _derived(
    subject_id: str, attribution: Attribution, confidence: ConfidenceClass
) -> IdentityLink:
    return IdentityLink(
        left_identifier=subject_id,
        right_identifier=attribution.resource_id,
        relationship="owns_resource",
        evidence_ids=attribution.activity_ids,
        confidence=confidence,
        review_required=True,
    )
