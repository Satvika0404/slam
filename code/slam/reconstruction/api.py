"""Public reconstruction interface for Manya's deterministic subsystem."""

from slam.contracts import AuditRequest, CaseContext, EvidenceBundle
from slam.runtime.events import emit
from slam.runtime.provider import ModelProvider

from .graph import build_dependency_graph
from .identity import resolve_identity
from .request_intent import interpret_request
from .timeline import reconstruct_timeline


def reconstruct(
    request: AuditRequest,
    bundle: EvidenceBundle,
    *,
    provider: ModelProvider | None = None,
) -> CaseContext:
    """Convert one request and evidence bundle into a grounded cutoff context."""

    evidence_times = {source.source_id: source.captured_at for source in bundle.sources}
    for activity in bundle.activities:
        evidence_times[activity.activity_id] = max(
            evidence_times.get(activity.activity_id, activity.occurred_at), activity.occurred_at
        )
    for change in bundle.identity_changes:
        evidence_times[change.audit_id] = max(
            evidence_times.get(change.audit_id, change.changed_at), change.changed_at
        )
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
            k: evidence_times[k].isoformat()
            for link in identity.links
            for k in link.evidence_ids
            if k in evidence_times
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
            evidence_captured_at=evidence_times,
            subject_id=identity.subject_id,
            identity_links=identity.links,
            coverage_issues=tuple(sorted(set((*identity.coverage_issues, *coverage)))),
            unresolved_conflicts=identity.conflicts,
        )

    emit("stage.started", stage="timeline")
    timeline = reconstruct_timeline(
        request,
        bundle,
        identity.match_values,
        identity.subject_id,
    )
    emit(
        "stage.completed",
        stage="timeline",
        resource_states=[s.model_dump(mode="json") for s in timeline.states],
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
        timeline.states,
        identity.match_values,
        identity.subject_id,
    )
    emit(
        "stage.completed",
        stage="graph",
        active_flows=[e.model_dump(mode="json") for e in graph.active_flows],
        restore_risks=[e.model_dump(mode="json") for e in graph.restore_risks],
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
        evidence_captured_at=evidence_times,
        subject_id=identity.subject_id,
        identity_links=identity.links,
        eligible_observation_ids=tuple(
            observation.observation_id for observation in timeline.eligible
        ),
        excluded_future_observation_ids=tuple(
            observation.observation_id for observation in timeline.excluded_future
        ),
        resource_states=timeline.states,
        active_flows=graph.active_flows,
        restore_risks=graph.restore_risks,
        coverage_issues=coverage,
        unresolved_conflicts=conflicts,
    )
