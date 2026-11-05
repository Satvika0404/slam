import type { AuditCase } from "../types";
import type { ConsoleData, Forecast, SystemGraph, SystemNode } from "./types";

export const number = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-GB", { maximumFractionDigits: 1 });
export const percent = (n: number | null | undefined) =>
  n == null ? "Not measured" : `${(n * 100).toFixed(1)}%`;
export const human = (s: string) => s.replaceAll("_", " ");
export const date = (s: string) =>
  new Date(s).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
export const edgeKey = (e: { source: string; target: string }) =>
  JSON.stringify([e.source, e.target]);

export function walk(
  graph: SystemGraph,
  start: string,
  reverse = false,
): string[] {
  const seen = new Set([start]);
  const queue = [start];
  for (let i = 0; i < queue.length; i++) {
    for (const edge of graph.edges) {
      const from = reverse ? edge.target : edge.source;
      const to = reverse ? edge.source : edge.target;
      if (from === queue[i] && !seen.has(to)) {
        seen.add(to);
        queue.push(to);
      }
    }
  }
  return queue.slice(1).sort();
}

/** SCC condensation gives a deterministic order even when flows form a cycle. */
export function graphLayers(graph: SystemGraph): Map<string, number> {
  let index = 0;
  const indices = new Map<string, number>(),
    low = new Map<string, number>();
  const stack: string[] = [],
    active = new Set<string>(),
    components: string[][] = [];
  function visit(id: string) {
    indices.set(id, index);
    low.set(id, index++);
    stack.push(id);
    active.add(id);
    for (const e of graph.edges.filter((e) => e.source === id)) {
      if (!indices.has(e.target)) {
        visit(e.target);
        low.set(id, Math.min(low.get(id)!, low.get(e.target)!));
      } else if (active.has(e.target))
        low.set(id, Math.min(low.get(id)!, indices.get(e.target)!));
    }
    if (low.get(id) === indices.get(id)) {
      const group: string[] = [];
      let item: string;
      do {
        item = stack.pop()!;
        active.delete(item);
        group.push(item);
      } while (item !== id);
      components.push(group.sort());
    }
  }
  graph.nodes.forEach((n) => {
    if (!indices.has(n.id)) visit(n.id);
  });
  const owner = new Map(
    components.flatMap((c, i) => c.map((id) => [id, i] as const)),
  );
  const levels = new Map<number, number>();
  function level(i: number): number {
    if (levels.has(i)) return levels.get(i)!;
    const previous = graph.edges
      .filter((e) => owner.get(e.target) === i && owner.get(e.source) !== i)
      .map((e) => owner.get(e.source)!);
    const value = previous.length ? 1 + Math.max(...previous.map(level)) : 0;
    levels.set(i, value);
    return value;
  }
  return new Map(graph.nodes.map((n) => [n.id, level(owner.get(n.id)!)]));
}

export function orphanNodes(original: SystemGraph, graph: SystemGraph) {
  return graph.nodes.filter(
    (n) =>
      original.edges.some((e) => e.target === n.id) &&
      !graph.edges.some((e) => e.target === n.id),
  );
}

export function removeScenario(
  original: SystemGraph,
  current: SystemGraph,
  selected: string[],
  cascade: boolean,
) {
  const removed = new Set(
    selected.filter((id) => current.nodes.some((n) => n.id === id)),
  );
  const subset = () => ({
    nodes: current.nodes.filter((n) => !removed.has(n.id)),
    edges: current.edges.filter(
      (e) => !removed.has(e.source) && !removed.has(e.target),
    ),
  });
  if (cascade) {
    let changed = true;
    while (changed) {
      changed = false;
      orphanNodes(original, subset()).forEach((n) => {
        // Only newly orphaned DELETE-policy copies cascade. Retained and redacted stores survive.
        if (
          n.action === "DELETE" &&
          !orphanNodes(original, current).some((x) => x.id === n.id) &&
          !removed.has(n.id)
        ) {
          removed.add(n.id);
          changed = true;
        }
      });
    }
  }
  const levels = graphLayers(current);
  const order = [...removed].sort(
    (a, b) => levels.get(b)! - levels.get(a)! || a.localeCompare(b),
  );
  const cyclic = order.filter((id) =>
    walk(current, id).some(
      (other) => removed.has(other) && walk(current, other).includes(id),
    ),
  );
  return {
    graph: subset(),
    order,
    retained: current.nodes.filter(
      (n) => removed.has(n.id) && n.action === "RETAIN",
    ),
    cyclic,
  };
}

export function wilson(bad: number, n: number): [number, number] | null {
  if (!n) return null;
  const z = 1.96,
    p = bad / n,
    d = 1 + (z * z) / n,
    c = (p + (z * z) / (2 * n)) / d;
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

export function pythonSnippet(graph: SystemGraph) {
  // Serialize only literal values. User text can never become a Python expression.
  function literal(value: unknown): string {
    if (value == null) return "None";
    if (typeof value === "boolean") return value ? "True" : "False";
    if (typeof value === "string" || typeof value === "number")
      return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(literal).join(", ")}]`;
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${literal(k)}: ${literal(v)}`)
      .join(", ")}}`;
  }
  const lines = [
    "# AFTERTRACE scenario export. Does not delete any external data.",
    "import networkx as nx",
    "",
    "G = nx.DiGraph()",
  ];
  for (const { id, ...attributes } of graph.nodes)
    lines.push(`G.add_node(${literal(id)}, **${literal(attributes)})`);
  lines.push("");
  for (const { source, target, ...attributes } of graph.edges)
    lines.push(
      `G.add_edge(${literal(source)}, ${literal(target)}, **${literal(attributes)})`,
    );
  lines.push(
    "",
    'print(G.number_of_nodes(), "systems", G.number_of_edges(), "links")',
    'print("Unlinked:", list(nx.isolates(G)))',
    "",
  );
  return lines.join("\n");
}

/** The active case is a read model, never filled with snapshot-wide statistics. */
export function fromCase(data: AuditCase): ConsoleData {
  const emptyForecast: Forecast = { slope: 0, p: null, fc: [], fit: [] };
  const rules = data.context.policy_rules;
  const nodes: SystemNode[] = [
    ...new Set(data.context.resource_states.map((r) => r.system_id)),
  ].map((id) => {
    const states = data.context.resource_states.filter(
      (r) => r.system_id === id,
    );
    const policy = rules.filter((r) =>
      states.some((s) => s.category === r.category),
    );
    const actions = [...new Set(policy.map((p) => p.required_action))];
    if (!actions.length)
      actions.push(
        ...new Set(
          data.answer.steps
            .filter((s) => s.phase === "REMEDIATION" && s.system_id === id)
            .map((s) => s.operation),
        ),
      );
    return {
      id,
      label: human(id),
      tier: "store",
      category: [...new Set(states.map((s) => s.category))].join(", "),
      rules: policy.map((p) => p.rule_id).join(", "),
      action:
        actions.length === 1 ? actions[0] : actions.length ? "MIXED" : "NONE",
      events: null,
      failures: 0,
      fail_rate: null,
      next_bad: null,
      resources: states.length,
      snap_resources: null,
      snap_identifiers: null,
      blast_radius: 0,
      betweenness: 0,
      evidence_ids: [
        ...new Set(states.flatMap((s) => s.supporting_evidence_ids)),
      ],
    };
  });
  function system(endpoint: string) {
    const parts = endpoint.split(":");
    return parts.length > 1 ? parts[1] : endpoint;
  }
  const edges = [
    ...(data.context.active_flows ?? []).map((e) => ({ ...e, restore: false })),
    ...(data.context.restore_risks ?? []).map((e) => ({ ...e, restore: true })),
  ].map((e) => ({
    source: system(e.source),
    target: system(e.target),
    kind: "engine risk",
    resource_id: e.source.split(":").at(-1),
    op: e.relationship,
    events: 0,
    fail_rate: null,
    active: e.active,
    restore: e.restore,
    evidence_ids: e.evidence_ids,
  }));
  for (const id of new Set(edges.flatMap((e) => [e.source, e.target])))
    if (!nodes.some((n) => n.id === id))
      nodes.push({
        id,
        label: human(id),
        tier: "flow",
        category: "Unresolved endpoint",
        rules: "",
        action: "NONE",
        events: null,
        failures: 0,
        fail_rate: null,
        next_bad: null,
        resources: 0,
        snap_resources: null,
        snap_identifiers: null,
        blast_radius: 0,
        betweenness: 0,
      });
  const register = data.answer.steps
    .filter((s) => s.phase === "FINDING")
    .map((s) => ({
      id: `F${s.step_no}`,
      cat: human(s.operation),
      title: human(s.operation),
      n: 1,
      unit: s.resource_id,
      sev: "Review",
      rule: rules
        .filter((r) =>
          data.context.resource_states.some(
            (x) => x.resource_id === s.resource_id && x.category === r.category,
          ),
        )
        .map((r) => r.rule_id)
        .join(", "),
      why: `Engine finding at ${data.request.audit_at}.`,
      conflict: `${s.system_id} / ${s.resource_id}: ${s.state}.`,
      action:
        data.answer.steps
          .filter(
            (x) => x.phase === "REMEDIATION" && x.resource_id === s.resource_id,
          )
          .map((x) => x.operation)
          .join(" → ") || "Review the audit folio",
      ev: s.evidence_id ? [s.evidence_id] : [],
    }));
  const months: string[] = [];
  return {
    meta: {
      as_of: data.request.audit_at,
      activity_from: data.request.requested_at,
      activity_to: data.request.audit_at,
      events: 0,
      requests: 1,
      evidence_files: data.sources.length,
      sql_snapshots: data.sources.filter((s) => s.kind === "sql").length,
      rules: rules.length,
      months,
      month_labels: {},
      oct_partial_events: 0,
      networkx: "Python engine",
    },
    kpis: {
      events: 0,
      non_success: 0,
      non_success_rate: null,
      destructive_n: 0,
      destructive_bad: 0,
      destructive_rate: null,
      reborn: null,
      flows_checked: 0,
      flows_open_act: edges.filter((e) => e.active && !e.restore).length,
      restore_checked: 0,
      restore_open_act: edges.filter((e) => e.restore).length,
      ghost_rows: null,
      replica_tables: 0,
    },
    rate_series: [],
    ctrl_series: [],
    rate_fc: emptyForecast,
    ctrl_fc: emptyForecast,
    count_fc: emptyForecast,
    patterns: [],
    heatmap: { systems: [], rows: [] },
    systems_rank: [],
    predictor: { table: [], class_rate: {} },
    drift: [],
    register,
    aging: { bins: [], series: [] },
    retention: {
      audit_by_year: [],
      legal_by_year: [],
      legal_register: [],
      legal_file: "",
      security_extract: "",
      security_extract_note:
        "Retention dates are not exposed in this case read model.",
    },
    identifier_fields: [],
    graph: { nodes, edges },
    rules: rules.map((r) => ({
      id: r.rule_id,
      category: r.category,
      condition: r.condition ?? "Unspecified",
      action: r.required_action,
    })),
  };
}
