import { Fragment, useState } from "react";
import { ChevronDown, TrendingUp } from "lucide-react";
import type { ConsoleData, InspectEvidence, Pattern } from "./types";
import { human, number, percent, wilson, date } from "./model";
import {
  ConsoleEmpty,
  ConsolePanel,
  ConsoleStats,
  EvidenceRefs,
} from "./Shared";

function Rate({
  value,
  interval,
}: {
  value: number | null;
  interval?: number[] | null;
}) {
  return value == null ? (
    <span className="intel-muted">Not a rate</span>
  ) : (
    <div className="intel-rate">
      <span>
        <i style={{ width: `${value * 100}%` }} />
        {interval && (
          <b
            style={{
              left: `${interval[0] * 100}%`,
              width: `${(interval[1] - interval[0]) * 100}%`,
            }}
          />
        )}
      </span>
      <strong>{percent(value)}</strong>
    </div>
  );
}
function Spark({ pattern }: { pattern: Pattern }) {
  const values = pattern.series.map((s) => s.c),
    mx = Math.max(1, ...values),
    points = values
      .map(
        (v, i) =>
          `${(i * 100) / Math.max(1, values.length - 1)},${32 - (v * 27) / mx}`,
      )
      .join(" ");
  return (
    <svg
      viewBox="0 0 100 36"
      className="intel-spark"
      role="img"
      aria-label={`${pattern.name}: monthly counts ${values.join(", ")}`}
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
function Trend({ data }: { data: ConsoleData }) {
  const [hover, setHover] = useState<number | null>(null);
  const months = data.meta.months,
    projection = data.rate_fc.fc;
  const count = months.length + projection.length,
    x = (i: number) => 55 + (i * 865) / Math.max(1, count - 1),
    y = (v: number) => 265 - v * 240;
  const series = [
    {
      name: "All reported outcomes",
      s: data.rate_series,
      f: data.rate_fc.fc,
      color: "var(--cyan)",
    },
    {
      name: "Delete · redact · anonymize",
      s: data.ctrl_series,
      f: data.ctrl_fc.fc,
      color: "var(--coral)",
    },
  ];
  const labels = [
    ...months.map((m) => data.meta.month_labels[m] ?? m),
    ...projection.map((f) => {
      const d = new Date(`${months.at(-1)}-01T00:00:00Z`);
      d.setUTCMonth(d.getUTCMonth() + f.h);
      return d.toLocaleDateString("en", { month: "short", timeZone: "UTC" });
    }),
  ];
  if (!data.rate_series.length)
    return (
      <ConsoleEmpty>
        This case read model has no global activity outcomes. Monthly rates and
        forecasts cannot be computed from resource states.
      </ConsoleEmpty>
    );
  return (
    <>
      <div className="intel-trend-scroll">
        <svg
          className="intel-trend"
          viewBox="0 0 970 310"
          role="img"
          aria-label="Monthly reported failure rates, with supplied forecast intervals"
        >
          <defs>
            <linearGradient id="intel-projection" x2="1" y2="0">
              <stop stopColor="#a58aff" stopOpacity="0.03" />
              <stop offset="1" stopColor="#a58aff" stopOpacity="0.13" />
            </linearGradient>
          </defs>
          {projection.length > 0 && (
            <>
              <rect
                x={x(months.length - 1)}
                y={20}
                width={x(count - 1) - x(months.length - 1) + 12}
                height={245}
                fill="url(#intel-projection)"
              />
              <text x={x(months.length - 1) + 15} y={34}>
                SUPPLIED PROJECTION
              </text>
            </>
          )}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line
                x1="55"
                x2="935"
                y1={y(t)}
                y2={y(t)}
                className="intel-gridline"
              />
              <text x="38" y={y(t) + 4} textAnchor="end">
                {t * 100}%
              </text>
            </g>
          ))}
          {labels.map((m, i) => (
            <text
              key={i}
              x={x(i)}
              y="294"
              textAnchor="middle"
              className={i >= months.length ? "intel-projected-label" : ""}
            >
              {m}
            </text>
          ))}
          {series.map((s) => {
            const last = s.s.at(-1);
            if (!last) return null;
            const future = [
              {
                i: months.length - 1,
                y: last.rate,
                lo: last.rate,
                hi: last.rate,
              },
              ...s.f.map((f, i) => ({ ...f, i: months.length + i })),
            ];
            return (
              <g key={s.name} style={{ color: s.color }}>
                {s.f.length > 0 && (
                  <>
                    <polygon
                      points={[
                        ...future.map((p) => `${x(p.i)},${y(p.hi)}`),
                        ...future
                          .slice()
                          .reverse()
                          .map((p) => `${x(p.i)},${y(p.lo)}`),
                      ].join(" ")}
                      fill="currentColor"
                      opacity=".1"
                    />
                    <polyline
                      points={future
                        .map((p) => `${x(p.i)},${y(p.y)}`)
                        .join(" ")}
                      stroke="currentColor"
                      fill="none"
                      strokeWidth="2"
                      strokeDasharray="5 5"
                    />
                  </>
                )}
                <polyline
                  className="intel-draw-line"
                  points={s.s.map((v, i) => `${x(i)},${y(v.rate)}`).join(" ")}
                  stroke="currentColor"
                  fill="none"
                  strokeWidth="2.5"
                />
                {s.s.map((v, i) => (
                  <circle
                    key={v.m}
                    cx={x(i)}
                    cy={y(v.rate)}
                    r={hover === i ? 5 : 3}
                    fill="currentColor"
                  >
                    <title>
                      {labels[i]}: {percent(v.rate)} ({v.bad}/{v.n})
                    </title>
                  </circle>
                ))}
              </g>
            );
          })}
          {labels.map((m, i) => (
            <rect
              key={i}
              x={x(i) - 29}
              y="38"
              width="58"
              height="230"
              fill="transparent"
              tabIndex={0}
              aria-label={
                i < months.length
                  ? `${m}, all outcomes ${percent(data.rate_series[i]?.rate)}, controlled ${percent(data.ctrl_series[i]?.rate)}`
                  : `${m}, supplied projection ${percent(projection[i - months.length]?.y)}`
              }
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
            />
          ))}
          {hover !== null && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1="42"
              y2="265"
              stroke="var(--ivory)"
              strokeOpacity=".25"
              strokeDasharray="2 4"
            />
          )}
        </svg>
      </div>
      <div className="intel-chart-legend">
        <span>
          <i className="cyan" />
          All reported outcomes
        </span>
        <span>
          <i className="coral" />
          Controlled operations
        </span>
        <span>Dashed: supplied projection · shaded: supplied 80% interval</span>
      </div>
      <div className="intel-chart-readout" aria-live="polite">
        {hover === null
          ? "Hover or focus a month to inspect its denominators."
          : hover < months.length
            ? `${labels[hover]} · All: ${data.rate_series[hover]?.bad} / ${data.rate_series[hover]?.n} · Controlled: ${data.ctrl_series[hover]?.bad} / ${data.ctrl_series[hover]?.n}`
            : `${labels[hover]} · Forecast ${percent(projection[hover - months.length]?.y)} · ${percent(projection[hover - months.length]?.lo)}–${percent(projection[hover - months.length]?.hi)} supplied interval`}
      </div>
    </>
  );
}
function Predictor({ data }: { data: ConsoleData }) {
  const table = data.predictor.table,
    operations = [...new Set(table.map((r) => r.op))];
  const [op, setOp] = useState(
    operations.includes("DELETE_RECORD")
      ? "DELETE_RECORD"
      : (operations[0] ?? ""),
  );
  const [system, setSystem] = useState(
    table.find((r) => r.op === "DELETE_RECORD" && r.system === "search_service")
      ?.system ??
      table[0]?.system ??
      "",
  );
  const row = table.find((r) => r.op === op && r.system === system),
    prior = row ? data.predictor.class_rate[row.cls] : 0;
  const estimate = row ? (row.bad + 10 * prior) / (row.n + 10) : null,
    ci = row ? wilson(row.bad, row.n) : null;
  return (
    <ConsolePanel
      number="04"
      title="Failure estimator"
      note="An operation-aware estimate, with the observed sample kept in view."
    >
      {!row ? (
        <ConsoleEmpty>
          No operation-level history is available for this investigation.
        </ConsoleEmpty>
      ) : (
        <>
          <div className="intel-fields">
            <label>
              Operation
              <select
                value={op}
                onChange={(e) => {
                  setOp(e.target.value);
                  setSystem(table.find((r) => r.op === e.target.value)!.system);
                }}
              >
                {operations.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </label>
            <label>
              Target system
              <select
                value={system}
                onChange={(e) => setSystem(e.target.value)}
              >
                {table
                  .filter((r) => r.op === op)
                  .map((r) => (
                    <option key={r.system}>{r.system}</option>
                  ))}
              </select>
            </label>
          </div>
          <div className="intel-estimate">
            <TrendingUp size={23} />
            <span>SMOOTHED REPORTED FAILURE RATE</span>
            <b>{percent(estimate)}</b>
            <p>
              {ci
                ? `${percent(ci[0])}–${percent(ci[1])} observed Wilson 95% interval.`
                : "No observed interval."}
            </p>
          </div>
          <dl className="intel-dl">
            <dt>All observed outcomes</dt>
            <dd>
              {row.bad} / {row.n}
            </dd>
            <dt>Last three months</dt>
            <dd>
              {row.bad3} / {row.n3}
            </dd>
            <dt>Operation-class mean</dt>
            <dd>{percent(prior)}</dd>
            <dt>Prior weight</dt>
            <dd>10 pseudo-observations</dd>
          </dl>
          <p className="intel-method">
            Estimate = (failures + 10 × class mean) / (sample + 10). This is a
            heuristic based on reported outcomes, not a calibrated prediction or
            proof of deletion.
          </p>
        </>
      )}
    </ConsolePanel>
  );
}
export default function Patterns({
  data,
  onInspect,
  imported,
}: {
  data: ConsoleData;
  onInspect: InspectEvidence;
  imported: boolean;
}) {
  const [group, setGroup] = useState("All"),
    [expanded, setExpanded] = useState<string[]>([]),
    [search, setSearch] = useState("");
  const patterns = data.patterns.filter(
    (p) =>
      (group === "All" || p.group === group) &&
      `${p.name} ${p.signature}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="intel-tab-body">
      <ConsoleStats
        items={[
          {
            label: "Reported non-success",
            value: percent(data.kpis.non_success_rate),
            note: `${number(data.kpis.non_success)} of ${number(data.kpis.events)} reported events`,
          },
          {
            label: "Controlled operations",
            value: percent(data.kpis.destructive_rate),
            note: `${number(data.kpis.destructive_bad)} of ${number(data.kpis.destructive_n)} outcomes`,
            tone: "coral-text",
          },
          {
            label: "Next-month estimate",
            value: data.count_fc.fc[0]
              ? `~${Math.round(data.count_fc.fc[0].y)}`
              : "Not estimated",
            note: data.count_fc.fc[0]
              ? `${Math.round(data.count_fc.fc[0].lo)}–${Math.round(data.count_fc.fc[0].hi)} supplied 80% interval`
              : "Insufficient activity history",
          },
          {
            label: "Written after delete",
            value: number(data.kpis.reborn),
            note: "Reported write after reported successful deletion",
          },
        ]}
      />
      <ConsolePanel
        number="01"
        title="The persistence signal"
        note="Reported operation outcomes over time. These are separate from evidence-backed audit verdicts."
      >
        <Trend data={data} />
        {imported && (
          <p className="intel-method">
            The attachment supplies nine complete months and a straight-line
            forecast. Its calculation script and raw observations were not
            attached; statistical assumptions and forecast coverage are
            unverified. October’s {data.meta.oct_partial_events} partial-month
            events were excluded by the supplied analysis.
          </p>
        )}
      </ConsolePanel>
      <ConsolePanel
        number="02"
        title="Pattern catalogue"
        note={`${patterns.length} of ${data.patterns.length} supplied patterns. Counts, denominators and source references stay attached.`}
        tools={
          <label className="intel-search">
            Search patterns
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Name or operation"
            />
          </label>
        }
      >
        <div className="intel-chips" role="group" aria-label="Pattern group">
          {["All", ...new Set(data.patterns.map((p) => p.group))].map((g) => (
            <button
              key={g}
              aria-pressed={g === group}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>
        {!patterns.length ? (
          <ConsoleEmpty>
            {data.patterns.length
              ? "No patterns match these filters."
              : "Global error patterns need operation-level outcomes. They cannot be inferred from a single audit verdict."}
          </ConsoleEmpty>
        ) : (
          <div className="intel-table-scroll">
            <table className="intel-table intel-pattern-table">
              <thead>
                <tr>
                  <th>Pattern / reported claim</th>
                  <th>Occurrences</th>
                  <th>Rate · supplied 95% interval</th>
                  <th>Next month</th>
                  <th>History</th>
                  <th>Trend / support</th>
                </tr>
              </thead>
              <tbody>
                {patterns.map((p) => (
                  <Fragment key={p.id}>
                    <tr>
                      <td>
                        <button
                          className="intel-expand"
                          aria-expanded={expanded.includes(p.id)}
                          aria-controls={`pattern-${p.id}`}
                          onClick={() =>
                            setExpanded((a) =>
                              a.includes(p.id)
                                ? a.filter((x) => x !== p.id)
                                : [...a, p.id],
                            )
                          }
                        >
                          <ChevronDown size={15} />
                          <span>
                            <strong>{p.name}</strong>
                            <small>
                              {p.id} · {p.signature}
                            </small>
                          </span>
                        </button>
                      </td>
                      <td>
                        <b>{number(p.count)}</b>
                        <small>
                          {p.kind === "snapshot"
                            ? `rows / ${p.n} tables`
                            : p.kind === "failure"
                              ? `of ${p.n} outcomes`
                              : "reported events"}
                        </small>
                      </td>
                      <td>
                        <Rate value={p.rate} interval={p.ci} />
                      </td>
                      <td>
                        {p.forecast[0] ? (
                          <>
                            <b>~{number(p.forecast[0].y)}</b>
                            <small>
                              {number(p.forecast[0].lo)}–
                              {number(p.forecast[0].hi)}
                            </small>
                          </>
                        ) : (
                          "Not estimated"
                        )}
                      </td>
                      <td>
                        <Spark pattern={p} />
                      </td>
                      <td>
                        <span className="intel-pill">{p.trend}</span>
                        <small>{p.confidence} · supplied label</small>
                      </td>
                    </tr>
                    {expanded.includes(p.id) && (
                      <tr className="intel-detail-row" id={`pattern-${p.id}`}>
                        <td colSpan={6}>
                          <div className="intel-pattern-detail">
                            <div>
                              <span className="intel-label">
                                SUPPLIED INTERPRETATION
                              </span>
                              <p>{p.note}</p>
                              <p className="intel-method">
                                Interpretation requires source and policy
                                verification. A reported operation result alone
                                does not establish record state.
                              </p>
                            </div>
                            <div>
                              <span className="intel-label">
                                RULE / STATISTICS
                              </span>
                              <p>
                                {p.rule} · slope {p.slope} / month
                                {p.p != null ? ` · p = ${p.p}` : ""}
                              </p>
                              <EvidenceRefs
                                ids={p.examples}
                                onInspect={onInspect}
                                context={p.name}
                              />
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ConsolePanel>
      <div className="intel-two-col">
        <ConsolePanel
          number="03"
          title="System × month"
          note="Controlled outcomes and replication checkpoints. Fewer than five observations remain unscored."
        >
          {!data.heatmap.rows.length ? (
            <ConsoleEmpty>
              No monthly operation matrix is available.
            </ConsoleEmpty>
          ) : (
            <div className="intel-table-scroll">
              <table className="intel-heatmap">
                <thead>
                  <tr>
                    <th>Target</th>
                    {data.meta.months.map((m) => (
                      <th key={m}>{data.meta.month_labels[m] ?? m}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.heatmap.rows.map((r) => (
                    <tr key={r.system}>
                      <th>{human(r.system)}</th>
                      {r.cells.map(([n, b], i) => (
                        <td
                          key={i}
                          style={
                            n >= 5
                              ? {
                                  background: `color-mix(in srgb, var(--coral) ${(b / n) * 46}%, #10151e)`,
                                }
                              : {}
                          }
                          tabIndex={0}
                          aria-label={`${r.system}, ${data.meta.months[i]}: ${b} of ${n} failed or partial`}
                        >
                          {n >= 5 ? `${Math.round((b / n) * 100)}%` : "—"}
                          <small>n={n}</small>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ConsolePanel>
        <Predictor data={data} />
      </div>
      <div className="intel-two-col">
        <ConsolePanel
          number="05"
          title="System risk register"
          note="Reported results ranked by non-success rate, with the sample size visible."
        >
          {data.systems_rank.length ? (
            <div className="intel-table-scroll">
              <table className="intel-table">
                <thead>
                  <tr>
                    <th>System</th>
                    <th>Outcomes</th>
                    <th>Rate</th>
                    <th>Next month</th>
                  </tr>
                </thead>
                <tbody>
                  {data.systems_rank.map((r) => (
                    <tr key={r.system}>
                      <td>{human(r.system)}</td>
                      <td>{number(r.n)}</td>
                      <td>
                        <Rate value={r.rate} interval={r.ci} />
                      </td>
                      <td>
                        {r.next_bad == null ? "—" : `~${number(r.next_bad)}`}
                        <small>
                          {r.next_lo != null
                            ? `${number(r.next_lo)}–${number(r.next_hi)}`
                            : ""}
                        </small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <ConsoleEmpty>
              No system-level operation history supplied.
            </ConsoleEmpty>
          )}
        </ConsolePanel>
        <ConsolePanel
          number="06"
          title="Replica drift"
          note="Differences per snapshot, not a count of unique people or current outstanding records."
        >
          {data.drift.length ? (
            <div className="intel-table-scroll">
              <table className="intel-table">
                <thead>
                  <tr>
                    <th>Snapshot</th>
                    <th>Topology</th>
                    <th>Primary / replica</th>
                    <th>Ghost / with IDs</th>
                  </tr>
                </thead>
                <tbody>
                  {data.drift.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <EvidenceRefs
                          ids={[r.file_id]}
                          onInspect={onInspect}
                          context={`Replica drift · ${r.topology}`}
                        />
                        <small>{date(r.captured_at)}</small>
                      </td>
                      <td>{human(r.topology)}</td>
                      <td>
                        {r.primary_rows} / {r.replica_rows}
                      </td>
                      <td className={r.ghost_rows ? "coral-text" : ""}>
                        {r.ghost_rows} / {r.ghost_with_identifiers}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <ConsoleEmpty>
              No comparable primary/replica snapshots are exposed in this read
              model.
            </ConsoleEmpty>
          )}
        </ConsolePanel>
      </div>
    </div>
  );
}
