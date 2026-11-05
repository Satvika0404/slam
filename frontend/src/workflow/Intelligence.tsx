import { useState } from "react";
import { Activity, Check, Network, Play, ShieldCheck } from "lucide-react";
import type { Sandbox } from "./types";

export interface IntelligenceData {
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
export default function Intelligence({
  data,
  sandbox,
  requestEmail,
  resourceId,
}: {
  data?: IntelligenceData;
  sandbox: Sandbox | null;
  requestEmail: string;
  resourceId?: string;
}) {
  const [tab, setTab] = useState("patterns"),
    [error, setError] = useState("");
  const [csv, setCsv] = useState(
    `Email Address,Record ID\n${JSON.stringify(requestEmail)},${JSON.stringify(resourceId ?? "")}\n`,
  );
  const [result, setResult] = useState<Record<string, any> | null>(null),
    [sync, setSync] = useState<Record<string, any> | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const deletes =
    sandbox?.actions.filter(
      (a) => a.operation === "DELETE_RECORD" && a.status === "verified",
    ) ?? [];
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
        {["patterns", "self-healing", "sync experiment"].map((t) => (
          <button
            className={tab === t ? "active" : ""}
            key={t}
            onClick={() => setTab(t)}
          >
            {t === "patterns" ? (
              <Network size={14} />
            ) : t === "self-healing" ? (
              <Activity size={14} />
            ) : (
              <ShieldCheck size={14} />
            )}{" "}
            {t}
          </button>
        ))}
      </nav>
      {error && <p role="alert">{error}</p>}
      {tab === "patterns" ? (
        <>
          <h3>{data?.model ?? "Timing attribution"}</h3>
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
      ) : tab === "self-healing" ? (
        <>
          <h3>Watch a component recover</h3>
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
