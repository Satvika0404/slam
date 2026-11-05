"""Validated API read models, separate from the shared engine contract."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from slam.contracts import AuditRequest, CaseAnswer, CaseContext, SourceRecord


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityNode(WebModel):
    id: str
    label: str
    kind: str


class IdentityEvidence(WebModel):
    source_id: str
    captured_at: datetime | None
    origin: str | None
    locator: str | None
    eligible: bool
    sha256: str | None = None


class RelationshipEvent(WebModel):
    kind: Literal["ended", "removed", "deleted"]
    at: datetime
    evidence_ids: list[str]
    reason: str | None = None


class IdentityEdge(WebModel):
    id: str
    source: str
    target: str
    relationship: str
    state: Literal["future", "candidate", "historical", "verified", "unknown"]
    evidence_ids: list[str]
    valid_from: datetime | None
    valid_to: datetime | None
    verification_state: (
        Literal["verified", "confirmed", "candidate", "conflict", "unknown"] | None
    ) = None
    directional: bool = False
    evidence: list[IdentityEvidence] = Field(default_factory=list)
    system_ids: list[str] = Field(default_factory=list)
    event_at: datetime | None = None
    lifecycle_event: RelationshipEvent | None = None
    conflicting_evidence_ids: list[str] = Field(default_factory=list)


class TimelineEvent(WebModel):
    id: str
    time: datetime
    captured_at: datetime
    system: str
    resource: str
    state: str
    evidence_id: str
    eligible: bool


class DecisionStage(WebModel):
    id: Literal["judge", "evidence", "verify"]
    label: str
    status: Literal[
        "PASSED", "NOT SATISFIED", "INSUFFICIENT EVIDENCE", "CONFLICT DETECTED", "NOT EVALUATED"
    ]
    description: str


class CaseView(WebModel):
    mode: Literal["demo", "dataset"]
    case_id: str
    name: str
    request: AuditRequest
    identity_nodes: list[IdentityNode]
    identity_edges: list[IdentityEdge]
    events: list[TimelineEvent]
    sources: list[SourceRecord]
    context: CaseContext
    answer: CaseAnswer
    stages: list[DecisionStage]
    quality: dict[str, Any]
    evaluation: dict[str, Any] | None
    fingerprint: str
