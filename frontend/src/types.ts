export type Mode = "demo" | "dataset";
export type Scene =
  | "portal"
  | "sources"
  | "identity"
  | "desk"
  | "timeline"
  | "decision"
  | "folio"
  | "observatory"
  | "console"
  | "run";
export interface Source {
  source_id: string;
  kind: string;
  origin: string;
  path: string;
  captured_at: string;
  sha256: string;
  parse_status: string;
}
export interface IdentityNode {
  id: string;
  label: string;
  kind: string;
  system_ids?: string[];
  entity_state?: string;
  entity_event_at?: string | null;
  entity_evidence_ids?: string[];
}
export interface IdentityEdge {
  id: string;
  source: string;
  target: string;
  relationship: string;
  state: string;
  evidence_ids: string[];
  valid_from: string | null;
  valid_to: string | null;
  verification_state?:
    "verified" | "confirmed" | "candidate" | "conflict" | "unknown" | null;
  directional?: boolean;
  evidence?: {
    source_id: string;
    captured_at: string | null;
    origin: string | null;
    locator: string | null;
    eligible: boolean;
    sha256?: string | null;
  }[];
  system_ids?: string[];
  event_at?: string | null;
  lifecycle_event?: {
    kind: "ended" | "removed" | "deleted";
    at: string;
    evidence_ids: string[];
    reason?: string | null;
  } | null;
  conflicting_evidence_ids?: string[];
}
export interface AuditEvent {
  id: string;
  time: string;
  captured_at: string;
  system: string;
  resource: string;
  state: string;
  evidence_id: string;
  eligible: boolean;
}
export interface Resource {
  system_id: string;
  resource_id: string;
  category: string;
  state: string;
  at: string;
  uncertain: boolean;
  supporting_evidence_ids: string[];
  conflicting_evidence_ids: string[];
}
export interface Step {
  step_no: number;
  phase: string;
  system_id: string;
  resource_id: string;
  operation: string;
  state: string;
  evidence_id: string;
}
export interface Stage {
  id: string;
  label: string;
  status: string;
  description: string;
}
export interface AuditCase {
  execution_export_csv?: string | null;
  mode: Mode;
  case_id: string;
  name: string;
  fingerprint: string;
  request: {
    case_id: string;
    email: string;
    request_text: string;
    requested_at: string;
    reported_at: string;
    audit_at: string;
    reported_status: string;
  };
  identity_nodes: IdentityNode[];
  identity_edges: IdentityEdge[];
  events: AuditEvent[];
  sources: Source[];
  context: {
    subject_id: string | null;
    resource_states: Resource[];
    policy_rules: {
      rule_id: string;
      category: string;
      required_action: string;
      condition: string | null;
    }[];
    coverage_issues: string[];
    unresolved_conflicts: string[];
    eligible_observation_ids: string[];
    excluded_future_observation_ids: string[];
    active_flows: {
      source: string;
      target: string;
      relationship: string;
      evidence_ids: string[];
      active: boolean;
    }[];
    restore_risks: {
      source: string;
      target: string;
      relationship: string;
      evidence_ids: string[];
      active: boolean;
    }[];
  };
  answer: {
    deletion_status: string | null;
    ready_for_export: boolean;
    steps: Step[];
    blocking_issues: string[];
    trace?: { not_certified_because?: string[]; [key: string]: unknown };
  };
  stages: Stage[];
  quality: {
    parsed_sources: number;
    expected_sources: number;
    observations: number;
    issues: { code: string; message: string; severity: string }[];
    conflicting_observation_groups: number;
  };
  evaluation: null;
}
export interface SceneProps {
  data: AuditCase;
  loading: boolean;
  onEvidence: (id: string) => void;
  onScene: (scene: Scene) => void;
  onCutoff: (value: string) => void;
}
export interface EvidenceDetail {
  truncated?: boolean;
  locators?: string[];
  pdf_page?: number | null;
  evidence_id: string;
  format: string;
  content: string;
  captured_at: string;
  sha256: string | null;
  locator: string;
  raw_available: boolean;
}
