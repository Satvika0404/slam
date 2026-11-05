import { useState } from "react";
import { ArrowRight, LockKeyhole } from "lucide-react";
import type { ConsoleData, InspectEvidence } from "./types";
import { number, human } from "./model";
import {
  ConsoleEmpty,
  ConsolePanel,
  ConsoleStats,
  EvidenceRefs,
} from "./Shared";

export default function Retention({
  data,
  onInspect,
  imported,
}: {
  data: ConsoleData;
  onInspect: InspectEvidence;
  imported: boolean;
}) {
  const [severity, setSeverity] = useState("All"),
    [category, setCategory] = useState("All"),
    [threshold, setThreshold] = useState(90);
  const items = data.register.filter(
    (r) =>
      (severity === "All" || r.sev === severity) &&
      (category === "All" || r.cat === category),
  );
  const years = [
    ...new Set([
      ...data.retention.audit_by_year.map((r) => r[0]),
      ...data.retention.legal_by_year.map((r) => r[0]),
      ...data.retention.legal_register.map((r) =>
        Number(r.retain_until.slice(-4)),
      ),
      ...(data.retention.security_extract ? [2027] : []),
    ]),
  ].sort();
  const yearValues = years.map((year) => ({
    year,
    counts: [
      data.retention.audit_by_year
        .filter((r) => r[0] === year)
        .reduce((n, r) => n + r[1], 0) +
        (year === 2027 && data.retention.security_extract ? 1 : 0),
      data.retention.legal_by_year
        .filter((r) => r[0] === year)
        .reduce((n, r) => n + r[1], 0),
      data.retention.legal_register.filter(
        (r) => Number(r.retain_until.slice(-4)) === year,
      ).length,
    ],
  }));
  const ymax = Math.max(
    1,
    ...yearValues.map((y) => y.counts.reduce((a, b) => a + b, 0)),
  );
  return (
    <div className="intel-tab-body">
      <ConsoleStats
        items={[
          {
            label: "Register classes",
            value: number(data.register.length),
            note: imported
              ? "Supplied analysis entries; not all are violations"
              : "Evidence-backed findings in this case",
          },
          {
            label: "High-severity entries",
            value: number(data.register.filter((r) => r.sev === "High").length),
            note: imported
              ? "Severity labels supplied by the attachment"
              : "Review in the audit folio",
            tone: "coral-text",
          },
          {
            label: "Retention rules",
            value: number(
              data.rules.filter((r) => r.action === "RETAIN").length,
            ),
            note: "Retain does not authorize blanket deletion",
          },
          {
            label: "Dates available",
            value: years.length ? `${years[0]}–${years.at(-1)}` : "Not exposed",
            note: "Retain-until years present in this read model",
          },
        ]}
      />
      <ConsolePanel
        number="01"
        title="The conflict register"
        note="Keep the reason, the policy and the consequence together. Scheduling reminders are separate from established violations."
        tools={
          <label className="intel-search">
            Category
            <select
              aria-label="Conflict category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {["All", ...new Set(data.register.map((r) => r.cat))].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
        }
      >
        <div
          className="intel-chips"
          role="group"
          aria-label="Conflict severity"
        >
          {["All", ...new Set(data.register.map((r) => r.sev))].map((s) => (
            <button
              key={s}
              onClick={() => setSeverity(s)}
              aria-pressed={s === severity}
            >
              {s}
            </button>
          ))}
        </div>
        {items.map((r) => (
          <article className="intel-conflict" key={r.id}>
            <div className="intel-conflict-heading">
              <span className="intel-conflict-id">{r.id}</span>
              <div>
                <span
                  className={`intel-pill ${r.sev === "High" ? "is-risk" : ""}`}
                >
                  {r.sev} · {r.cat}
                </span>
                <h3>{r.title}</h3>
                <p>
                  {r.rule}
                  {imported
                    ? " · supplied policy association"
                    : " · engine policy association"}
                </p>
              </div>
              <div className="intel-conflict-count">
                <b>{number(r.n)}</b>
                <span>{r.unit}</span>
              </div>
            </div>
            <div className="intel-conflict-body">
              <div>
                <span className="intel-label">
                  {imported ? "SUPPLIED RATIONALE" : "AUDIT BASIS"}
                </span>
                <p>{r.why}</p>
              </div>
              <div>
                <span className="intel-label">CONSEQUENCE TO REVIEW</span>
                <p>{r.conflict}</p>
              </div>
              <div>
                <span className="intel-label">
                  {imported ? "SUGGESTED TREATMENT" : "PROPOSED REMEDIATION"}
                </span>
                <p className="intel-action">
                  <ArrowRight size={14} />
                  {r.action}
                </p>
                <EvidenceRefs
                  ids={r.ev}
                  onInspect={onInspect}
                  context={r.title}
                />
              </div>
            </div>
          </article>
        ))}
        {!items.length && (
          <ConsoleEmpty>
            {data.register.length
              ? "No register entries match both filters."
              : "No findings are listed in this case read model. This view alone does not establish completeness."}
          </ConsoleEmpty>
        )}
        {imported && (
          <p className="intel-method">
            These entries reproduce the attachment’s interpretations. Several
            are claims or future retention reviews, rather than proven policy
            violations. Original sources and policy applicability must be
            checked before acting.
          </p>
        )}
      </ConsolePanel>
      <div className="intel-two-col">
        <ConsolePanel
          number="02"
          title="Age is a lens. Not a policy."
          note="Explore records without a confirmed delete using a threshold you control."
        >
          <div className="intel-age-control">
            <label htmlFor="intel-age">Assumed age threshold</label>
            <output htmlFor="intel-age">{threshold} days</output>
            <input
              id="intel-age"
              type="range"
              min="30"
              max="240"
              step="30"
              value={threshold}
              onChange={(e) => setThreshold(+e.target.value)}
              aria-label="Age threshold in days"
            />
          </div>
          {data.aging.series.map((s) => {
            const over = s.bins.reduce(
                (n, c, i) => n + (data.aging.bins[i][0] >= threshold ? c : 0),
                0,
              ),
              max = Math.max(1, ...s.bins);
            return (
              <div className="intel-age-row" key={s.system}>
                <div>
                  <h3>{s.label}</h3>
                  <span>{s.system}</span>
                </div>
                <svg
                  viewBox="0 0 280 65"
                  role="img"
                  aria-label={`${s.label}: ${over} of ${s.total} above ${threshold} days`}
                >
                  {s.bins.map((c, i) => (
                    <rect
                      key={i}
                      x={i * 31 + 2}
                      y={58 - (c / max) * 50}
                      width="25"
                      height={(c / max) * 50}
                      rx="2"
                      className={
                        data.aging.bins[i][0] >= threshold ? "is-old" : ""
                      }
                    >
                      <title>
                        {data.aging.bins[i].join("–")} days: {c}
                      </title>
                    </rect>
                  ))}
                </svg>
                <strong>
                  {number(over)}
                  <small>of {number(s.total)}</small>
                </strong>
              </div>
            );
          })}
          {!data.aging.series.length && (
            <ConsoleEmpty>
              Creation timestamps and confirmed-delete histories are not
              available here.
            </ConsoleEmpty>
          )}
          <p className="intel-method">
            The {threshold}-day threshold is an exploratory assumption. It is
            not supplied by deletion_rules.csv and never changes the audit
            verdict. Snapshot age alone does not establish the present state.
          </p>
        </ConsolePanel>
        <ConsolePanel
          number="03"
          title="Keep until. Review then."
          note="Retain-until dates describe a review boundary, not automatic permission to delete."
        >
          <div className="intel-retain-illustration">
            <LockKeyhole size={29} />
            <p>{data.retention.security_extract_note}</p>
            {data.retention.security_extract && (
              <EvidenceRefs
                ids={[data.retention.security_extract]}
                onInspect={onInspect}
                context="Supplied security retention extract"
              />
            )}
          </div>
          {years.length ? (
            <>
              <svg
                viewBox="0 0 460 230"
                className="intel-retention-chart"
                role="img"
                aria-label="Supplied retained record counts by retain-until year"
              >
                {yearValues.map((v, i) => {
                  let offset = 0;
                  const x = 35 + (i * 390) / Math.max(1, years.length),
                    w = Math.min(48, 300 / years.length);
                  return (
                    <g key={v.year}>
                      {v.counts.map((c, j) => {
                        const h = (c / ymax) * 150;
                        offset += h;
                        return c ? (
                          <rect
                            key={j}
                            x={x}
                            y={180 - offset}
                            width={w}
                            height={h}
                            rx="2"
                            fill={
                              ["var(--cyan)", "var(--violet)", "var(--lime)"][j]
                            }
                          >
                            <title>
                              {v.year},{" "}
                              {["Security", "Legal", "Finance register"][j]}:{" "}
                              {c}
                            </title>
                          </rect>
                        ) : null;
                      })}
                      <text x={x + w / 2} y="205" textAnchor="middle">
                        {v.year}
                      </text>
                      <text x={x + w / 2} y={165 - offset} textAnchor="middle">
                        {v.counts.reduce((a, b) => a + b, 0)}
                      </text>
                    </g>
                  );
                })}
              </svg>
              <div className="intel-chart-legend">
                <span>
                  <i className="cyan" />
                  Security
                </span>
                <span>
                  <i className="violet" />
                  Legal
                </span>
                <span>
                  <i className="lime" />
                  Finance register
                </span>
              </div>
            </>
          ) : (
            <ConsoleEmpty>
              Explicit retain-until dates are not exposed in this case.
            </ConsoleEmpty>
          )}
        </ConsolePanel>
      </div>
      <div className="intel-two-col">
        <ConsolePanel
          number="04"
          title="Superseded identifiers"
          note="Historical keys still matter when searching older copies. Counts do not authorize identity merging."
        >
          {data.identifier_fields.length ? (
            <table className="intel-table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Changes</th>
                  <th>Users</th>
                  <th>Older than a year</th>
                </tr>
              </thead>
              <tbody>
                {data.identifier_fields.map((f) => (
                  <tr key={f.field}>
                    <td>{human(f.field)}</td>
                    <td>{f.changes}</td>
                    <td>{f.users}</td>
                    <td>{f.over_365}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <ConsoleEmpty>
              Use Identity Constellation for this case’s source-backed
              historical links; corpus-wide change counts are not provided.
            </ConsoleEmpty>
          )}
        </ConsolePanel>
        <ConsolePanel
          number="05"
          title="Legal and finance holds"
          note="Rows supplied in the attachment’s hold register."
        >
          {data.retention.legal_register.length ? (
            <>
              <div className="intel-table-scroll">
                <table className="intel-table">
                  <thead>
                    <tr>
                      <th>Order / user</th>
                      <th>Reason</th>
                      <th>Retain until</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.retention.legal_register.map((r) => (
                      <tr key={r.order}>
                        <td>
                          {r.order}
                          <small>{r.user}</small>
                        </td>
                        <td>{r.kind}</td>
                        <td>{r.retain_until}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <EvidenceRefs
                ids={[data.retention.legal_file].filter(Boolean)}
                onInspect={onInspect}
                context="Supplied hold register"
              />
            </>
          ) : (
            <ConsoleEmpty>
              No per-record hold dates are included in this read model.
            </ConsoleEmpty>
          )}
        </ConsolePanel>
      </div>
      <ConsolePanel
        number="06"
        title="Policy reference"
        note="Conditional rules require applicability to be established for each record."
      >
        <div className="intel-policy-grid">
          {data.rules.map((r) => (
            <div key={r.id}>
              <span>{r.id}</span>
              <strong>{human(r.category)}</strong>
              <p>{r.condition}</p>
              <b
                className={`intel-policy-action action-${r.action.toLowerCase()}`}
              >
                {r.action}
              </b>
            </div>
          ))}
        </div>
      </ConsolePanel>
    </div>
  );
}
