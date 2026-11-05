import { useState } from "react";
import {
  Activity,
  BrainCircuit,
  Check,
  Network,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { Sandbox } from "./types";

export interface IntelligenceData {
  attributions?: Record<
    string,
    { linked: Attribution[]; candidates: Attribution[] }
  >;
  recoveries?: {
    component: string;
    status: string;
    adapter_version: string;
    missing_before: string[];
    checks: string;
    attempts: { outcome: string; elapsed_ms: number }[];
  }[];
  model: string;
  learning: string;
  groups: {
    key: string[];
    window: number[];
    pairs: number;
    resolved: number;
  }[];
  quality: {
    findings?: {
      code: string;
      kind: string;
      message?: string;
      explanation?: string;
    }[];
    issues: { code: string; message: string }[];
    impact?: {
      directly_affected_cases: string[];
      potentially_reachable_resources: string[];
      unknowns: string[];
    };
  };
}
interface Attribution {
  resource_id: string;
  system_id: string;
  group: string[];
  activity_ids: string[];
  known_owners: string[];
}
interface CohortInsights {
  available: boolean;
  reason?: string;
  audited_cases?: number;
  cases?: { case_id: string; failure_risk: number | null }[];
  failed?: number;
  scope: string;
  model?: {
    algorithm: string;
    folds: number;
    metrics: Record<string, number>;
    baselines: Record<string, Record<string, number>>;
    importance: { feature: string; share: number }[];
  };
  patterns?: {
    pattern_id: string;
    label: string;
    size: number;
    mean_p_failure: number | null;
  }[];
  novel_cases?: string[];
  recreation_paths?: Record<string, string[][]>;
}
export default function Intelligence({
  data,
  sandbox,
  runId,
  requestEmail,
  resourceId,
  caseId,
  onEvidence,
}: {
  data?: IntelligenceData;
  sandbox: Sandbox | null;
  runId: string;
  requestEmail: string;
  resourceId?: string;
  caseId: string;
  onEvidence: (id: string) => void;
}) {
  const [tab, setTab] = useState("overview"),
    [error, setError] = useState("");
  const [csv, setCsv] = useState(
    `Email Address,Record ID\n${JSON.stringify(requestEmail)},${JSON.stringify(resourceId ?? "")}\n`,
  );
  const [result, setResult] = useState<Record<string, any> | null>(null),
    [sync, setSync] = useState<Record<string, any> | null>(null);
  const [cohort, setCohort] = useState<CohortInsights | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const deletes =
    sandbox?.actions.filter(
      (a) => a.operation === "DELETE_RECORD" && a.status === "verified",
    ) ?? [];
  const attribution = data?.attributions?.[caseId];
  const recoveries = data?.recoveries ?? [];
  const recoveredCount = recoveries.filter(
    (item) => item.status === "recovered",
  ).length;
  const unresolvedCount = recoveries.filter(
    (item) => item.status !== "recovered",
  ).length;
  const learnedPairs =
    data?.groups.reduce((total, group) => total + group.pairs, 0) ?? 0;
  async function loadCohort() {
    if (cohort) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workflow/runs/${runId}/insights`);
      const value = await response.json();
      if (!response.ok) throw Error(value.detail);
      setCohort(value);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function call(url: string, body: unknown, save: (r: any) => void) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw Error(value.detail);
      save(value);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="wf-intelligence">
      <nav aria-label="Agent intelligence">
        {[
          "overview",
          "pattern recognition",
          "cohort intelligence",
          "self-healing agent",
          "sync experiment",
        ].map((t) => (
          <button
            className={tab === t ? "active" : ""}
            key={t}
            onClick={() => {
              setTab(t);
              if (t === "cohort intelligence") void loadCohort();
            }}
          >
            {t === "overview" ? (
              <Sparkles size={14} />
            ) : t === "pattern recognition" ? (
              <Network size={14} />
            ) : t === "cohort intelligence" ? (
              <BrainCircuit size={14} />
            ) : t === "self-healing agent" ? (
              <RefreshCw size={14} />
            ) : (
              <ShieldCheck size={14} />
            )}{" "}
            {t}
          </button>
        ))}
      </nav>
      {error && <p role="alert">{error}</p>}
      {tab === "overview" ? (
        <>
          <header className="wf-agent-overview-heading">
            <div>
              <span className="wf-kicker">Adaptive audit intelligence</span>
              <h3>See what the agent learned and repaired in this run</h3>
            </div>
            <span className="wf-run-boundary">RUN-SCOPED · EVIDENCE-BOUND</span>
          </header>
          <div className="wf-agent-feature-grid">
            <article
              className={`wf-agent-feature healing ${unresolvedCount ? "warning" : recoveredCount ? "active" : "quiet"}`}
              data-feature="self-healing"
            >
              <div className="wf-agent-feature-title">
                <span>
                  <RefreshCw size={18} />
                </span>
                <div>
                  <small>FEATURE 01</small>
                  <h4>Self-Healing Agent</h4>
                </div>
              </div>
              <p>
                Detects an allowlisted parser failure, applies one bounded
                recovery rule to a copy, retries, and independently validates
                the result.
              </p>
              <div className="wf-agent-flow" aria-label="Self-healing stages">
                {["Detect", "Recover", "Retry", "Validate"].map(
                  (step, index) => (
                    <span
                      className={recoveries.length ? "complete" : "standby"}
                      key={step}
                    >
                      <b>{index + 1}</b>
                      {step}
                    </span>
                  ),
                )}
              </div>
              <strong className="wf-agent-feature-result">
                {unresolvedCount
                  ? `${unresolvedCount} component remains unresolved`
                  : recoveredCount
                    ? `${recoveredCount} component recovered and validated`
                    : "No repair was required in this audit"}
              </strong>
              <button
                className="wf-feature-open"
                onClick={() => setTab("self-healing agent")}
              >
                Inspect healing evidence <span>→</span>
              </button>
            </article>
            <article
              className={`wf-agent-feature patterns ${data?.groups.length ? "active" : "quiet"}`}
              data-feature="pattern-recognition"
            >
              <div className="wf-agent-feature-title">
                <span>
                  <BrainCircuit size={18} />
                </span>
                <div>
                  <small>FEATURE 02</small>
                  <h4>Pattern Recognition Engine</h4>
                </div>
              </div>
              <p>
                Learns timing signatures only from known-owner evidence,
                validates them out of sample, and abstains when a link is not
                unique.
              </p>
              <div className="wf-pattern-summary">
                <span>
                  <b>{data?.groups.length ?? 0}</b> validated models
                </span>
                <span>
                  <b>{learnedPairs}</b> grounded pairs
                </span>
                <span>
                  <b>{attribution?.linked.length ?? 0}</b> case links
                </span>
                <span>
                  <b>{attribution?.candidates.length ?? 0}</b> abstained
                </span>
              </div>
              <strong className="wf-agent-feature-result">
                {data?.groups.length
                  ? "Validated patterns are active for this run"
                  : "No pattern passed the validation threshold"}
              </strong>
              <button
                className="wf-feature-open"
                onClick={() => setTab("pattern recognition")}
              >
                Inspect learned patterns <span>→</span>
              </button>
            </article>
          </div>
          <p className="wf-agent-truth-note">
            These features never rewrite source evidence or promote their own
            code. Recovery is allowlisted and validated; learned links remain
            candidates unless the evidence uniquely supports them.
          </p>
        </>
      ) : tab === "pattern recognition" ? (
        <>
          <div className="wf-feature-detail-heading">
            <div>
              <span className="wf-kicker">FEATURE 02 · LIVE MODEL</span>
              <h3>Pattern Recognition Engine</h3>
            </div>
            <span className="wf-truth-badge">VALIDATED OR ABSTAINED</span>
          </div>
          <p>
            {data?.learning ?? "Awaiting run measurements"}. The validated
            windows below come from known-owner pairs.
          </p>
          <div className="wf-pattern-grid">
            {data?.groups.map((g) => (
              <article key={g.key.join(":")}>
                <span>{g.key[0]}</span>
                <strong>{g.key[1]}</strong>
                <div className="wf-pattern-window">
                  <i style={{ width: `${g.resolved * 100}%` }} />
                </div>
                <small>
                  {g.window[0].toFixed(1)} to {g.window[1].toFixed(1)} minutes ·{" "}
                  {g.pairs} grounded pairs
                </small>
                <b>
                  {Math.round(g.resolved * 100)}% resolved on held-out
                  validation
                </b>
              </article>
            ))}
          </div>
          {!data?.groups.length && (
            <p>
              No timing group met the validation threshold in this input.
              Explicit identity evidence remains available.
            </p>
          )}
          <details>
            <summary>
              Why this case was linked — candidates and evidence
            </summary>
            {[
              ...(attribution?.linked ?? []).map((a) => ({
                ...a,
                status: "Corroborated timing attribution",
              })),
              ...(attribution?.candidates ?? []).map((a) => ({
                ...a,
                status: "Candidate — abstained",
              })),
            ].map((a, i) => (
              <article className="wf-attribution" key={i}>
                <strong>{a.status}</strong>
                <code>
                  {a.system_id}/{a.resource_id}
                </code>
                <p>
                  {a.group.join(" · ")} · known owners:{" "}
                  {a.known_owners.join(", ") ||
                    "not established by explicit ownership"}
                </p>
                {a.activity_ids.map((id) => (
                  <button key={id} onClick={() => onEvidence(id)}>
                    {id} ↗
                  </button>
                ))}
              </article>
            ))}
            {!attribution?.linked.length && !attribution?.candidates.length && (
              <p>
                No timing attribution was made for this case. Inspect its
                explicit identity/resource evidence; no candidate ownership is
                invented.
              </p>
            )}
          </details>
          <details>
            <summary>Input diagnostics and conflicts</summary>
            {data?.quality.issues.map((issue, i) => (
              <p key={i}>
                <code>{issue.code}</code> {issue.message}
              </p>
            ))}
            {data?.quality.findings?.map((finding, i) => (
              <p key={`finding-${i}`}>
                <code>{finding.code ?? finding.kind}</code>{" "}
                {finding.message ?? finding.explanation}
              </p>
            ))}
            {data?.quality.impact && (
              <p>
                {data.quality.impact.directly_affected_cases.length} directly
                affected cases ·{" "}
                {data.quality.impact.potentially_reachable_resources.length}{" "}
                potentially reachable resources. Reachability is a scope
                estimate, not a probability of error.
              </p>
            )}
            {!data?.quality.issues.length &&
              !data?.quality.findings?.length && (
                <p>
                  No configured diagnostic rules found an issue. This does not
                  prove complete coverage.
                </p>
              )}
          </details>
        </>
      ) : tab === "cohort intelligence" ? (
        <>
          <div className="wf-cohort-heading">
            <div>
              <span className="wf-kicker">Cross-request intelligence</span>
              <h3>Recurring failures and recreation paths</h3>
            </div>
            <span className="wf-truth-badge">TRIAGE · NOT A VERDICT</span>
          </div>
          {busy && !cohort ? (
            <p role="status">Scoring audited cases and discovering patterns…</p>
          ) : cohort && !cohort.available ? (
            <article className="wf-cohort-unavailable">
              <strong>Not enough evidence for honest model scoring</strong>
              <p>{cohort.reason}</p>
              <small>
                {cohort.audited_cases} audited cases · {cohort.failed ?? 0}
                failed. The audit and its deterministic evidence remain fully
                available.
              </small>
            </article>
          ) : cohort?.model ? (
            <>
              <div className="wf-cohort-metrics">
                {[
                  ["AUC", cohort.model.metrics.auc],
                  ["Accuracy", cohort.model.metrics.accuracy],
                  ["Recall", cohort.model.metrics.recall],
                  ["Brier", cohort.model.metrics.brier],
                ].map(([label, value]) => (
                  <article key={String(label)}>
                    <span>{label}</span>
                    <strong>{Number(value).toFixed(3)}</strong>
                    <small>{cohort.model!.folds}-fold out-of-fold</small>
                  </article>
                ))}
              </div>
              <div className="wf-cohort-columns">
                <section>
                  <h4>Discovered failure signatures</h4>
                  {cohort.patterns?.map((pattern) => (
                    <article
                      className="wf-cohort-pattern"
                      key={pattern.pattern_id}
                    >
                      <b>{pattern.pattern_id}</b>
                      <span>{pattern.label}</span>
                      <small>
                        {pattern.size} cases
                        {pattern.mean_p_failure == null
                          ? ""
                          : ` · ${Math.round(pattern.mean_p_failure * 100)}% mean risk`}
                      </small>
                    </article>
                  ))}
                </section>
                <section>
                  <h4>Active paths that could recreate data</h4>
                  {Object.entries(cohort.recreation_paths ?? {}).flatMap(
                    ([target, paths]) =>
                      paths.map((path, index) => (
                        <article
                          className="wf-recreation-path"
                          key={`${target}-${index}`}
                        >
                          {path.map((node, nodeIndex) => (
                            <span key={`${node}-${nodeIndex}`}>
                              {node}
                              {nodeIndex < path.length - 1 && <i>→</i>}
                            </span>
                          ))}
                        </article>
                      )),
                  )}
                  {!Object.values(cohort.recreation_paths ?? {}).some(
                    (paths) => paths.length,
                  ) && (
                    <p>No configured active path reaches a failed system.</p>
                  )}
                </section>
              </div>
              <details>
                <summary>Model boundaries and strongest drivers</summary>
                <p>{cohort.scope}.</p>
                <p>
                  {cohort.model.algorithm}. Labels come from this audit’s own
                  verdicts; probabilities prioritize review and cannot certify
                  completion.
                </p>
                {cohort.model.importance.map((item) => (
                  <p key={item.feature}>
                    <code>{item.feature}</code> {Math.round(item.share * 100)}%
                    of model gain
                  </p>
                ))}
              </details>
            </>
          ) : null}
        </>
      ) : tab === "self-healing agent" ? (
        <>
          <div className="wf-feature-detail-heading">
            <div>
              <span className="wf-kicker">FEATURE 01 · GUARDED RECOVERY</span>
              <h3>Self-Healing Agent</h3>
            </div>
            <span className="wf-truth-badge">VALIDATION REQUIRED</span>
          </div>
          {data?.recoveries?.length ? (
            data.recoveries.map((r) => (
              <section
                className={`wf-healing-arm ${r.status}`}
                key={r.component}
                aria-label="Recovery in this audit"
              >
                <span>
                  {r.component}
                  <small>Missing {r.missing_before.join(", ")}</small>
                </span>
                <i />
                <span className="wf-healed-component">
                  <Activity size={16} />
                  {r.status === "recovered"
                    ? "Recovered this run"
                    : "Unresolved"}
                  <small>{r.adapter_version}</small>
                </span>
                <i />
                <span>
                  Validated
                  <small>
                    {r.attempts.length} attempt · {r.checks}
                  </small>
                </span>
              </section>
            ))
          ) : (
            <p>No table-header recovery was needed in this audit.</p>
          )}
          <p>
            Run the bounded header adapter on an input snippet. The result
            records the failure, recovery and independent checks. This snippet
            starts with an identity and resource from this audit; header aliases
            deliberately exercise the adapter without changing the source.
          </p>
          <textarea
            aria-label="Recovery CSV input"
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
          />
          <button
            className="wf-secondary"
            disabled={busy}
            onClick={() =>
              call(
                "/api/workflow/experiments/recovery",
                { csv_text: csv },
                setResult,
              )
            }
          >
            <Play size={14} />
            {busy ? "Validating recovery…" : "Test recovery"}
          </button>
          <div className={`wf-healing-arm ${result?.status ?? "waiting"}`}>
            <span>Source</span>
            <i />
            <span className="wf-healed-component">
              <Activity size={16} />
              {result?.component ?? "CSV adapter"}
              {result?.status === "recovered" && <Check size={15} />}
            </span>
            <i />
            <span>Validation</span>
          </div>
          {result && (
            <div className="wf-recovery-result">
              <strong>
                {result.status === "recovered"
                  ? "Recovered this input"
                  : "Input remains unresolved"}
              </strong>
              <p>
                Missing original fields ·{" "}
                {result.missing_before.join(", ") || "none"}
              </p>
              <p>
                {result.checks_passed}/{result.checks_total} checks ·{" "}
                {result.adapter_version} ·{" "}
                {result.promotion.replaceAll("_", " ")}
              </p>
              <pre>
                {result.validated_payload?.csv ?? "No validated output"}
              </pre>
              <small>
                This experiment records adapter eligibility for review.
                Future-run promotion requires acceptance.
              </small>
            </div>
          )}
        </>
      ) : (
        <>
          <h3>Can a deleted row return?</h3>
          <p>
            Replay the selected imported row through the same sync worker in two
            independent copies. Compare enabled and disabled controls.
          </p>
          <select
            aria-label="Sync experiment row"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Choose a verified deleted row</option>
            {deletes.map((a) => (
              <option key={a.id} value={a.id}>
                {a.system_id}/{a.resource_id}
              </option>
            ))}
          </select>
          <button
            className="wf-secondary"
            disabled={busy || !target}
            onClick={() => {
              const a = deletes.find((a) => a.id === target);
              if (a)
                void call(
                  "/api/workflow/experiments/sync",
                  {
                    sandbox_id: sandbox!.id,
                    system_id: a.system_id,
                    resource_id: a.resource_id,
                  },
                  setSync,
                );
            }}
          >
            <Play size={14} />
            {busy ? "Running worker…" : "Run sync again"}
          </button>
          {sync && (
            <>
              <div className="wf-sync-branches">
                {sync.branches.map((b: any) => (
                  <article
                    key={String(b.sync_enabled)}
                    className={b.recreated ? "recreated" : "protected"}
                  >
                    <span>SYNC {b.sync_enabled ? "ENABLED" : "DISABLED"}</span>
                    <strong>
                      {b.before_rows}
                      <small> → </small>
                      {b.after_rows}
                    </strong>
                    <p>
                      {b.recreated ? "Row recreated" : "Row remains absent"}
                    </p>
                    <small>Measured matching rows after worker execution</small>
                    <small>
                      {b.original_rows} original → {b.before_rows} after
                      deletion → {b.after_rows} after sync. Control set before
                      deletion.
                    </small>
                  </article>
                ))}
              </div>
              <p>
                {sync.resource_id} · {sync.scope}
              </p>
              <code>{sync.sha256}</code>
            </>
          )}
          {!deletes.length && (
            <p>
              Execute a reviewed DELETE action first to make this experiment
              available.
            </p>
          )}
        </>
      )}
    </section>
  );
}
