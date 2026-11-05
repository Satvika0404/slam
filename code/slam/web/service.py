"""Read models for the UI. Python owns reconstruction, policy and verification."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from slam.contracts import AuditRequest, CaseAnswer, CaseContext, EvidenceBundle, RequestIntent
from slam.evaluation.data_quality import analyze_evidence_quality
from slam.ingestion import ingest, load_requests
from slam.planning.engine import plan_case
from slam.reconstruction import linking, reconstruct_with_links

from .demo import corpus


@lru_cache(maxsize=1)
def dataset(root: str) -> tuple[tuple[AuditRequest, ...], EvidenceBundle]:
    path = Path(root)
    if not (path / "deletion_requests.csv").is_file():
        raise FileNotFoundError(
            "Participant dataset is not installed. Demo is available separately."
        )
    return load_requests(path), ingest(path)


def case_list(mode: str, root: Path) -> list[dict[str, str]]:
    if mode == "demo":
        return [
            {"case_id": key, "name": "Mara Vale", "label": label}
            for key, label in (
                ("demo_024", "The surviving copy"),
                ("demo_025", "The verified absence"),
                ("demo_026", "The conflicting accounts"),
            )
        ]
    requests, bundle = dataset(str(root))
    names = {item.email_normalized: item.name for item in bundle.current_identities}
    return [
        {
            "case_id": r.case_id,
            "name": names.get(r.email.lower(), "Identity unresolved"),
            "label": r.case_id,
        }
        for r in requests
    ]


def inputs(
    case_id: str, mode: str, root: Path
) -> tuple[AuditRequest, EvidenceBundle, dict[str, str]]:
    if mode == "demo":
        return corpus(case_id)
    requests, bundle = dataset(str(root))
    request = next((r for r in requests if r.case_id == case_id), None)
    if request is None:
        raise KeyError(case_id)
    return request, bundle, {}


def source_detail(evidence_id: str, case_id: str, mode: str, root: Path) -> dict[str, Any]:
    _, bundle, documents = inputs(case_id, mode, root)
    row = next((item for item in bundle.sources if item.source_id == evidence_id), None)
    if row is None:
        change = next(
            (item for item in bundle.identity_changes if item.audit_id == evidence_id), None
        )
        if change is not None:
            return {
                "evidence_id": evidence_id,
                "format": "CSV",
                "content": change.model_dump_json(indent=2),
                "captured_at": change.changed_at.isoformat(),
                "sha256": None,
                "locator": "Identity audit row",
                "raw_available": False,
            }
        identity = next(
            (item for item in bundle.current_identities if item.source_id == evidence_id), None
        )
        if identity is not None:
            return {
                "evidence_id": evidence_id,
                "format": "CSV",
                "content": identity.model_dump_json(indent=2),
                "captured_at": identity.updated_at.isoformat(),
                "sha256": None,
                "locator": "Current identity snapshot row / updated_at",
                "raw_available": False,
            }
        activity = next(
            (item for item in bundle.activities if item.activity_id == evidence_id), None
        )
        if activity is None:
            raise KeyError(evidence_id)
        return {
            "evidence_id": evidence_id,
            "format": "CSV",
            "content": activity.model_dump_json(indent=2),
            "captured_at": activity.occurred_at.isoformat(),
            "sha256": None,
            "locator": "Activity row",
            "raw_available": False,
        }
    content = documents.get(evidence_id)
    truncated = False
    if content is None:
        path = (root / row.path).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Unsafe evidence path")
        if row.kind.value in {"json", "csv", "log", "text", "sql"} and path.is_file():
            with path.open("rb") as handle:
                preview = handle.read(131073)
            truncated = len(preview) > 131072
            content = preview[:131072].decode("utf-8", errors="replace")
        else:
            content = "Open the original PDF/image to inspect this source."
    observations = [
        o.model_dump(mode="json")
        for o in bundle.observations
        if any(s.source_id == evidence_id for s in o.spans)
    ]
    locators: set[str] = set()
    pages: list[int] = []
    for observation in bundle.observations:
        for span in observation.spans:
            if span.source_id != evidence_id:
                continue
            if span.line_range:
                locators.add(f"Lines {span.line_range.start}-{span.line_range.end}")
            elif span.json_path:
                locators.add(f"JSON path {span.json_path}")
            elif span.table_row:
                locators.add(f"Table {span.table_row.table}, row {span.table_row.row}")
            elif span.pdf_position:
                pages.append(span.pdf_position.page)
                locators.add(f"PDF page {span.pdf_position.page}")
            elif span.image_region:
                region = span.image_region
                locators.add(
                    f"Image region x={region.x}, y={region.y}, {region.width}x{region.height}"
                )
    return {
        "evidence_id": evidence_id,
        "format": row.kind.value.upper(),
        "content": content,
        "captured_at": row.captured_at.isoformat(),
        "sha256": row.sha256,
        "locator": row.path,
        "raw_available": mode != "demo",
        "observations": observations,
        "locators": sorted(locators),
        "pdf_page": min(pages) if pages else None,
        "truncated": truncated,
    }


def search(case_id: str, mode: str, root: Path, query: str) -> list[str]:
    _, bundle, documents = inputs(case_id, mode, root)
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE VIRTUAL TABLE evidence USING fts5(source_id UNINDEXED, content)")
        for row in bundle.sources:
            text = documents.get(
                row.source_id,
                " ".join(
                    o.model_dump_json()
                    for o in bundle.observations
                    if any(s.source_id == row.source_id for s in o.spans)
                ),
            )
            db.execute("INSERT INTO evidence VALUES (?, ?)", (row.source_id, text))
        terms = query.split()[:20]
        expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        if not expression:
            return [s.source_id for s in bundle.sources]
        return [
            row[0]
            for row in db.execute(
                "SELECT source_id FROM evidence WHERE evidence MATCH ? ORDER BY rank LIMIT 100",
                (expression,),
            )
        ]


def case_view(
    case_id: str,
    mode: str,
    root: Path,
    cutoff: datetime | None = None,
    *,
    prepared: tuple[AuditRequest, EvidenceBundle, CaseContext, CaseAnswer] | None = None,
) -> dict[str, Any]:
    if prepared is not None:
        request, bundle, context, answer = prepared
    else:
        request, bundle, _ = inputs(case_id, mode, root)
        if cutoff is not None:
            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                raise ValueError("Audit cutoff must include a timezone")
            request = request.model_copy(update={"audit_at": cutoff})
        cohort = dataset(str(root))[0] if mode == "dataset" else (request,)
        context = reconstruct_with_links(request, bundle, linking.fit(bundle, cohort))
        if request.audit_at < request.requested_at:
            context = context.model_copy(
                update={
                    "coverage_issues": (
                        *context.coverage_issues,
                        "Selected cutoff precedes the deletion request.",
                    )
                }
            )
        answer = plan_case(context, bundle)
    if cutoff is not None and (cutoff.tzinfo is None or cutoff.utcoffset() is None):
        raise ValueError("Audit cutoff must include a timezone")
    eligible = set(context.eligible_observation_ids)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    relation_times = dict(context.evidence_captured_at)
    for identity in bundle.current_identities:
        relation_times.setdefault(identity.source_id, identity.updated_at)
    source_records = {s.source_id: s for s in bundle.sources}
    changes_by_id = {e.audit_id: e for e in bundle.identity_changes}
    for link in context.identity_links:
        visible = [
            key
            for key in link.evidence_ids
            if key in relation_times and relation_times[key] <= request.audit_at
        ]
        historical = bool(link.valid_to and link.valid_to <= request.audit_at)
        state = (
            "unknown"
            if any(key not in relation_times for key in link.evidence_ids)
            else "future"
            if not visible
            else "candidate"
            if link.review_required or link.confidence.value == "CANDIDATE"
            else "historical"
            if historical
            else "verified"
        )
        for value in (link.left_identifier, link.right_identifier):
            field_kind = (
                link.relationship.removeprefix("current_")
                .removeprefix("historical_")
                .removeprefix("changed_")
                .removesuffix("_change")
            )
            kind = (
                "subject"
                if value == context.subject_id
                else "email"
                if "@" in value
                else "hash"
                if len(value) == 64
                else "resource"
                if link.relationship == "owns_resource"
                else "phone"
                if field_kind == "phone"
                else "name"
                if field_kind == "name"
                else "identifier"
            )
            nodes.setdefault(value, {"id": value, "label": value, "kind": kind})
        evidence = []
        for key in link.evidence_ids:
            row = source_records.get(key)
            change = changes_by_id.get(key)
            captured = relation_times.get(key)
            evidence.append(
                {
                    "source_id": key,
                    "captured_at": captured.isoformat() if captured else None,
                    "origin": row.origin
                    if row
                    else "Identity audit log"
                    if change
                    else "Current identity snapshot"
                    if captured
                    else None,
                    "locator": row.path
                    if row
                    else f"user_audit_log.csv / {key}"
                    if change
                    else "Current identity snapshot row"
                    if captured
                    else None,
                    "eligible": bool(captured and captured <= request.audit_at),
                    "sha256": row.sha256 if row else None,
                }
            )
        change_events = [changes_by_id[k] for k in link.evidence_ids if k in changes_by_id]
        event_at = max((e.changed_at for e in change_events), default=None)
        # A validity end is evidence of an ended association, never proof of entity deletion.
        lifecycle_event = (
            {
                "kind": "ended",
                "at": link.valid_to.isoformat(),
                "evidence_ids": list(link.evidence_ids),
                "reason": f"{change_events[0].field_name} changed in the identity audit log"
                if change_events
                else None,
            }
            if link.valid_to is not None and visible
            else None
        )
        systems = sorted(
            {
                o.system_id
                for o in bundle.observations
                if o.observation_id in eligible
                and any(s.source_id in link.evidence_ids for s in o.spans)
            }
        )
        edges.append(
            {
                "id": "edge_" + hashlib.sha256(link.model_dump_json().encode()).hexdigest()[:16],
                "source": link.left_identifier,
                "target": link.right_identifier,
                "relationship": link.relationship,
                "state": state,
                "evidence_ids": list(link.evidence_ids),
                "valid_from": link.valid_from.isoformat() if link.valid_from else None,
                "valid_to": link.valid_to.isoformat() if link.valid_to else None,
                "verification_state": "candidate"
                if state == "candidate"
                else "unknown"
                if state in {"unknown", "future"}
                else "confirmed"
                if link.confidence.value == "CORROBORATED"
                else "verified",
                "directional": link.relationship.endswith("_change"),
                "evidence": evidence,
                "system_ids": systems,
                "event_at": event_at.isoformat() if event_at else None,
                "lifecycle_event": lifecycle_event,
                "conflicting_evidence_ids": [],
            }
        )
    events = [
        {
            "id": o.observation_id,
            "time": o.effective_time.isoformat(),
            "captured_at": max(
                (
                    s.captured_at
                    for s in bundle.sources
                    if any(p.source_id == s.source_id for p in o.spans)
                ),
                default=o.effective_time,
            ).isoformat(),
            "system": o.system_id,
            "resource": o.resource_id,
            "state": o.observed_state,
            "evidence_id": o.spans[0].source_id,
            "eligible": o.observation_id in eligible,
        }
        for o in bundle.observations
        if o.observation_id in eligible
        or o.observation_id in context.excluded_future_observation_ids
    ]
    assessments = answer.trace.get("policy_assessments", [])
    judge_pass = bool(context.resource_states) and (
        len(assessments) == len(context.resource_states)
        or answer.trace.get("relevant_resources") == len(context.resource_states)
    )
    evidence_state = (
        "CONFLICT DETECTED"
        if context.unresolved_conflicts
        else "INSUFFICIENT EVIDENCE"
        if context.coverage_issues
        or not context.eligible_observation_ids
        or any(
            "evidence" in issue or "identity" in issue or "uncertain" in issue
            for issue in answer.blocking_issues
        )
        else "PASSED"
    )
    verify = (
        "PASSED"
        if answer.deletion_status and answer.deletion_status.value == "COMPLETE"
        else "NOT SATISFIED"
        if answer.ready_for_export
        else "CONFLICT DETECTED"
        if context.unresolved_conflicts
        else "INSUFFICIENT EVIDENCE"
    )
    judge_state = "PASSED" if judge_pass else "INSUFFICIENT EVIDENCE"
    if context.request_intent is RequestIntent.NON_DELETION:
        judge_state = evidence_state = verify = "NOT EVALUATED"
    quality = analyze_evidence_quality(bundle)
    return {
        "mode": mode,
        "case_id": case_id,
        "name": next(
            (
                i.name
                for i in bundle.current_identities
                if i.user_id == context.subject_id and i.updated_at <= request.audit_at
            ),
            "Unresolved subject",
        ),
        "request": request.model_dump(mode="json"),
        "identity_nodes": list(nodes.values()),
        "identity_edges": edges,
        "events": sorted(events, key=lambda e: str(e["time"])),
        "sources": [s.model_dump(mode="json") for s in bundle.sources],
        "context": context.model_dump(mode="json"),
        "answer": answer.model_dump(mode="json"),
        "stages": [
            {
                "id": "judge",
                "label": "Judge",
                "status": judge_state,
                "description": "Supplied policy rules determine the required treatment.",
            },
            {
                "id": "evidence",
                "label": "Evidence",
                "status": evidence_state,
                "description": "Identity, source provenance and audit eligibility are checked.",
            },
            {
                "id": "verify",
                "label": "Verify",
                "status": verify,
                "description": "Deterministic state checks; proposed actions remain unexecuted.",
            },
        ],
        "quality": quality.to_dict(),
        "evaluation": None,
        "fingerprint": hashlib.sha256(
            (case_id + request.audit_at.isoformat()).encode()
        ).hexdigest()[:12],
    }
