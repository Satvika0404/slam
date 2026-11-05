import { useMemo, useRef, useState } from "react";
import {
  Check,
  Copy,
  Download,
  Focus,
  Minus,
  Plus,
  RotateCcw,
  Undo2,
  X,
  GitBranch,
  ShieldAlert,
} from "lucide-react";
import type {
  ConsoleData,
  InspectEvidence,
  SystemGraph as Graph,
} from "./types";
import {
  edgeKey,
  graphLayers,
  human,
  number,
  orphanNodes,
  percent,
  pythonSnippet,
  removeScenario,
  walk,
} from "./model";
import {
  ConsoleEmpty,
  ConsolePanel,
  ConsoleStats,
  EvidenceRefs,
} from "./Shared";

export default function SystemGraph({
  data,
  onInspect,
  readOnly = false,
}: {
  data: ConsoleData;
  onInspect: InspectEvidence;
  readOnly?: boolean;
}) {
  const original = data.graph;
  const [graph, setGraph] = useState<Graph>(original),
    [selected, setSelected] = useState<string[]>([]),
    [inspect, setInspect] = useState(
      original.nodes.find((n) => n.id === "account_service")?.id ??
        original.nodes[0]?.id ??
        "",
    );
  const [history, setHistory] = useState<{ graph: Graph; logs: string[] }[]>(
      [],
    ),
    [logs, setLogs] = useState<string[]>([
      `${original.nodes.length} systems and ${original.edges.length} links loaded into the local scenario.`,
    ]);
  const [query, setQuery] = useState(""),
    [action, setAction] = useState("All"),
    [cascade, setCascade] = useState(false),
    [pending, setPending] = useState(false),
    [observed, setObserved] = useState(false),
    [focus, setFocus] = useState(false),
    [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 }),
    [copied, setCopied] = useState(false),
    [copyError, setCopyError] = useState("");
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
      null,
    ),
    canvas = useRef<SVGSVGElement>(null),
    confirmButton = useRef<HTMLButtonElement>(null);
  const orphans = orphanNodes(original, graph),
    removed = original.nodes.filter(
      (n) => !graph.nodes.some((x) => x.id === n.id),
    );
  const active = graph.edges.filter((e) => e.active && !e.restore),
    restores = graph.edges.filter((e) => e.restore);
  const retained = removed.filter((n) => n.action === "RETAIN"),
    preview = removeScenario(original, graph, selected, cascade);
  const layers = useMemo(() => graphLayers(graph), [graph]);
  const positions = useMemo(() => {
    const groups = new Map<number, string[]>();
    graph.nodes.forEach((n) => {
      const level = layers.get(n.id) ?? 0;
      groups.set(level, [...(groups.get(level) ?? []), n.id]);
    });
    const result = new Map<string, { x: number; y: number }>();
    groups.forEach((ids, level) =>
      ids
        .sort()
        .forEach((id, i) =>
          result.set(id, { x: 38 + level * 260, y: 70 + i * 86 }),
        ),
    );
    return {
      nodes: result,
      w: Math.max(1000, 80 + (Math.max(0, ...groups.keys()) + 1) * 260),
      h: Math.max(
        440,
        100 + Math.max(0, ...[...groups.values()].map((a) => a.length)) * 86,
      ),
    };
  }, [graph, layers]);
  const inspected = graph.nodes.find((n) => n.id === inspect),
    neighbors = inspect
      ? new Set([
          inspect,
          ...walk(graph, inspect),
          ...walk(graph, inspect, true),
        ])
      : new Set<string>();
  const table = original.nodes.filter(
    (n) =>
      (action === "All" || n.action === action) &&
      `${n.label} ${n.id} ${n.category}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const snippet = useMemo(() => pythonSnippet(graph), [graph]);
  function mutate(next: Graph, message: string[]) {
    if (readOnly) return;
    setHistory((h) => [...h, { graph, logs }]);
    setGraph(next);
    setLogs((l) => [...l, ...message]);
    setSelected([]);
    setPending(false);
    setCopied(false);
    if (!next.nodes.some((n) => n.id === inspect)) setInspect("");
  }
  function undo() {
    const last = history.at(-1);
    if (!last) return;
    setGraph(last.graph);
    setLogs(last.logs);
    setHistory((h) => h.slice(0, -1));
    setSelected([]);
    setPending(false);
    setCopied(false);
  }
  function reset() {
    setGraph(original);
    setLogs([
      `${original.nodes.length} systems and ${original.edges.length} links loaded into the local scenario.`,
    ]);
    setHistory([]);
    setSelected([]);
    setPending(false);
    setPan({ x: 0, y: 0 });
    setZoom(1);
    setCopied(false);
  }
  function toggle(id: string) {
    setSelected((v) =>
      v.includes(id) ? v.filter((x) => x !== id) : [...v, id],
    );
    setPending(false);
  }
  function cut(source: string, target: string) {
    mutate(
      {
        ...graph,
        edges: graph.edges.filter(
          (e) => edgeKey(e) !== edgeKey({ source, target }),
        ),
      },
      [
        `G.remove_edge(${JSON.stringify(source)}, ${JSON.stringify(target)})  # scenario only`,
      ],
    );
  }
  function remove() {
    mutate(
      preview.graph,
      preview.order.map(
        (id) =>
          `G.remove_node(${JSON.stringify(id)})  # scenario only${original.nodes.find((n) => n.id === id)?.action === "RETAIN" ? "; RETENTION CONFLICT" : ""}`,
      ),
    );
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setCopyError("");
    } catch {
      setCopyError(
        "Clipboard unavailable. Use Download Python or select the code below.",
      );
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([snippet], { type: "text/x-python" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "aftertrace-graph-scenario.py";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const visibleEdges = graph.edges.filter(
    (e) => !observed || e.kind === "observed" || e.kind === "engine risk",
  );
  const queryList = (reverse: boolean) =>
    inspected
      ? graph.edges
          .filter((e) => (reverse ? e.target : e.source) === inspected.id)
          .map((e) => (reverse ? e.source : e.target))
      : [];
  return (
    <div className={`intel-tab-body ${readOnly ? "live-graph-readonly" : ""}`}>
      <div className="intel-sandbox-label">
        <GitBranch size={17} />
        <strong>
          {readOnly ? "BACKEND DEPENDENCY SNAPSHOT" : "REVERSIBLE SCENARIO"}
        </strong>
        <span>
          {readOnly
            ? "Topology emitted by the backend. Explore nodes and evidence; source editing is disabled."
            : "Changes affect this browser session only. Removing a system from the map does not delete its records or prove a compliant state."}
        </span>
      </div>
      <ConsoleStats
        items={[
          {
            label: "Systems in scenario",
            value: number(graph.nodes.length),
            note: `${original.nodes.length} in the source graph`,
          },
          {
            label: "Directed links",
            value: number(graph.edges.length),
            note: `${graph.edges.filter((e) => e.kind === "observed").length} labelled observed`,
          },
          {
            label: "Open flow / restore links",
            value: `${active.length} / ${restores.length}`,
            note: "Source flags; not a verified current-state count",
            tone: active.length || restores.length ? "coral-text" : "",
          },
          {
            label: "Orphans / retention conflicts",
            value: `${orphans.length} / ${retained.length}`,
            note: "Derived from changes in this scenario",
            tone: orphans.length || retained.length ? "coral-text" : "",
          },
        ]}
      />
      <ConsolePanel
        number="01"
        title="The system atlas"
        note="Directed connections show how data can travel. Select a system to inspect its actual neighborhood."
        tools={
          <div className="intel-graph-options">
            <label>
              <input
                type="checkbox"
                checked={observed}
                onChange={(e) => setObserved(e.target.checked)}
              />
              Hide inferred links
            </label>
            <label>
              <input
                type="checkbox"
                checked={focus}
                onChange={(e) => setFocus(e.target.checked)}
              />
              Focus neighborhood
            </label>
          </div>
        }
      >
        <div className="intel-map-scroll">
          <svg
            ref={canvas}
            viewBox={`0 0 ${positions.w} ${positions.h}`}
            className="intel-system-map"
            role="group"
            aria-label="Interactive system dependency map"
            style={{ height: Math.min(760, positions.h) }}
            onPointerDown={(e) => {
              if ((e.target as Element).closest('[role="button"]')) return;
              drag.current = {
                x: e.clientX,
                y: e.clientY,
                px: pan.x,
                py: pan.y,
              };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!drag.current || !canvas.current) return;
              const scale =
                positions.w / canvas.current.getBoundingClientRect().width;
              setPan({
                x: drag.current.px + (e.clientX - drag.current.x) * scale,
                y: drag.current.py + (e.clientY - drag.current.y) * scale,
              });
            }}
            onPointerUp={() => {
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          >
            <defs>
              <pattern
                id="intel-map-grid"
                width="26"
                height="26"
                patternUnits="userSpaceOnUse"
              >
                <path d="M26 0H0V26" fill="none" stroke="#ffffff07" />
              </pattern>
              <marker
                id="intel-map-arrow"
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M0 0L8 4L0 8" fill="none" stroke="context-stroke" />
              </marker>
              <linearGradient id="intel-node-glass" x2=".6" y2="1">
                <stop stopColor="#1c2531" stopOpacity=".96" />
                <stop offset="1" stopColor="#10151f" stopOpacity=".95" />
              </linearGradient>
            </defs>
            <rect width="100%" height="100%" fill="url(#intel-map-grid)" />
            <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
              {[...new Set(layers.values())].map((l) => (
                <text
                  key={l}
                  x={38 + l * 260}
                  y="30"
                  className="intel-map-caption"
                >
                  HOP {l} / {l === 0 ? "ORIGIN OR UNLINKED" : "DOWNSTREAM"}
                </text>
              ))}
              {visibleEdges.map((e, i) => {
                const s = positions.nodes.get(e.source),
                  t = positions.nodes.get(e.target);
                if (!s || !t) return null;
                const muted =
                  focus &&
                  !(neighbors.has(e.source) && neighbors.has(e.target));
                const forward = t.x > s.x;
                const sx = s.x + (forward ? 205 : 0),
                  tx = t.x + (forward ? 0 : 205);
                const cy = s.y + 31;
                const path =
                  e.source === e.target
                    ? `M${s.x + 180} ${s.y} C${s.x + 230} ${s.y - 50},${s.x + 80} ${s.y - 55},${s.x + 90} ${s.y}`
                    : `M${sx} ${cy} C${sx + (forward ? 70 : -80)} ${cy},${tx - (forward ? 70 : -80)} ${t.y + 31},${tx} ${t.y + 31}`;
                return (
                  <path
                    key={`${edgeKey(e)}:${i}`}
                    d={path}
                    className={`intel-map-link ${e.restore ? "is-restore" : e.active ? "is-active" : ""} ${e.kind === "inferred" ? "is-inferred" : ""}`}
                    opacity={muted ? 0.1 : 1}
                    markerEnd="url(#intel-map-arrow)"
                  >
                    <title>
                      {e.source} → {e.target} · {e.op || e.why || "inferred"} ·{" "}
                      {e.kind}
                      {e.active ? " · flagged active" : ""}
                    </title>
                  </path>
                );
              })}
              {graph.nodes.map((n) => {
                const p = positions.nodes.get(n.id)!;
                const chosen = n.id === inspect;
                return (
                  <g
                    key={n.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Inspect system ${n.label}`}
                    aria-pressed={chosen}
                    className={`intel-map-node action-${n.action.toLowerCase()} ${chosen ? "is-inspected" : ""} ${selected.includes(n.id) ? "is-selected" : ""}`}
                    transform={`translate(${p.x} ${p.y})`}
                    opacity={focus && !neighbors.has(n.id) ? 0.2 : 1}
                    onClick={() => setInspect(n.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setInspect(n.id);
                      }
                    }}
                  >
                    <rect
                      width="205"
                      height="62"
                      rx="7"
                      fill="url(#intel-node-glass)"
                    />
                    <rect
                      className="intel-node-stripe"
                      x="0"
                      y="13"
                      width="2"
                      height="36"
                    />
                    <text x="15" y="25" className="intel-node-title">
                      {n.label.length > 27
                        ? n.label.slice(0, 25) + "…"
                        : n.label}
                    </text>
                    <text x="15" y="46" className="intel-node-sub">
                      {n.action} · {n.resources} resources
                    </text>
                    <circle cx="187" cy="17" r="3" className="intel-node-led" />
                    <title>
                      {n.label} · {n.category} ·{" "}
                      {n.rules || "No policy association"}
                      {orphans.some((o) => o.id === n.id)
                        ? " · orphaned in this scenario"
                        : ""}
                    </title>
                  </g>
                );
              })}
            </g>
          </svg>
          {!graph.nodes.length && (
            <ConsoleEmpty>
              No systems remain in this scenario. Undo or reset to recover the
              graph.
            </ConsoleEmpty>
          )}
        </div>
        <div className="intel-map-bottom">
          <div className="intel-chart-legend">
            <span>
              <i className="coral" />
              Flagged active
            </span>
            <span>
              <i className="violet" />
              Restore path
            </span>
            <span>Dashed: inferred · drag canvas to pan</span>
          </div>
          <div className="intel-map-controls">
            <button
              aria-label="Zoom system map out"
              onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))}
            >
              <Minus size={15} />
            </button>
            <output>{Math.round(zoom * 100)}%</output>
            <button
              aria-label="Zoom system map in"
              onClick={() => setZoom((z) => Math.min(2, z + 0.15))}
            >
              <Plus size={15} />
            </button>
            <button
              aria-label="Reset system map view"
              onClick={() => {
                setZoom(1);
                setPan({ x: 0, y: 0 });
              }}
            >
              <Focus size={15} />
            </button>
          </div>
        </div>
        {inspected ? (
          <div className="intel-system-inspector">
            <div className="intel-system-heading">
              <span className="intel-label">SYSTEM QUERY / {inspected.id}</span>
              <h3>{inspected.label}</h3>
              <span
                className={`intel-policy-action action-${inspected.action.toLowerCase()}`}
              >
                {inspected.action}
              </span>
            </div>
            <div className="intel-system-grid">
              <div>
                <span className="intel-label">DIRECTED NEIGHBORHOOD</span>
                <dl className="intel-graph-queries">
                  <dt>predecessors</dt>
                  <dd>{queryList(true).join(", ") || "[]"}</dd>
                  <dt>successors</dt>
                  <dd>{queryList(false).join(", ") || "[]"}</dd>
                  <dt>ancestors</dt>
                  <dd>{walk(graph, inspect, true).join(", ") || "[]"}</dd>
                  <dt>descendants</dt>
                  <dd>{walk(graph, inspect).join(", ") || "[]"}</dd>
                  <dt>downstream reach</dt>
                  <dd>{walk(graph, inspect).length} systems</dd>
                </dl>
              </div>
              <div>
                <span className="intel-label">POLICY / SOURCE FIGURES</span>
                <p>{inspected.category}</p>
                <p className="intel-muted">
                  {inspected.rules || "No rule linked"}
                </p>
                <dl className="intel-dl">
                  <dt>Reported outcomes</dt>
                  <dd>{number(inspected.events)}</dd>
                  <dt>Reported failure rate</dt>
                  <dd>{percent(inspected.fail_rate)}</dd>
                  <dt>Snapshot records</dt>
                  <dd>{number(inspected.snap_resources)}</dd>
                </dl>
                <EvidenceRefs
                  ids={inspected.evidence_ids ?? []}
                  onInspect={onInspect}
                  context={inspected.label}
                />
              </div>
              <div>
                <span className="intel-label">SIMULATE A LINK CHANGE</span>
                {graph.edges
                  .filter((e) => e.source === inspect || e.target === inspect)
                  .map((e, i) => (
                    <div className="intel-link-control" key={i}>
                      <span>
                        {e.source === inspect ? "→" : "←"}{" "}
                        {e.source === inspect ? e.target : e.source}
                        <small>
                          {e.kind} · {e.op || e.why || "No operation supplied"}
                        </small>
                      </span>
                      <button onClick={() => cut(e.source, e.target)}>
                        {e.restore
                          ? "Simulate block"
                          : e.active
                            ? "Simulate disable"
                            : "Detach link"}
                      </button>
                    </div>
                  ))}
                {!graph.edges.some(
                  (e) => e.source === inspect || e.target === inspect,
                ) && (
                  <p className="intel-muted">
                    No links are present for this system.
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : (
          <ConsoleEmpty>
            Select a system on the map or in the register to inspect it.
          </ConsoleEmpty>
        )}
      </ConsolePanel>
      <ConsolePanel
        number="02"
        title="Edit the scenario"
        note="Preview downstream impacts before removing nodes. Changes never execute remediation."
        tools={
          <div className="intel-fields intel-table-filters">
            <label>
              Search systems
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Name, category or ID"
              />
            </label>
            <label>
              Policy action
              <select
                value={action}
                onChange={(e) => setAction(e.target.value)}
              >
                {["All", ...new Set(original.nodes.map((n) => n.action))].map(
                  (a) => (
                    <option key={a}>{a}</option>
                  ),
                )}
              </select>
            </label>
          </div>
        }
      >
        <div className="intel-scenario-toolbar">
          <div>
            <button
              onClick={() => {
                setSelected(
                  graph.nodes
                    .filter((n) => n.action === "DELETE")
                    .map((n) => n.id),
                );
                setPending(false);
              }}
            >
              Select delete-policy stores
            </button>
            <button
              disabled={!selected.length}
              onClick={() => {
                setSelected([]);
                setPending(false);
              }}
            >
              Clear selection
            </button>
          </div>
          <label>
            <input
              type="checkbox"
              checked={cascade}
              onChange={(e) => {
                setCascade(e.target.checked);
                setPending(false);
              }}
            />
            Cascade newly orphaned DELETE copies
          </label>
          <div>
            <button
              aria-label="Undo scenario change"
              disabled={!history.length}
              onClick={undo}
            >
              <Undo2 size={14} />
              Undo
            </button>
            <button onClick={reset}>
              <RotateCcw size={14} />
              Reset
            </button>
            <button
              className="intel-danger-button"
              disabled={!selected.length}
              onClick={() => {
                setPending(true);
                setTimeout(() => confirmButton.current?.focus(), 0);
              }}
            >
              Preview removal ({selected.length})
            </button>
          </div>
        </div>
        {pending && (
          <div
            className="intel-scenario-confirm"
            role="region"
            aria-label="Scenario removal preview"
          >
            <span className="intel-label">PREVIEW / NO EXTERNAL ACTION</span>
            <h3>Remove {preview.order.length} systems from this scenario?</h3>
            <p>
              Downstream-first order:{" "}
              <strong>{preview.order.join(" → ")}</strong>
            </p>
            {preview.cyclic.length > 0 && (
              <p className="coral-text">
                Cycle detected among {preview.cyclic.join(", ")}. A valid real
                remediation order would require breaking the cycle first.
              </p>
            )}
            {preview.retained.length > 0 && (
              <p className="coral-text">
                <ShieldAlert size={15} /> Retention conflict:{" "}
                {preview.retained.map((n) => n.label).join(", ")} must remain
                under the supplied RETAIN association.
              </p>
            )}
            <p>
              {orphanNodes(original, preview.graph).length} systems would have
              lost all their original incoming links. Removing map links does
              not prove flows have stopped.
            </p>
            <div>
              <button
                ref={confirmButton}
                className="intel-danger-button"
                onClick={remove}
              >
                Apply to scenario
              </button>
              <button onClick={() => setPending(false)}>
                <X size={14} />
                Cancel
              </button>
            </div>
          </div>
        )}
        <div className="intel-table-scroll">
          <table className="intel-table intel-system-table">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Select</span>
                </th>
                <th>System</th>
                <th>Policy / category</th>
                <th>Source resources</th>
                <th>In / out</th>
                <th>Scenario state</th>
              </tr>
            </thead>
            <tbody>
              {table.map((n) => {
                const gone = removed.some((r) => r.id === n.id);
                return (
                  <tr
                    key={n.id}
                    className={
                      gone
                        ? "is-removed"
                        : selected.includes(n.id)
                          ? "is-selected"
                          : ""
                    }
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${n.label}`}
                        checked={selected.includes(n.id)}
                        disabled={gone}
                        onChange={() => toggle(n.id)}
                      />
                    </td>
                    <td>
                      <button
                        className="intel-system-name"
                        disabled={gone}
                        onClick={() => {
                          setInspect(n.id);
                          canvas.current?.scrollIntoView({
                            block: "nearest",
                            behavior: window.matchMedia(
                              "(prefers-reduced-motion: reduce)",
                            ).matches
                              ? "instant"
                              : "smooth",
                          });
                        }}
                      >
                        {n.label}
                        <small>{n.id}</small>
                      </button>
                    </td>
                    <td>
                      <span
                        className={`intel-policy-action action-${n.action.toLowerCase()}`}
                      >
                        {n.action}
                      </span>
                      <small>{n.category}</small>
                    </td>
                    <td>{number(n.resources)}</td>
                    <td>
                      {graph.edges.filter((e) => e.target === n.id).length} /{" "}
                      {graph.edges.filter((e) => e.source === n.id).length}
                    </td>
                    <td>
                      {gone
                        ? "Removed in scenario"
                        : orphans.some((o) => o.id === n.id)
                          ? "Orphaned"
                          : graph.edges.some(
                                (e) => e.source === n.id || e.target === n.id,
                              )
                            ? "Linked"
                            : "Unlinked"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!table.length && (
            <ConsoleEmpty>No systems match these filters.</ConsoleEmpty>
          )}
        </div>
      </ConsolePanel>
      <div className="intel-two-col">
        <ConsolePanel
          number="03"
          title="Scenario consequences"
          note="Derived from the edited graph, independently of audit certification."
        >
          <div className="intel-consequence">
            <h3>
              Recreation links still shown{" "}
              <b>{active.length + restores.length}</b>
            </h3>
            {[...active, ...restores].map((e, i) => (
              <p key={i}>
                {human(e.source)} → {human(e.target)}
                <small>
                  {e.restore ? "Restore flag" : "Active-flow flag"} · {e.kind}
                </small>
              </p>
            ))}
            {!active.length && !restores.length && (
              <p>
                No flagged links remain in this scenario. External state is
                unverified.
              </p>
            )}
            <h3>
              Copies without their source <b>{orphans.length}</b>
            </h3>
            {orphans.map((n) => (
              <p key={n.id}>
                {n.label}
                <small>
                  {n.action} · {n.category}
                </small>
              </p>
            ))}
            {!orphans.length && (
              <p>No newly disconnected incoming relationships.</p>
            )}
            <h3>
              Retention conflicts <b>{retained.length}</b>
            </h3>
            {retained.map((n) => (
              <p className="coral-text" key={n.id}>
                {n.label}
                <small>{n.rules}</small>
              </p>
            ))}
            {!retained.length && <p>No RETAIN-policy systems were removed.</p>}
          </div>
        </ConsolePanel>
        <ConsolePanel
          number="04"
          title="Scenario change log"
          note="A local history of equivalent graph operations. Undo restores the previous graph and log."
        >
          <ol className="intel-graph-log" aria-live="polite">
            {logs.map((l, i) => (
              <li key={`${i}:${l}`}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                <code>{l}</code>
              </li>
            ))}
          </ol>
        </ConsolePanel>
      </div>
      <ConsolePanel
        number="05"
        title="Take the graph with you"
        note="Exports rebuild the current scenario in Python with NetworkX, including node and edge attributes."
        tools={
          <div className="intel-export-tools">
            <button onClick={copy}>
              {copied ? <Check size={14} /> : <Copy size={14} />}{" "}
              {copied ? "Copied" : "Copy Python"}
            </button>
            <button onClick={download}>
              <Download size={14} />
              Download Python
            </button>
          </div>
        }
      >
        <details className="intel-code">
          <summary>Inspect generated NetworkX code</summary>
          <pre tabIndex={0}>{snippet}</pre>
        </details>
        {copyError && (
          <p role="status" className="intel-method">
            {copyError}
          </p>
        )}
      </ConsolePanel>
    </div>
  );
}
