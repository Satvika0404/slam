import { useState } from "react";
import { ArrowUpRight, Check, FileCheck2, LockKeyhole } from "lucide-react";
import { clock, label } from "../api";
import { EvidenceLink, SectionLabel, Status } from "../components";
import type { SceneProps } from "../types";
export default function Decision({
  data,
  onEvidence,
  onScene,
  loading,
}: SceneProps) {
  const [selected, setSelected] = useState("judge");
  const stage = data.stages.find((s) => s.id === selected)!;
  const ready = data.answer.ready_for_export;
  const status = data.answer.deletion_status ?? "UNVERIFIED";
  const ids = [
    ...new Set(
      data.answer.steps.filter((s) => s.evidence_id).map((s) => s.evidence_id),
    ),
  ];
  const face = [
    { id: "judge", path: "M400 40 400 295 85 485Z", x: 265, y: 246 },
    { id: "evidence", path: "M85 485 400 295 715 485Z", x: 400, y: 432 },
    { id: "verify", path: "M715 485 400 295 400 40Z", x: 534, y: 246 },
  ];
  return (
    <section className="decision-scene">
      <div className="scene-heading">
        <div>
          <SectionLabel number="06">THE DECISION CHAMBER</SectionLabel>
          <h1>
            Proof before
            <br />
            <em>pronouncement.</em>
          </h1>
        </div>
        <p className="heading-aside">
          Three perspectives.
          <br />
          One accountable decision.
          <span>DETERMINISTIC ENGINE · {clock(data.request.audit_at)} UTC</span>
        </p>
      </div>
      <div className="chamber-layout">
        <div className="chamber-stage">
          <div className="chamber-overline">
            <span>JUDGE — EVIDENCE — VERIFY</span>
            <span>SELECT A SURFACE TO INSPECT</span>
          </div>
          <svg
            viewBox="0 0 800 550"
            aria-label="Judge Evidence Verify decision structure"
          >
            <defs>
              <linearGradient id="prismGlass" x1="0" y1="0" x2="1" y2="1">
                <stop stopColor="#a58aff" stopOpacity=".13" />
                <stop offset="1" stopColor="#a58aff" stopOpacity=".015" />
              </linearGradient>
              <linearGradient id="prism-judge" x1="0" y1="0" x2="1" y2=".7">
                <stop stopColor="#ddd4ff" stopOpacity=".13" />
                <stop offset=".35" stopColor="#a58aff" stopOpacity=".035" />
                <stop offset="1" stopColor="#a58aff" stopOpacity=".08" />
              </linearGradient>
              <linearGradient id="prism-verify" x1=".2" y1="0" x2="1" y2="1">
                <stop stopColor="#b6b9db" stopOpacity=".025" />
                <stop offset=".6" stopColor="#a58aff" stopOpacity=".12" />
                <stop offset="1" stopColor="#f0eee7" stopOpacity=".025" />
              </linearGradient>
              <linearGradient id="prism-evidence" x1="0" y1="0" x2="0" y2="1">
                <stop stopColor="#a58aff" stopOpacity=".12" />
                <stop offset="1" stopColor="#26313d" stopOpacity=".04" />
              </linearGradient>
              <radialGradient id="chamberLight">
                <stop stopColor="#a58aff" stopOpacity=".1" />
                <stop offset="1" stopColor="#a58aff" stopOpacity="0" />
              </radialGradient>
            </defs>
            <ellipse
              cx="400"
              cy="325"
              rx="335"
              ry="230"
              fill="url(#chamberLight)"
            />
            <path d="M400 12 52 510 748 510Z" className="prism-outline" />
            <path d="M400 78 120 475 680 475Z" className="prism-inner" />
            {face.map((f) => {
              const result = data.stages.find((s) => s.id === f.id)!;
              return (
                <g
                  key={f.id}
                  role="button"
                  tabIndex={0}
                  className={`prism-face ${selected === f.id ? "selected" : ""} ${result.status === "PASSED" ? "passed" : "unresolved"}`}
                  aria-label={`Inspect ${result.label}: ${result.status}`}
                  onClick={() => setSelected(f.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(f.id);
                    }
                  }}
                >
                  <path d={f.path} style={{ fill: `url(#prism-${f.id})` }} />
                  <text
                    x={f.x}
                    y={f.y}
                    textAnchor="middle"
                    className="face-label"
                  >
                    {result.label.toUpperCase()}
                  </text>
                  <text
                    x={f.x}
                    y={f.y + 24}
                    textAnchor="middle"
                    className="face-status"
                  >
                    {result.status}
                  </text>
                </g>
              );
            })}
            <circle cx="400" cy="295" r="72" className="decision-seal" />
            <circle cx="400" cy="295" r="80" className="seal-ring" />
            <text x="400" y="274" textAnchor="middle" className="seal-overline">
              ENGINE RESULT
            </text>
            <text
              x="400"
              y="302"
              textAnchor="middle"
              className={`seal-result ${status === "COMPLETE" ? "complete" : "incomplete"}`}
            >
              {loading ? "RECONSTRUCTING" : status}
            </text>
            <text
              x="400"
              y="324"
              textAnchor="middle"
              className="seal-fingerprint"
            >
              {data.fingerprint.toUpperCase()}
            </text>
            <text x="65" y="75" className="svg-coordinate">
              POLICY / 01
            </text>
            <text x="610" y="75" className="svg-coordinate">
              STATE / 03
            </text>
            <text x="340" y="540" className="svg-coordinate">
              PROVENANCE / 02
            </text>
          </svg>
          <div className="chamber-ground">
            <LockKeyhole size={13} />
            <span>
              AI assists extraction. Deterministic code owns this result.
            </span>
          </div>
        </div>
        <aside className="chamber-inspector">
          <div className="chamber-stage-tabs" aria-label="Decision stages">
            {data.stages.map((s, i) => (
              <button
                key={s.id}
                className={selected === s.id ? "active" : ""}
                onClick={() => setSelected(s.id)}
              >
                <span>0{i + 1}</span>
                {s.label}
                <i>
                  {s.status === "PASSED" ? <Check size={12} /> : <span>·</span>}
                </i>
              </button>
            ))}
          </div>
          <div className="stage-description">
            <span className="small-label">
              {selected === "judge"
                ? "WHAT SHOULD BE TRUE"
                : selected === "evidence"
                  ? "WHAT THE SOURCES ESTABLISH"
                  : "WHAT THE ENGINE CAN CERTIFY"}
            </span>
            <h3>
              {selected === "judge"
                ? "The obligation."
                : selected === "evidence"
                  ? "The grounding."
                  : "The verdict."}
            </h3>
            <Status value={stage.status} />
            <p>{stage.description}</p>
          </div>
          {selected === "judge" ? (
            <div className="policy-list">
              {data.context.policy_rules.map((rule) => (
                <div key={rule.rule_id}>
                  <span className="policy-number">§</span>
                  <div>
                    <b>{label(rule.category)}</b>
                    <small>{rule.rule_id}</small>
                    <p>
                      {rule.required_action}
                      {rule.condition ? ` · ${rule.condition}` : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : selected === "evidence" ? (
            <div>
              <dl className="check-ledger">
                <dt>Eligible observations</dt>
                <dd>{data.context.eligible_observation_ids.length}</dd>
                <dt>After-cutoff observations</dt>
                <dd>{data.context.excluded_future_observation_ids.length}</dd>
                <dt>Unresolved conflicts</dt>
                <dd>{data.context.unresolved_conflicts.length}</dd>
              </dl>
              <span className="small-label">OPEN THE SUPPORTING SOURCE</span>
              <div className="evidence-stack">
                {ids.map((id) => (
                  <EvidenceLink key={id} id={id} onOpen={onEvidence} />
                ))}
              </div>
              {data.context.unresolved_conflicts.map((c) => (
                <p className="conflict-note" key={c}>
                  {c}
                </p>
              ))}
            </div>
          ) : (
            <div className="verification-ledger">
              {data.answer.blocking_issues.map((issue) => (
                <p className="conflict-note" key={issue}>
                  {issue}
                </p>
              ))}
              {data.answer.steps
                .filter((s) => s.phase === "VERIFICATION")
                .map((s) => (
                  <div key={s.step_no}>
                    <FileCheck2 size={15} />
                    <span>
                      {label(s.operation)}
                      <small>
                        {s.resource_id} ·{" "}
                        {s.evidence_id
                          ? "Source-backed observed state"
                          : "Future check · not yet satisfied"}
                      </small>
                      {s.evidence_id && (
                        <EvidenceLink id={s.evidence_id} onOpen={onEvidence} />
                      )}
                    </span>
                  </div>
                ))}
            </div>
          )}
          <div className="stage-footnote">
            <span>{ready ? "EXPORT-READY CASE" : "CERTIFICATION BLOCKED"}</span>
            <p>
              Recommendations are a plan. No external records have been changed.
            </p>
            <button className="primary-button" onClick={() => onScene("folio")}>
              Open audit folio <ArrowUpRight size={16} />
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}
