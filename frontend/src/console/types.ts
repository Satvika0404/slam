export interface Forecast {
  slope: number;
  p: number | null;
  fc: { h: number; y: number; lo: number; hi: number }[];
  fit: number[];
}
export interface Pattern {
  id: string;
  name: string;
  group: string;
  signature: string;
  rule: string;
  kind: string;
  note: string;
  n: number;
  count: number;
  rate: number | null;
  ci: number[] | null;
  series: { m: string; n: number; c: number }[];
  slope: number;
  p: number | null;
  trend: string;
  forecast: Forecast["fc"];
  fit: number[];
  confidence: string;
  examples: string[];
}
export interface RegisterEntry {
  id: string;
  cat: string;
  title: string;
  n: number;
  unit: string;
  sev: string;
  rule: string;
  why: string;
  conflict: string;
  action: string;
  ev: string[];
}
export interface SystemNode {
  id: string;
  label: string;
  tier: string;
  category: string;
  rules: string;
  action: string;
  events: number | null;
  failures: number;
  fail_rate: number | null;
  next_bad: number | null;
  resources: number;
  snap_resources: number | null;
  snap_identifiers: number | null;
  blast_radius: number;
  betweenness: number;
  evidence_ids?: string[];
}
export interface SystemEdge {
  source: string;
  target: string;
  kind: string;
  op: string;
  events: number;
  fail_rate: number | null;
  active: boolean;
  restore: boolean;
  why?: string;
  evidence_ids?: string[];
}
export interface SystemGraph {
  nodes: SystemNode[];
  edges: SystemEdge[];
}
export interface ConsoleData {
  meta: {
    as_of: string;
    activity_from: string;
    activity_to: string;
    events: number;
    requests: number;
    evidence_files: number;
    sql_snapshots: number;
    rules: number;
    months: string[];
    month_labels: Record<string, string>;
    oct_partial_events: number;
    networkx: string;
  };
  kpis: {
    events: number;
    non_success: number;
    non_success_rate: number | null;
    destructive_n: number;
    destructive_bad: number;
    destructive_rate: number | null;
    reborn: number | null;
    flows_checked: number;
    flows_open_act: number;
    restore_checked: number;
    restore_open_act: number;
    ghost_rows: number | null;
    replica_tables: number;
  };
  rate_series: { m: string; n: number; bad: number; rate: number }[];
  ctrl_series: ConsoleData["rate_series"];
  rate_fc: Forecast;
  ctrl_fc: Forecast;
  count_fc: Forecast;
  patterns: Pattern[];
  heatmap: { systems: string[]; rows: { system: string; cells: number[][] }[] };
  systems_rank: {
    system: string;
    n: number;
    bad: number;
    rate: number;
    ci: number[];
    next_bad: number | null;
    next_lo: number | null;
    next_hi: number | null;
  }[];
  predictor: {
    table: {
      op: string;
      system: string;
      n: number;
      bad: number;
      n3: number;
      bad3: number;
      cls: string;
    }[];
    class_rate: Record<string, number>;
  };
  drift: {
    file_id: string;
    captured_at: string;
    topology: string;
    primary_rows: number;
    replica_rows: number;
    ghost_rows: number;
    ghost_with_identifiers: number;
    missing_rows?: number;
    diverged_rows?: number;
  }[];
  register: RegisterEntry[];
  aging: {
    bins: number[][];
    series: { label: string; system: string; total: number; bins: number[] }[];
  };
  retention: {
    audit_by_year: number[][];
    legal_by_year: number[][];
    legal_register: {
      order: string;
      user: string;
      kind: string;
      retain_until: string;
    }[];
    legal_file: string;
    security_extract: string;
    security_extract_note: string;
  };
  identifier_fields: {
    field: string;
    changes: number;
    over_365: number;
    users: number;
  }[];
  graph: SystemGraph;
  rules: { id: string; category: string; condition: string; action: string }[];
}
export type InspectEvidence = (id: string, context?: string) => void;
