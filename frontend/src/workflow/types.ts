import type { AuditCase, Resource, Step } from "../types";

export interface DatasetInput {
  id: string;
  name: string;
  fingerprint: string;
  requests: number;
  sources: number;
  formats: Record<string, number>;
}
export interface CaseSummary {
  executable?: boolean;
  case_id: string;
  status: string | null;
  actions: number;
  steps: number;
  uncertain: boolean;
}
export interface RunInfo {
  request_count?: number;
  intelligence?: unknown;
  csv_available?: boolean;
  working_copies?: Record<string, string>;
  id: string;
  input: DatasetInput;
  status: string;
  cases: CaseSummary[];
  errors: Record<string, string>;
}
export interface Receipt {
  field_changes?: { path: string; before: unknown; after: unknown }[];
  id: string;
  system_id: string;
  resource_id: string;
  operation: string;
  at: string;
  before_state: string;
  state: string;
  sha256: string;
  verified: boolean;
}
export interface Action extends Step {
  error?: string;
  id: string;
  status: "pending" | "running" | "verified" | "failed";
  proof_id: string | null;
}
export interface WorkingRecord {
  fields?: Record<string, unknown>;
  system_id: string;
  resource_id: string;
  category: string;
  before_state: string;
  state: string;
  present: boolean;
  receipt: Receipt | null;
}
export interface Sandbox {
  id: string;
  run_id: string;
  case_id: string;
  input_fingerprint: string;
  scope: string;
  status: string;
  actions: Action[];
  records: WorkingRecord[];
  receipts: Receipt[];
  after: {
    at: string;
    answer: AuditCase["answer"];
    resources: Resource[];
    proof_id: string;
    source_sha256: string;
    remaining_flows: number;
    remaining_restores: number;
    scope: string;
  } | null;
}
