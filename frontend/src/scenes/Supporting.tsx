import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Asterisk,
  Check,
  Download,
  FileText,
  Focus,
  Orbit,
  Printer,
  Search,
  ShieldCheck,
} from "lucide-react";
import { clock, label, loadEvidence, query, request } from "../api";
import { EvidenceLink, SectionLabel, Status } from "../components";
import type { EvidenceDetail, Scene, SceneProps } from "../types";
import { EmptyField, SceneLoading } from "../Presentation";

export default function Supporting(props: SceneProps & { scene: Scene }) {
  const { data, scene, onScene, onEvidence, loading } = props;
  const [selected, setSelected] = useState(data.sources[0]?.source_id ?? ""),
    [detail, setDetail] = useState<EvidenceDetail | null>(null),
    [q, setQ] = useState(""),
    [found, setFound] = useState<string[] | null>(null),
    [searching, setSearching] = useState(false),
    [error, setError] = useState(""),
    [lens, setLens] = useState(true),
    [format, setFormat] = useState("all");
  useEffect(() => {
    setSelected(data.sources[0]?.source_id ?? "");
    setFound(null);
    setQ("");
  }, [data.case_id, data.mode]);
  useEffect(() => {
    if (scene !== "desk" || !selected) return;
    const c = new AbortController();
    setDetail(null);
    setError("");
    loadEvidence(selected, data.case_id, data.mode, c.signal)
      .then(setDetail)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [scene, selected, data.case_id, data.mode]);
  async function search() {
    setSearching(true);
    setError("");
    try {
      setFound(
        await request<string[]>(
          `/api/cases/${encodeURIComponent(data.case_id)}/search?${new URLSearchParams({ q, mode: data.mode })}`,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSearching(false);
    }
  }
  if (scene === "portal")
    return (
      <section className="portal-scene">
        <div className="portal-overline">
          <span className="eyebrow">A NEW PERSPECTIVE ON DIGITAL EVIDENCE</span>
          <span className="edition">VOL. 01 / THE INVESTIGATION ARCHIVE</span>
        </div>
        <div className="portal-composition">
          <div className="portal-copy">
            <span className="portal-pretitle">
              THE ABSENCE OF DATA
              <br />
              IS SOMETHING YOU PROVE.
            </span>
            <h1>
              Gone.
              <br />
              <em>
                Or just
                <br />
                out of sight?
              </em>
            </h1>
            <p>
              Follow identities through systems and time.
              <br />
              Turn a deletion claim into a traceable conclusion.
            </p>
            <button
              className="primary-button"
              onClick={() => onScene("identity")}
            >
              Enter the investigation <ArrowUpRight size={18} />
            </button>
            <button
              className="portal-secondary"
              onClick={() => onScene("sources")}
            >
              Explore the source archive <ArrowRight size={14} />
            </button>
            <button
              className="portal-secondary"
              onClick={() => onScene("console")}
            >
              Open the intelligence console <ArrowRight size={14} />
            </button>
          </div>
          <div className="portal-orbit" aria-label="Source relationships">
            <svg viewBox="0 0 650 650">
              <defs>
                <radialGradient id="portalLight">
                  <stop stopColor="#a58aff" stopOpacity=".09" />
                  <stop offset="1" stopColor="#a58aff" stopOpacity="0" />
                </radialGradient>
              </defs>
              <circle cx="325" cy="325" r="300" fill="url(#portalLight)" />
              <g className="orbit-rings">
                <ellipse
                  cx="325"
                  cy="325"
                  rx="275"
                  ry="108"
                  transform="rotate(-35 325 325)"
                />
                <ellipse
                  cx="325"
                  cy="325"
                  rx="260"
                  ry="140"
                  transform="rotate(40 325 325)"
                />
                <ellipse
                  cx="325"
                  cy="325"
                  rx="207"
                  ry="240"
                  transform="rotate(20 325 325)"
                />
                <circle cx="325" cy="325" r="170" />
              </g>
              <path d="M100 325H550M325 100V550" className="orbital-axis" />
              <circle cx="325" cy="325" r="71" className="portal-core" />
              <path
                d="M302 353 325 304 348 353M311 337h28"
                className="portal-symbol"
              />
              <circle cx="325" cy="325" r="85" className="orbit-core-line" />
              {[
                [148, 160],
                [510, 257],
                [202, 487],
                [430, 475],
                [74, 340],
                [477, 117],
              ].map((p, i) => (
                <g key={i}>
                  <circle
                    cx={p[0]}
                    cy={p[1]}
                    r={i === 0 ? 7 : 4}
                    className={i === 0 ? "orbit-point active" : "orbit-point"}
                  />
                  <text x={p[0] + 14} y={p[1] + 4} className="orbit-label">
                    {
                      [
                        "IDENTITY",
                        "SEARCH REPLICA",
                        "EVIDENCE",
                        "POLICY",
                        "PRIMARY",
                        "AUDIT TIME",
                      ][i]
                    }
                  </text>
                </g>
              ))}
              <text
                x="325"
                y="426"
                textAnchor="middle"
                className="orbital-subject"
              >
                {data.context.subject_id ?? "SUBJECT UNRESOLVED"}
              </text>
              <text x="505" y="595" className="svg-coordinate">
                X 024 / Y 108
              </text>
            </svg>
            <button
              className="orbital-callout"
              onClick={() => onScene("timeline")}
            >
              <span className="callout-dot" />
              <span>
                THE CLAIM: {data.request.reported_status.replaceAll("_", " ")}
                <small>What does the evidence say?</small>
              </span>
              <ArrowUpRight size={17} />
            </button>
            <span className="orbit-annotation">
              A PERSON IS MORE
              <br />
              THAN ONE IDENTIFIER.
            </span>
          </div>
        </div>
        <div className="portal-bottom">
          <div className="portal-stats">
            <div>
              <strong>{String(data.sources.length).padStart(2, "0")}</strong>
              <span>SOURCE ARTIFACTS</span>
            </div>
            <div>
              <strong>
                {String(data.events.filter((e) => e.eligible).length).padStart(
                  2,
                  "0",
                )}
              </strong>
              <span>ELIGIBLE OBSERVATIONS</span>
            </div>
            <div>
              <strong>
                {String(
                  new Set(data.events.map((e) => e.system)).size,
                ).padStart(2, "0")}
              </strong>
              <span>CONNECTED SYSTEMS</span>
            </div>
          </div>
          <p>
            <Asterisk size={16} />
            {data.mode === "demo"
              ? "Fictional evidence. Real engine. Inspect every source."
              : "Local evidence. Deterministic decisions. Full provenance."}
          </p>
        </div>
      </section>
    );
  if (scene === "sources") {
    const formats = [...new Set(data.sources.map((s) => s.kind))];
    return (
      <section className="sources-scene">
        <div className="scene-heading">
          <div>
            <SectionLabel number="02">THE SOURCE NEBULA</SectionLabel>
            <h1>
              Fragments become
              <br />
              <em>an investigation.</em>
            </h1>
          </div>
          <p className="heading-aside">
            Every format. Every failure.
            <br />
            Every piece accounted for.
            <span>PROCESSING STATES COME FROM INGESTION.</span>
          </p>
        </div>
        <div className="source-nebula">
          <div className="nebula-core">
            <Orbit size={47} />
            <strong>{data.sources.length}</strong>
            <span>INGESTED SOURCES</span>
            <small>
              {data.sources.filter((s) => s.parse_status === "parsed").length}{" "}
              parsed ·{" "}
              {data.sources.filter((s) => s.parse_status !== "parsed").length}{" "}
              need review
            </small>
          </div>
          <svg viewBox="0 0 1000 440" className="nebula-lines">
            <ellipse cx="500" cy="220" rx="360" ry="155" />
            <ellipse cx="500" cy="220" rx="270" ry="100" />
            {data.sources.map((_, i) => {
              const angle = (i * 2 * Math.PI) / data.sources.length;
              return (
                <line
                  key={i}
                  x1="500"
                  y1="220"
                  x2={500 + 350 * Math.cos(angle)}
                  y2={220 + 150 * Math.sin(angle)}
                />
              );
            })}
          </svg>
          {data.sources.map((s, i) => {
            const angle = (i * 2 * Math.PI) / data.sources.length;
            return (
              <button
                className="source-satellite"
                data-format={s.kind}
                key={s.source_id}
                style={{
                  left: `${50 + 35 * Math.cos(angle)}%`,
                  top: `${50 + 34 * Math.sin(angle)}%`,
                }}
                onClick={() => onEvidence(s.source_id)}
              >
                <span className="specimen-symbol" aria-hidden="true">
                  {s.kind === "json"
                    ? "{ }"
                    : s.kind === "sql"
                      ? "≡"
                      : s.kind === "image"
                        ? "◩"
                        : s.kind === "log"
                          ? "⌁"
                          : "¶"}
                </span>
                <b>{s.kind.toUpperCase()}</b>
                <small>{s.source_id}</small>
                <span
                  className={
                    s.parse_status === "parsed" ? "lime-text" : "coral-text"
                  }
                >
                  {s.parse_status.toUpperCase()}
                </span>
              </button>
            );
          })}
        </div>
        <div className="source-manifest">
          {!data.sources.length && (
            <EmptyField title="The archive is waiting.">
              No source artifacts are available in this case. Load participant
              sources before interpreting an empty register as absence.
            </EmptyField>
          )}
          <div className="manifest-title">
            <span className="eyebrow">THE SOURCE REGISTER</span>
            <select
              aria-label="Filter source formats"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="all">All formats</option>
              {formats.map((f) => (
                <option key={f} value={f}>
                  {f.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
          {data.sources
            .filter((s) => format === "all" || s.kind === format)
            .map((s) => (
              <button
                className="manifest-row"
                key={s.source_id}
                onClick={() => onEvidence(s.source_id)}
              >
                <span className="file-type">{s.kind.toUpperCase()}</span>
                <span>
                  {s.source_id}
                  <small>{s.origin}</small>
                </span>
                <span className="mono">{clock(s.captured_at)} UTC</span>
                <Status value={s.parse_status} />
                <ArrowUpRight size={16} />
              </button>
            ))}
        </div>
      </section>
    );
  }
  if (scene === "desk")
    return (
      <section className="desk-scene">
        <div className="scene-heading compact">
          <div>
            <SectionLabel number="04">THE FORENSIC DESK</SectionLabel>
            <h1>
              Go back to <em>the source.</em>
            </h1>
          </div>
          <span className="heading-aside">
            Search results are leads.
            <br />
            Inspection establishes the facts.
          </span>
        </div>
        <form
          className="forensic-search"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <Search size={19} />
          <input
            aria-label="Search evidence with FTS5"
            placeholder="Search an identifier, resource, or phrase…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span>SQLITE FTS5</span>
          <button className="outline-button" disabled={searching} type="submit">
            {searching ? "Searching…" : "Find traces"}
            <ArrowRight size={14} />
          </button>
        </form>
        {error && (
          <p className="error-message" role="alert">
            {error}
          </p>
        )}
        <div className="forensic-layout">
          <aside className="source-explorer">
            <div className="inspector-kicker">
              SOURCE EXPLORER{" "}
              <span>{found?.length ?? data.sources.length}</span>
            </div>
            {data.sources
              .filter((s) => found === null || found.includes(s.source_id))
              .map((s) => (
                <button
                  className={selected === s.source_id ? "active" : ""}
                  key={s.source_id}
                  onClick={() => setSelected(s.source_id)}
                >
                  <FileText size={16} />
                  <span>
                    {s.source_id}
                    <small>{s.origin}</small>
                  </span>
                </button>
              ))}
            {found?.length === 0 && (
              <EmptyField compact title="No text matches.">
                Try another identifier or phrase. An empty search does not prove
                absence.
              </EmptyField>
            )}
          </aside>
          <div className="desk-document">
            <div className="document-toolbar">
              <span>{selected} / SOURCE VIEW</span>
              <button
                className={lens ? "lens-button active" : "lens-button"}
                onClick={() => setLens((v) => !v)}
              >
                <Focus size={14} />
                Trace lens {lens ? "on" : "off"}
              </button>
            </div>
            {detail ? (
              <>
                <div className="document-paper">
                  <div className="paper-heading">
                    <span>AFTERTRACE / EVIDENCE EXTRACT</span>
                    <span>{detail.format}</span>
                  </div>
                  <h3>{detail.locator.split("/").pop()}</h3>
                  <div className="paper-meta">
                    Captured {clock(detail.captured_at)} UTC{" "}
                    <span>01 / 01</span>
                  </div>
                  <pre>
                    {detail.content.split("\n").map((line, i) => (
                      <span
                        className={
                          lens && /"state"|"resource_id"/.test(line)
                            ? "source-highlight"
                            : ""
                        }
                        key={i}
                      >
                        <i>{String(i + 1).padStart(2, "0")}</i>
                        {line}
                        {"\n"}
                      </span>
                    ))}
                  </pre>
                  <div className="paper-stamp">
                    <ShieldCheck size={20} />
                    <span>
                      ORIGINAL CONTENT
                      <br />
                      <small>Highlights are view annotations.</small>
                    </span>
                  </div>
                </div>
                <div className="document-bottom">
                  <span>
                    SHA-256 / {detail.sha256?.slice(0, 24) ?? "Unavailable"}…
                  </span>
                  <button
                    className="text-link"
                    onClick={() => onEvidence(selected)}
                  >
                    Inspect provenance
                    <ArrowUpRight size={14} />
                  </button>
                </div>
              </>
            ) : !selected || error ? (
              <EmptyField
                title={
                  error
                    ? "The source could not be opened."
                    : "Choose a source to begin."
                }
              >
                {error
                  ? "Select another artifact or retry the request. The source has not been replaced with a guessed extract."
                  : "Original content and provenance will appear here when a source is available."}
              </EmptyField>
            ) : (
              <SceneLoading source />
            )}
          </div>
          <aside className="desk-provenance">
            <span className="small-label">CHAIN OF PROVENANCE</span>
            <h3>
              A fact, with
              <br />
              <em>its footing.</em>
            </h3>
            <ol>
              <li>
                <span>01</span>
                <b>Source artifact</b>
                <small>{selected}</small>
              </li>
              <li>
                <span>02</span>
                <b>Capture time</b>
                <small>
                  {detail ? clock(detail.captured_at) + " UTC" : "Loading…"}
                </small>
              </li>
              <li>
                <span>03</span>
                <b>Audit eligibility</b>
                <small>
                  {detail
                    ? Date.parse(detail.captured_at) <=
                      Date.parse(data.request.audit_at)
                      ? "Before the audit boundary"
                      : "Beyond the audit boundary"
                    : "Not evaluated"}
                </small>
              </li>
            </ol>
            <p className="fine-print">
              Direct inspection preserves the distinction between an observation
              and an inference.
            </p>
          </aside>
        </div>
      </section>
    );
  if (scene === "folio")
    return (
      <section className="folio-scene">
        <div className="folio-actions">
          <SectionLabel number="07">THE AUDIT FOLIO</SectionLabel>
          <div>
            <button className="outline-button" onClick={() => window.print()}>
              <Printer size={14} />
              Print folio
            </button>
            {data.answer.ready_for_export && !loading ? (
              <a
                className="primary-button"
                href={`/api/cases/${encodeURIComponent(data.case_id)}/export?${query(data.mode, data.request.audit_at)}`}
              >
                <Download size={14} />
                Export case CSV
              </a>
            ) : (
              <button className="outline-button" disabled>
                Export blocked
              </button>
            )}
          </div>
        </div>
        <article className="audit-paper">
          <header>
            <div className="paper-wordmark">
              AFTERTRACE<span>INVESTIGATION RECORD</span>
            </div>
            <span className="folio-ref">
              {data.case_id.toUpperCase()}
              <br />
              {data.fingerprint}
            </span>
          </header>
          <div className="folio-title">
            <span className="small-label">EVIDENCE-BASED DELETION AUDIT</span>
            <h1>
              The record
              <br />
              of <em>what remains.</em>
            </h1>
            <div className="folio-decision">
              <Status value={data.answer.deletion_status ?? "UNVERIFIED"} />
              <span>
                AS OF{" "}
                {new Date(data.request.audit_at)
                  .toISOString()
                  .replace("T", " ")
                  .slice(0, 16)}{" "}
                UTC
              </span>
            </div>
          </div>
          <p className="folio-intro">{data.request.request_text}</p>
          <div className="folio-facts">
            <div>
              <span>SUBJECT</span>
              <strong>{data.name}</strong>
              <small>{data.context.subject_id ?? "Not resolved"}</small>
            </div>
            <div>
              <span>REQUEST IDENTITY</span>
              <strong>{data.request.email}</strong>
            </div>
            <div>
              <span>EVIDENCE BASIS</span>
              <strong>
                {data.context.eligible_observation_ids.length} observations
              </strong>
              <small>
                {data.context.excluded_future_observation_ids.length} later
                observations excluded
              </small>
            </div>
          </div>
          {data.mode === "demo" && (
            <p className="demo-paper-notice">
              FICTIONAL DEMONSTRATION · Engine results are computed from the
              demonstration evidence.
            </p>
          )}
          {data.answer.blocking_issues.length > 0 && (
            <div className="folio-blockers">
              <h3>Outstanding requirements</h3>
              {data.answer.blocking_issues.map((b) => (
                <p key={b}>{b}</p>
              ))}
            </div>
          )}
          {["FINDING", "REMEDIATION", "VERIFICATION"].map((phase) => {
            const steps = data.answer.steps.filter((s) => s.phase === phase);
            return (
              steps.length > 0 && (
                <section className="folio-section" key={phase}>
                  <h2>
                    {phase === "FINDING"
                      ? "01 / Observed findings"
                      : phase === "REMEDIATION"
                        ? "02 / Required remediation"
                        : "03 / Verification record"}
                  </h2>
                  {steps.map((step) => (
                    <div className="folio-step" key={step.step_no}>
                      <span className="step-number">
                        {String(step.step_no).padStart(2, "0")}
                      </span>
                      <div>
                        <b>{label(step.operation)}</b>
                        <p>
                          {step.system_id} / {step.resource_id}
                        </p>
                        <small>
                          {step.evidence_id
                            ? "Established by source evidence"
                            : "Proposed future work · not executed"}
                        </small>
                      </div>
                      {step.evidence_id ? (
                        <EvidenceLink
                          id={step.evidence_id}
                          onOpen={onEvidence}
                        />
                      ) : (
                        <span className="planned-label">PLANNED</span>
                      )}
                    </div>
                  ))}
                </section>
              )
            );
          })}
          <div className="folio-policy">
            <span className="small-label">APPLICABLE POLICY</span>
            {data.context.policy_rules.map((p) => (
              <p key={p.rule_id}>
                <b>{p.rule_id}</b> {p.category} → {p.required_action}
              </p>
            ))}
          </div>
          <footer>
            <span>Every action leaves a trace.</span>
            <p>
              Prepared by the deterministic SLAM engine. This is an audit of
              supplied evidence; recommendations do not modify external systems.
            </p>
          </footer>
        </article>
      </section>
    );
  return (
    <section className="observatory-scene">
      <div className="scene-heading">
        <div>
          <SectionLabel number="08">THE EXPERIMENT OBSERVATORY</SectionLabel>
          <h1>
            Progress needs
            <br />
            <em>its own proof.</em>
          </h1>
        </div>
        <p className="heading-aside">
          Measure the difference.
          <br />
          Keep the uncertainty.<span>NO EVALUATION RUN HAS BEEN IMPORTED.</span>
        </p>
      </div>
      <div className="experiment-track">
        {[
          "BASELINE",
          "CHANGE",
          "REGRESSION",
          "COMPARISON",
          "ACCEPT / REJECT",
        ].map((s, i) => (
          <div key={s}>
            <span>0{i + 1}</span>
            <b>{s}</b>
            {i < 4 && <ArrowRight size={16} />}
          </div>
        ))}
      </div>
      <div className="observatory-layout">
        <div>
          <div className="inspector-kicker">
            ENGINE EVALUATION <span>NOT MEASURED</span>
          </div>
          <div className="observatory-empty">
            <span className="small-label">EVALUATION / NO IMPORTED RUN</span>
            <h3>
              A baseline is
              <br />
              <em>where proof begins.</em>
            </h3>
            <p>
              Comparison metrics will appear with a versioned evaluation report.
              Current corpus diagnostics remain available.
            </p>
          </div>
          <div className="metric-ledger">
            {[
              "Case status accuracy",
              "Full-case exact match",
              "Precision / recall / F1",
              "False COMPLETE count",
              "Invalid citation count",
              "Runtime / inference usage",
            ].map((metric) => (
              <div key={metric}>
                <span>{metric}</span>
                <strong>—</strong>
                <small>Awaiting an evaluation report</small>
              </div>
            ))}
          </div>
          <p className="fine-print">
            An audit result is not an accuracy measurement. Metrics appear only
            when accompanied by an evaluated fixture set and its denominators.
          </p>
        </div>
        <aside className="quality-ledger">
          <span className="small-label">CURRENT CORPUS DIAGNOSTICS</span>
          <h3>
            What we can
            <br />
            <em>measure now.</em>
          </h3>
          <dl className="check-ledger">
            <dt>Manifest sources</dt>
            <dd>{data.quality.expected_sources}</dd>
            <dt>Successfully parsed</dt>
            <dd>{data.quality.parsed_sources}</dd>
            <dt>Observations</dt>
            <dd>{data.quality.observations}</dd>
            <dt>Conflicting groups</dt>
            <dd>{data.quality.conflicting_observation_groups}</dd>
          </dl>
          {data.quality.issues.length ? (
            data.quality.issues.map((issue) => (
              <div className="quality-issue" key={issue.code + issue.message}>
                <span className="coral-text">{issue.code}</span>
                <p>{issue.message}</p>
              </div>
            ))
          ) : (
            <p className="quality-clean">
              <Check size={15} />
              No issues detected by the current checks.
            </p>
          )}
          <button
            className="outline-button"
            onClick={() => {
              const url = URL.createObjectURL(
                new Blob(
                  [
                    JSON.stringify(
                      {
                        mode: data.mode,
                        case_id: data.case_id,
                        quality: data.quality,
                      },
                      null,
                      2,
                    ),
                  ],
                  { type: "application/json" },
                ),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = "aftertrace-diagnostics.json";
              link.click();
              URL.revokeObjectURL(url);
            }}
          >
            <Download size={14} />
            Download diagnostics
          </button>
        </aside>
      </div>
    </section>
  );
}
