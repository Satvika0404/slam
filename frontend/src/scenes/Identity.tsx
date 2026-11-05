import { useEffect, useMemo, useRef, useState } from "react";
import {
  BadgeCheck,
  CircleX,
  Expand,
  Fingerprint,
  Focus,
  Hash,
  Mail,
  Minus,
  Phone,
  Plus,
  Search,
  UserRound,
  Waypoints,
} from "lucide-react";
import { SectionLabel } from "../components";
import { label } from "../api";
import type { SceneProps, IdentityNode } from "../types";
import IdentityInspector from "../identity/Inspector";
import {
  edgeStatus,
  fullTime,
  isEnded,
  layoutIdentity,
  neighborhood,
  shortestPath,
  statusName,
  validateEdge,
} from "../identity/model";
import "@fontsource/manrope/latin-500.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "../identity/identity.css";

// The original renderer is retained: HTML node buttons over the same SVG path layer,
// original anchor positions, pointer drag/pan, IDs, evidence callbacks and time control.
export default function Identity(props: SceneProps) {
  const { data, loading } = props;
  const [filter, setFilter] = useState("all"),
    [view, setView] = useState("historical"),
    [type, setType] = useState("all"),
    [system, setSystem] = useState("all");
  const [selected, setSelected] = useState(data.context.subject_id ?? ""),
    [edgeId, setEdgeId] = useState<string | null>(null),
    [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 }),
    [positions, setPositions] = useState<Record<string, number[]>>({});
  const [collapsed, setCollapsed] = useState(false),
    [hops, setHops] = useState(1),
    [limit, setLimit] = useState(40),
    [pathFocus, setPathFocus] = useState(false),
    [resourceExpanded, setResourceExpanded] = useState(false),
    [query, setQuery] = useState(""),
    [message, setMessage] = useState("");
  const viewport = useRef<HTMLDivElement>(null),
    suppressClick = useRef(false),
    drag = useRef<{
      id: string;
      x: number;
      y: number;
      start: number[];
      moved: boolean;
    } | null>(null),
    panDrag = useRef<{
      x: number;
      y: number;
      start: { x: number; y: number };
      moved: boolean;
    } | null>(null);
  const oldStatuses = useRef(new Map<string, string>()),
    [justEnded, setJustEnded] = useState<string[]>([]);
  const nodeIds = useMemo(
    () => new Set(data.identity_nodes.map((n) => n.id)),
    [data.identity_nodes],
  );
  const issues = data.identity_edges
    .map((e) => ({ edge: e, problem: validateEdge(e, nodeIds) }))
    .filter((x) => x.problem);
  const validEdges = data.identity_edges.filter(
    (e) => !validateEdge(e, nodeIds),
  );
  const statuses = new Map(
    validEdges.map((e) => [e.id, edgeStatus(e, data.request.audit_at)]),
  );
  const eligibleEdges = validEdges.filter(
    (e) => statuses.get(e.id) !== "future",
  );
  const root =
    selected || data.context.subject_id || data.identity_nodes[0]?.id || "";
  const neighborhoodIds = neighborhood(eligibleEdges, [root], hops);
  const allNodes = [...data.identity_nodes].sort((a, b) =>
    a.kind === "subject"
      ? -1
      : b.kind === "subject"
        ? 1
        : a.kind === "resource" && b.kind !== "resource"
          ? 1
          : b.kind === "resource" && a.kind !== "resource"
            ? -1
            : a.id.localeCompare(b.id),
  );
  const layout = useMemo(() => layoutIdentity(allNodes), [data.identity_nodes]);
  const loc = (id: string) => positions[id] ?? layout[id] ?? [490, 248];
  const systems = [
    ...new Set(validEdges.flatMap((e) => e.system_ids ?? [])),
  ].sort();
  let edges = eligibleEdges.filter((e) => {
    const status = statuses.get(e.id)!;
    return (
      (view === "historical" || !isEnded(status) || justEnded.includes(e.id)) &&
      (filter === "all" ||
        (filter === "historical" ? isEnded(status) : status === filter)) &&
      (system === "all" || e.system_ids?.includes(system)) &&
      (type === "all" ||
        data.identity_nodes.some(
          (n) => (n.id === e.source || n.id === e.target) && n.kind === type,
        )) &&
      (!collapsed ||
        (neighborhoodIds.has(e.source) && neighborhoodIds.has(e.target)))
    );
  });
  const progressive = allNodes.length > 40;
  let visibleNodes = allNodes.filter(
    (n) =>
      (n.kind !== "resource" ||
        resourceExpanded ||
        type === "resource" ||
        n.id === selected) &&
      (type === "all" ||
        n.kind === type ||
        edges.some((e) => e.source === n.id || e.target === n.id)) &&
      (!collapsed || neighborhoodIds.has(n.id)) &&
      (system === "all" ||
        edges.some((e) => e.source === n.id || e.target === n.id)),
  );
  if (progressive) {
    const ordered = [
      ...visibleNodes.filter((n) => n.id === root),
      ...visibleNodes.filter((n) => n.id !== root && neighborhoodIds.has(n.id)),
      ...visibleNodes.filter(
        (n) => n.id !== root && !neighborhoodIds.has(n.id),
      ),
    ];
    visibleNodes = ordered.slice(0, limit);
  }
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  edges = edges.filter(
    (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
  );
  const active = edges.find((e) => e.id === edgeId);
  const path = pathFocus
    ? shortestPath(
        edges,
        data.context.subject_id ?? root,
        active?.target ?? selected,
      )
    : { nodes: new Set<string>(), edges: new Set<string>() };
  const endpoints = active
    ? new Set([active.source, active.target])
    : new Set(selected ? [selected] : []);
  const nearby = neighborhood(edges, [...endpoints], 1);
  const worldHeight = Math.max(
    520,
    ...Object.values(layout).map((p) => p[1] + 90),
  );
  function clear() {
    setSelected("");
    setEdgeId(null);
    setPathFocus(false);
    setCollapsed(false);
    setMessage("");
  }
  function chooseEdge(id: string) {
    const connection = validEdges.find((e) => e.id === id);
    if (connection) {
      if (
        allNodes.some(
          (n) =>
            n.kind === "resource" &&
            (n.id === connection.source || n.id === connection.target),
        )
      )
        setResourceExpanded(true);
      const bounds = viewport.current?.getBoundingClientRect();
      if (bounds) {
        const a = loc(connection.source),
          b = loc(connection.target),
          height = worldHeight > 520 ? worldHeight : bounds.height;
        const s = Math.min(
          1,
          (bounds.width - 60) /
            ((Math.abs(a[0] - b[0]) * bounds.width) / 1000 + 150),
          (bounds.height - 50) /
            ((Math.abs(a[1] - b[1]) * height) / worldHeight + 150),
        );
        setZoom(s);
        setPan({
          x:
            bounds.width / 2 -
            ((((a[0] + b[0]) / 2) * bounds.width) / 1000) * s,
          y:
            bounds.height / 2 -
            ((((a[1] + b[1]) / 2) * height) / worldHeight) * s,
        });
      }
    }
    setEdgeId((old) => (old === id ? null : id));
    setSelected("");
    setPathFocus(false);
  }
  function chooseNode(id: string) {
    if (allNodes.some((n) => n.id === id && n.kind === "resource"))
      setResourceExpanded(true);
    setSelected(id);
    setEdgeId(null);
    setPathFocus(false);
    setHops(1);
  }
  function reset() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setPositions({});
  }
  function fit() {
    const bounds = viewport.current?.getBoundingClientRect();
    if (!bounds || !visibleNodes.length) return;
    const points = visibleNodes.map((n) => loc(n.id));
    const minX = Math.min(...points.map((p) => p[0])) - 75,
      maxX = Math.max(...points.map((p) => p[0])) + 75,
      minY = Math.min(...points.map((p) => p[1])) - 65,
      maxY = Math.max(...points.map((p) => p[1])) + 80;
    const physicalHeight = worldHeight > 520 ? worldHeight : bounds.height;
    const scale = Math.min(
      1.45,
      (bounds.width - 50) / (((maxX - minX) * bounds.width) / 1000),
      (bounds.height - 50) / (((maxY - minY) * physicalHeight) / worldHeight),
    );
    setZoom(scale);
    setPan({
      x:
        bounds.width / 2 -
        ((((minX + maxX) / 2) * bounds.width) / 1000) * scale,
      y:
        bounds.height / 2 -
        ((((minY + maxY) / 2) * physicalHeight) / worldHeight) * scale,
    });
  }
  useEffect(() => {
    if (selected && !nodeIds.has(selected))
      setSelected(data.context.subject_id ?? "");
    if (edgeId && !data.identity_edges.some((e) => e.id === edgeId))
      setEdgeId(null);
  }, [data, selected, edgeId]);
  useEffect(() => {
    function escape(e: KeyboardEvent) {
      if (
        e.key === "Escape" &&
        !(e.target as Element)?.closest('[role="dialog"]')
      )
        clear();
    }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  useEffect(() => {
    const ended = data.identity_edges
      .filter(
        (e) =>
          isEnded(edgeStatus(e, data.request.audit_at)) &&
          oldStatuses.current.has(e.id) &&
          !isEnded(
            oldStatuses.current.get(e.id) as ReturnType<typeof edgeStatus>,
          ),
      )
      .map((e) => e.id);
    setJustEnded(ended);
    oldStatuses.current = new Map(
      data.identity_edges.map((e) => [
        e.id,
        edgeStatus(e, data.request.audit_at),
      ]),
    );
    const t = setTimeout(() => setJustEnded([]), 550);
    return () => clearTimeout(t);
  }, [data.identity_edges, data.request.audit_at]);
  function exactSearch() {
    const found = data.identity_nodes.find(
      (n) => n.id === query.trim() || n.label === query.trim(),
    );
    if (!found) {
      setMessage("No exact identifier match in this backend response.");
      return;
    }
    setType("all");
    setFilter("all");
    setSystem("all");
    setView("historical");
    setCollapsed(false);
    setLimit(Math.max(40, allNodes.findIndex((n) => n.id === found.id) + 1));
    chooseNode(found.id);
    setMessage(`Exact match: ${found.label}`);
  }
  function nodeIcon(node: IdentityNode) {
    return node.kind === "subject" ? (
      <Fingerprint size={31} />
    ) : node.kind === "email" ? (
      <Mail size={19} />
    ) : node.kind === "phone" ? (
      <Phone size={19} />
    ) : node.kind === "hash" ? (
      <Hash size={19} />
    ) : node.kind === "name" ? (
      <UserRound size={19} />
    ) : (
      <Waypoints size={19} />
    );
  }
  return (
    <section className="identity-scene">
      <div className="scene-heading">
        <div>
          <SectionLabel number="03">IDENTITY CONSTELLATION</SectionLabel>
          <h1>
            One person.
            <br />
            <em>Many versions.</em>
          </h1>
        </div>
        <p className="heading-aside">
          An association is not an entity.
          <br />A missing link is not a deletion.
          <span>EVERY CONNECTION HAS A SOURCE.</span>
        </p>
      </div>
      <div className="identity-query-bar">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            exactSearch();
          }}
        >
          <Search size={15} />
          <input
            aria-label="Exact identifier search"
            placeholder="Find an exact identifier…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">Find exact</button>
        </form>
        <label>
          Node type
          <select
            aria-label="Filter identity node type"
            value={type}
            onChange={(e) => setType(e.target.value)}
          >
            <option value="all">All types</option>
            {[...new Set(allNodes.map((n) => n.kind))].map((k) => (
              <option key={k} value={k}>
                {label(k)}
              </option>
            ))}
          </select>
        </label>
        <label>
          System
          <select
            aria-label="Filter identity system"
            disabled={!systems.length}
            value={system}
            onChange={(e) => setSystem(e.target.value)}
          >
            <option value="all">
              {systems.length ? "All supplied systems" : "No system metadata"}
            </option>
            {systems.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="identity-feedback" role="status">
        {message ||
          `${edges.length} visible relationships · ${visibleNodes.length} of ${allNodes.length} identifiers · audit ${fullTime(data.request.audit_at)}`}
      </div>
      {!!issues.length && (
        <details className="identity-invalid">
          <summary>
            {issues.length} invalid relationships excluded from the drawing
          </summary>
          {issues.map((x, i) => (
            <p key={i}>
              {x.edge.id || "Missing ID"}: {x.problem}
            </p>
          ))}
        </details>
      )}
      <div className="constellation-layout">
        <div className="constellation-stage">
          <div className="graph-toolbar">
            <div
              className="identity-mode"
              aria-label="Relationship history mode"
            >
              <button
                aria-pressed={view === "current"}
                onClick={() => {
                  setView("current");
                  if (filter === "historical") setFilter("all");
                }}
              >
                Current relationships
              </button>
              <button
                aria-pressed={view === "historical"}
                onClick={() => setView("historical")}
              >
                Historical relationships
              </button>
            </div>
            <span className="graph-caption">
              INVESTIGATION ONLY · NO EXTERNAL WRITES
            </span>
          </div>
          <div
            className="identity-status-filters segmented"
            aria-label="Relationship filters"
          >
            {[
              "all",
              "verified",
              "confirmed",
              "candidate",
              "conflict",
              "historical",
              "unknown",
            ].map((f) => (
              <button
                key={f}
                aria-pressed={filter === f}
                className={filter === f ? "selected" : ""}
                onClick={() => {
                  setFilter(f);
                  if (f === "historical") setView("historical");
                }}
              >
                {f === "all" ? "All traces" : label(f)}
              </button>
            ))}
          </div>
          <div
            className={`graph-viewport ${loading ? "identity-updating" : ""}`}
            ref={viewport}
            tabIndex={0}
            aria-label="Identity graph canvas"
            onKeyDown={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.key === "+") setZoom((z) => Math.min(2.2, z + 0.15));
              if (e.key === "-") setZoom((z) => Math.max(0.25, z - 0.15));
              if (e.key === "f") {
                e.preventDefault();
                fit();
              }
              if (e.key.startsWith("Arrow")) {
                e.preventDefault();
                setPan((p) => ({
                  x:
                    p.x +
                    (e.key === "ArrowRight"
                      ? 30
                      : e.key === "ArrowLeft"
                        ? -30
                        : 0),
                  y:
                    p.y +
                    (e.key === "ArrowDown"
                      ? 30
                      : e.key === "ArrowUp"
                        ? -30
                        : 0),
                }));
              }
            }}
            onPointerDown={(e) => {
              if ((e.target as Element).closest('button,[role="button"]'))
                return;
              panDrag.current = {
                x: e.clientX,
                y: e.clientY,
                start: pan,
                moved: false,
              };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              const d = panDrag.current;
              if (d) {
                if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3)
                  d.moved = true;
                setPan({
                  x: d.start.x + e.clientX - d.x,
                  y: d.start.y + e.clientY - d.y,
                });
              }
            }}
            onPointerUp={() => {
              if (panDrag.current && !panDrag.current.moved) clear();
              panDrag.current = null;
            }}
            onPointerCancel={() => {
              panDrag.current = null;
            }}
          >
            <div
              className="graph-world"
              style={{
                transformOrigin: "0 0",
                transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`,
                height: worldHeight > 520 ? `${worldHeight}px` : "100%",
              }}
            >
              <svg
                className="graph-lines"
                viewBox={`0 0 1000 ${worldHeight}`}
                preserveAspectRatio="none"
                aria-label="Evidence backed identity relationships"
              >
                <defs>
                  <radialGradient id="identity-aura">
                    <stop stopColor="#2563EB" stopOpacity=".06" />
                    <stop offset="1" stopColor="#2563EB" stopOpacity="0" />
                  </radialGradient>
                  <marker
                    id="identity-direction"
                    viewBox="0 0 8 8"
                    refX="7"
                    refY="4"
                    markerWidth="5"
                    markerHeight="5"
                    orient="auto"
                  >
                    <path
                      d="M0 0L8 4L0 8"
                      fill="none"
                      stroke="context-stroke"
                    />
                  </marker>
                </defs>
                <ellipse
                  cx="490"
                  cy="260"
                  rx="330"
                  ry="210"
                  fill="url(#identity-aura)"
                />
                <ellipse
                  cx="490"
                  cy="260"
                  rx="310"
                  ry="185"
                  className="graph-orbit"
                />
                <ellipse
                  cx="490"
                  cy="260"
                  rx="205"
                  ry="125"
                  className="graph-orbit"
                />
                {edges.map((e) => {
                  const a = loc(e.source),
                    b = loc(e.target),
                    peers = validEdges
                      .filter(
                        (p) =>
                          (p.source === e.source && p.target === e.target) ||
                          (p.source === e.target && p.target === e.source),
                      )
                      .sort((x, y) => x.id.localeCompare(y.id)),
                    bend =
                      (e.relationship.includes("change") ? -45 : 24) +
                      (peers.findIndex((p) => p.id === e.id) -
                        (peers.length - 1) / 2) *
                        48,
                    route = `M ${a[0]} ${a[1]} Q ${(a[0] + b[0]) / 2} ${(a[1] + b[1]) / 2 + bend} ${b[0]} ${b[1]}`,
                    status = statuses.get(e.id)!;
                  const dim = pathFocus
                    ? path.edges.has(e.id)
                      ? 1
                      : 0.12
                    : active
                      ? e.id === active.id
                        ? 1
                        : nearby.has(e.source) && nearby.has(e.target)
                          ? 0.6
                          : 0.15
                      : selected
                        ? e.source === selected || e.target === selected
                          ? 1
                          : 0.22
                        : 1;
                  return (
                    <g
                      className={`identity-edge ${status} ${e.id === edgeId ? "focused" : ""} ${justEnded.includes(e.id) ? "just-ended" : ""}`}
                      key={e.id}
                      data-edge-id={e.id}
                      data-status={status}
                      role="button"
                      tabIndex={0}
                      aria-pressed={e.id === edgeId}
                      aria-label={`${label(e.relationship)}: ${e.source} to ${e.target}; ${statusName[status]}`}
                      opacity={dim}
                      onClick={() => chooseEdge(e.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          chooseEdge(e.id);
                        }
                      }}
                    >
                      <path d={route} className="edge-hit" />
                      <path
                        d={route}
                        className="edge-line"
                        markerEnd={
                          e.directional ? "url(#identity-direction)" : undefined
                        }
                      />
                      <circle
                        cx={a[0]}
                        cy={a[1]}
                        r="3"
                        className="identity-endpoint"
                      />
                      <circle
                        cx={b[0]}
                        cy={b[1]}
                        r="3"
                        className="identity-endpoint"
                      />
                      {isEnded(status) && (
                        <g
                          className="identity-end-marker"
                          transform={`translate(${(a[0] + b[0]) / 2},${(a[1] + b[1]) / 2 + bend / 2})`}
                        >
                          <circle r="7" />
                          <path d="M-3 0H3" />
                          <title>
                            {statusName[status]}
                            {e.valid_to ? ` · ${fullTime(e.valid_to)}` : ""}
                          </title>
                        </g>
                      )}
                      {e.id === edgeId && (
                        <text
                          className="identity-edge-label"
                          x={(a[0] + b[0]) / 2}
                          y={(a[1] + b[1]) / 2 + bend / 2 - 13}
                          textAnchor="middle"
                        >
                          {statusName[status]}
                        </text>
                      )}
                    </g>
                  );
                })}
                <text x="30" y={worldHeight - 25} className="svg-coordinate">
                  SOURCE-BOUND IDENTITY SPACE / {data.case_id}
                </text>
                <path
                  d="M940 30h20m-10-10v20M30 30h20M40 20v20"
                  className="crosshairs"
                />
              </svg>
              {visibleNodes.map((n) => {
                const point = loc(n.id),
                  subject = n.kind === "subject",
                  connected = eligibleEdges.filter(
                    (e) => e.source === n.id || e.target === n.id,
                  ),
                  ended = connected.filter((e) =>
                    isEnded(statuses.get(e.id)!),
                  ).length;
                return (
                  <button
                    key={n.id}
                    data-node-id={n.id}
                    className={`identity-node ${subject ? "subject-node" : ""} node-kind-${n.kind} ${selected === n.id || endpoints.has(n.id) ? "node-selected" : ""} ${active && endpoints.has(n.id) ? "edge-endpoint-selected" : ""}`}
                    style={{
                      left: `${point[0] / 10}%`,
                      top: `${(point[1] / worldHeight) * 100}%`,
                      opacity: active && !nearby.has(n.id) ? 0.25 : 1,
                    }}
                    title={`${n.label}\n${n.kind} · ${connected.length - ended} active/unverified · ${ended} historical relationships`}
                    onClick={() => {
                      if (!suppressClick.current)
                        chooseNode(selected === n.id ? "" : n.id);
                      suppressClick.current = false;
                    }}
                    onDoubleClick={() => {
                      chooseNode(n.id);
                      setHops((h) => h + 1);
                      setCollapsed(true);
                    }}
                    onKeyDown={(e) => {
                      if (e.key.startsWith("Arrow")) {
                        e.preventDefault();
                        const index = visibleNodes.findIndex(
                            (x) => x.id === n.id,
                          ),
                          delta =
                            e.key === "ArrowRight" || e.key === "ArrowDown"
                              ? 1
                              : -1,
                          next =
                            visibleNodes[
                              (index + delta + visibleNodes.length) %
                                visibleNodes.length
                            ];
                        viewport.current
                          ?.querySelector<HTMLButtonElement>(
                            `[data-node-id="${CSS.escape(next.id)}"]`,
                          )
                          ?.focus();
                      }
                    }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      drag.current = {
                        id: n.id,
                        x: e.clientX,
                        y: e.clientY,
                        start: point,
                        moved: false,
                      };
                      e.currentTarget.setPointerCapture(e.pointerId);
                    }}
                    onPointerMove={(e) => {
                      const d = drag.current,
                        r = viewport.current?.getBoundingClientRect();
                      if (d?.id !== n.id || !r) return;
                      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4)
                        d.moved = true;
                      setPositions((old) => ({
                        ...old,
                        [n.id]: [
                          Math.max(
                            65,
                            Math.min(
                              935,
                              d.start[0] +
                                ((e.clientX - d.x) * 1000) / r.width / zoom,
                            ),
                          ),
                          Math.max(
                            60,
                            Math.min(
                              worldHeight - 60,
                              d.start[1] +
                                ((e.clientY - d.y) *
                                  (worldHeight > 520 ? 1 : 520 / r.height)) /
                                  zoom,
                            ),
                          ),
                        ],
                      }));
                    }}
                    onPointerUp={() => {
                      suppressClick.current = !!drag.current?.moved;
                      drag.current = null;
                    }}
                    onPointerCancel={() => {
                      drag.current = null;
                    }}
                    aria-label={`Inspect ${n.kind}: ${n.label}`}
                    aria-pressed={selected === n.id}
                  >
                    <span className="node-orb">{nodeIcon(n)}</span>
                    <span className="node-kind">
                      {subject ? "STABLE USER ID" : n.kind.toUpperCase()}
                    </span>
                    <span className="node-label">
                      {subject
                        ? data.name
                        : n.label.length > 26
                          ? n.label.slice(0, 12) + "…" + n.label.slice(-8)
                          : n.label}
                    </span>
                    {subject && <span className="node-id">{n.id}</span>}
                    <span className="identity-node-tooltip">
                      {n.label}
                      <small>
                        {connected.length - ended} active/unverified · {ended}{" "}
                        historical
                      </small>
                    </span>
                  </button>
                );
              })}
            </div>
            {!edges.length && (
              <div className="graph-empty">
                <span className="small-label">RELATIONSHIP FILTER</span>
                <p>
                  No {filter === "all" ? "eligible" : filter} relationships in
                  this view.
                </p>
                <small>Missing connections do not establish deletion.</small>
              </div>
            )}
            <div className="graph-controls">
              <button
                aria-label="Zoom identity graph out"
                onClick={() => setZoom((z) => Math.max(0.25, z - 0.15))}
              >
                <Minus size={15} />
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <button
                aria-label="Zoom identity graph in"
                onClick={() => setZoom((z) => Math.min(2.2, z + 0.15))}
              >
                <Plus size={15} />
              </button>
              <button aria-label="Fit identity graph to screen" onClick={fit}>
                <Expand size={15} />
              </button>
              <button aria-label="Reset identity view" onClick={reset}>
                <Focus size={15} />
              </button>
            </div>
          </div>
          <div className="identity-explore-tools">
            {allNodes.some((n) => n.kind === "resource") && (
              <button
                aria-pressed={resourceExpanded}
                onClick={() => setResourceExpanded((v) => !v)}
              >
                {resourceExpanded ? "Collapse" : "Show"} resource associations (
                {allNodes.filter((n) => n.kind === "resource").length})
              </button>
            )}
            <button
              disabled={!root}
              onClick={() => {
                setHops((h) => h + 1);
                setCollapsed(true);
                setLimit((l) => Math.min(allNodes.length, l + 40));
              }}
            >
              Expand neighbourhood ({hops} hop{hops === 1 ? "" : "s"})
            </button>
            <button
              aria-pressed={collapsed}
              disabled={!root}
              onClick={() => setCollapsed((c) => !c)}
            >
              {collapsed
                ? "Expand all relationships"
                : "Collapse unrelated groups"}
            </button>
            <button
              disabled={!selected && !active}
              onClick={() => setPathFocus((p) => !p)}
              aria-pressed={pathFocus}
            >
              Focus selected path
            </button>
            <button onClick={clear}>
              <CircleX size={12} />
              Clear selection
            </button>
            {progressive && visibleNodes.length < allNodes.length && (
              <button onClick={() => setLimit((l) => l + 40)}>
                Show next 40 identifiers
              </button>
            )}
          </div>
          <div className="graph-underbar">
            <div className="graph-legend">
              <span>
                <i className="solid" />
                Verified
              </span>
              <span>
                <i className="confirmed-line" />
                Confirmed
              </span>
              <span>
                <i className="dashed" />
                Candidate
              </span>
              <span>
                <i className="conflict-line" />
                Conflict
              </span>
              <span>
                <i className="historical-line" />
                Ended / removed
              </span>
            </div>
          </div>
          <p className="identity-graph-note">
            <BadgeCheck size={13} />
            Colours describe the supplied relationship evidence. Node size
            identifies its role. Entity deletion is shown separately only when
            supplied.
          </p>
        </div>
        <IdentityInspector
          {...props}
          selected={selected}
          active={active}
          edges={eligibleEdges}
          onEdge={chooseEdge}
          onNode={chooseNode}
          onFocus={() => {
            setPathFocus((p) => !p);
            if (selected) setCollapsed(true);
          }}
        />
      </div>
      <div className="scene-note">
        <span>IDENTIFIERS · VALIDITY INTERVALS · ORIGINAL EVIDENCE</span>
        <span>INVESTIGATION ONLY</span>
      </div>
    </section>
  );
}
