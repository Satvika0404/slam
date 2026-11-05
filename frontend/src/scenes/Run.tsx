import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Download,
  Play,
  Radio,
  Square,
  X,
} from "lucide-react";
import { request } from "../api";
import type { AuditCase, Mode, SceneProps } from "../types";
import { consumeExecution, executionStages } from "../live";
import type { ExecutionEvent } from "../live";
import Identity from "./Identity";
import SystemGraph from "../console/SystemGraph";
import { fromCase } from "../console/model";
import "../console/console.css";
import "../run.css";

export default function Run({
  mode,
  caseId,
  cutoff,
  onEvidence,
  onScene,
  onResult,
  onOpen,
}: {
  mode: Mode;
  caseId: string;
  cutoff: string | null;
  onEvidence: SceneProps["onEvidence"];
  onScene: SceneProps["onScene"];
  onResult: (view: AuditCase) => void;
  onOpen: (view: AuditCase) => void;
}) {
  const [runtime, setRuntime] = useState<{
      model_available: boolean;
      provider: string;
      model: string | null;
    } | null>(null),
    [scope, setScope] = useState("case"),
    [useModel, setUseModel] = useState(false),
    [callLimit, setCallLimit] = useState(4);
  const [running, setRunning] = useState(false),
    [error, setError] = useState(""),
    [events, setEvents] = useState<ExecutionEvent[]>([]),
    [stage, setStage] = useState("ingestion"),
    [following, setFollowing] = useState(true),
    [snapshots, setSnapshots] = useState<Record<string, AuditCase>>({}),
    [sources, setSources] = useState<
      { source_id: string; parse_status: string; kind: string }[]
    >([]),
    [result, setResult] = useState<ExecutionEvent | null>(null),
    [modelEvents, setModelEvents] = useState<ExecutionEvent[]>([]),
    [latestCase, setLatestCase] = useState("");
  const abort = useRef<AbortController | null>(null),
    followRef = useRef(true),
    resultsRef = useRef(onResult);
  resultsRef.current = onResult;
  useEffect(() => {
    const c = new AbortController();
    request<NonNullable<typeof runtime>>("/api/runtime", c.signal)
      .then(setRuntime)
      .catch(() => setRuntime(null));
    return () => c.abort();
  }, []);
  useEffect(() => () => abort.current?.abort(), []);
  async function start() {
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setError("");
    setEvents([]);
    setSnapshots({});
    setSources([]);
    setResult(null);
    setModelEvents([]);
    setFollowing(true);
    followRef.current = true;
    setStage("ingestion");
    try {
      const response = await fetch("/api/runs/stream", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          case_id: caseId,
          scope,
          cutoff: scope === "case" ? cutoff : null,
          use_model: useModel,
          max_model_calls: callLimit,
        }),
      });
      await consumeExecution(response, (event) => {
        if (event.case_id) setLatestCase(event.case_id);
        if (event.event === "case.started") setSnapshots({});
        if (event.payload.snapshot) {
          const snapshot = event.payload.snapshot;
          setSnapshots((s) => ({
            ...s,
            [event.payload.stage ?? "validation"]: snapshot,
          }));
          if (event.payload.stage === "validation")
            resultsRef.current(snapshot);
        }
        if (event.event === "source.completed") {
          const source = event.payload.source as (typeof sources)[number];
          setSources((old) => [
            ...old.filter((s) => s.source_id !== source.source_id),
            source,
          ]);
        }
        if (event.payload.source_records)
          setSources(event.payload.source_records as typeof sources);
        if (event.event.startsWith("model."))
          setModelEvents((old) => [...old, event]);
        if (event.payload.stage && followRef.current)
          setStage(event.payload.stage);
        if (event.event === "run.completed") setResult(event);
        if (event.event === "run.failed")
          setError(
            String(event.payload.message ?? "Backend execution failed.") +
              (event.payload.error_type
                ? ` (${event.payload.error_type})`
                : ""),
          );
        const { snapshot: _, ...payload } = event.payload;
        setEvents((old) => [...old.slice(-999), { ...event, payload }]);
      });
    } catch (e) {
      setError(
        (e as Error).name === "AbortError"
          ? "Stopped following. Backend cancellation is requested at the next execution checkpoint; an in-flight API call may finish."
          : (e as Error).message,
      );
    } finally {
      setRunning(false);
      abort.current = null;
    }
  }
  const snapshot =
    snapshots[stage] ??
    snapshots.validation ??
    snapshots.graph ??
    snapshots.timeline ??
    snapshots.identity;
  const stageEvents = events.filter((e) => e.payload.stage === stage),
    latest = stageEvents.at(-1);
  const answer = snapshots.validation?.answer;
  const output = result?.payload.output_csv as string | null | undefined;
  function download() {
    if (!output) return;
    const url = URL.createObjectURL(new Blob([output], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = scope === "all" ? "output.csv" : "aftertrace-case.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function select(id: string) {
    setStage(id);
    setFollowing(false);
    followRef.current = false;
  }
  return (
    <section className="live-run">
      <header className="run-heading">
        <div>
          <span className="eyebrow">
            EXECUTION OBSERVATORY / ACTUAL BACKEND EVENTS
          </span>
          <h1>
            Watch the evidence
            <br />
            <em>become an answer.</em>
          </h1>
          <p>
            Every transition follows a server event. Graphs, model usage and
            output come from the functions that actually ran.
          </p>
        </div>
        <span className={`run-connection ${running ? "is-running" : ""}`}>
          <Radio size={16} />
          {running
            ? "LIVE CONNECTION"
            : result
              ? "RECORDED EXECUTION"
              : "READY TO RUN"}
        </span>
      </header>
      <div className="run-controls">
        <label>
          Run scope
          <select
            value={scope}
            disabled={running}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="case">Selected audit · {caseId}</option>
            <option value="all">All requests · original cutoffs</option>
          </select>
        </label>
        <label className="run-model">
          <span>
            <input
              type="checkbox"
              aria-label="Use configured API model"
              checked={useModel}
              disabled={running || !runtime?.model_available}
              onChange={(e) => setUseModel(e.target.checked)}
            />
            Use configured API model
          </span>
          <small>
            {runtime?.model_available
              ? `${runtime.provider} / ${runtime.model}`
              : "No API model configured · deterministic engine available"}
          </small>
        </label>
        {useModel && (
          <label>
            Structured-call limit
            <input
              type="number"
              min="1"
              max="32"
              value={callLimit}
              disabled={running}
              onChange={(e) =>
                setCallLimit(Math.max(1, Math.min(32, +e.target.value)))
              }
            />
          </label>
        )}
        <button className="run-start" disabled={running} onClick={start}>
          <Play size={15} />
          Run backend audit
        </button>
        {running && (
          <button onClick={() => abort.current?.abort()}>
            <Square size={13} />
            Stop following
          </button>
        )}
      </div>
      <div className="run-scope-note">
        {mode === "demo"
          ? "FICTIONAL DEMO INPUTS · REAL ENGINE EXECUTION"
          : "PARTICIPANT DATASET · REAL ENGINE EXECUTION"}{" "}
        · No external identities or records are modified.
      </div>
      {error && (
        <div className="run-error" role="alert">
          <X size={17} />
          {error}
        </div>
      )}
      <div className="run-layout">
        <nav className="run-stages" aria-label="Backend execution phases">
          {executionStages.map((s, i) => {
            const last = events.filter((e) => e.payload.stage === s.id).at(-1),
              state =
                last?.event === "stage.completed"
                  ? "completed"
                  : last?.event === "stage.skipped"
                    ? "skipped"
                    : last?.event === "stage.started"
                      ? "running"
                      : "waiting";
            return (
              <button
                key={s.id}
                onClick={() => select(s.id)}
                aria-current={stage === s.id ? "step" : undefined}
                className={`run-stage ${state}`}
              >
                <span>
                  {state === "completed" ? (
                    <Check size={13} />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <div>
                  <strong>{s.name}</strong>
                  <small>{s.tech}</small>
                  <b>
                    {state.toUpperCase()}
                    {last?.elapsed_ms != null ? ` · +${last.elapsed_ms}ms` : ""}
                  </b>
                </div>
              </button>
            );
          })}
          <button
            className="run-follow"
            aria-pressed={following}
            onClick={() => {
              setFollowing(true);
              followRef.current = true;
              const last = events.filter((e) => e.payload.stage).at(-1);
              if (last?.payload.stage) setStage(last.payload.stage);
            }}
          >
            Follow live phase
          </button>
        </nav>
        <div className="run-stage-content">
          <header>
            <span className="eyebrow">
              {following && running ? "LIVE PHASE" : "INSPECT EXECUTED STAGE"}
            </span>
            <h2>{executionStages.find((s) => s.id === stage)?.name}</h2>
            <p>
              {latest
                ? `${latest.event} · ${latest.at ?? ""} · ${latestCase}`
                : "This stage has not run yet. No output is assumed."}
            </p>
          </header>
          {stage === "identity" && snapshots.identity ? (
            <Identity
              data={snapshots.identity}
              loading={false}
              onEvidence={onEvidence}
              onScene={onScene}
              onCutoff={() =>
                setError(
                  "This is a recorded execution snapshot. Change the audit cutoff in Identity Constellation and start a new run.",
                )
              }
            />
          ) : stage === "graph" && snapshot ? (
            <SystemGraph
              key={`${snapshot.case_id}:${snapshot.fingerprint}`}
              data={fromCase(snapshot)}
              onInspect={onEvidence}
              readOnly
            />
          ) : stage === "ingestion" ? (
            <div className="run-sources">
              {sources.length ? (
                sources.map((s) => (
                  <div key={s.source_id}>
                    <span>{s.kind?.toUpperCase()}</span>
                    <strong>{s.source_id}</strong>
                    <b>{s.parse_status}</b>
                  </div>
                ))
              ) : (
                <p>
                  {running
                    ? "Waiting for actual parser results…"
                    : "Parsed sources appear only after the backend reads them."}
                </p>
              )}
            </div>
          ) : stage === "timeline" && snapshots.timeline ? (
            <div className="run-resource-table">
              <table>
                <thead>
                  <tr>
                    <th>System / resource</th>
                    <th>Reconstructed state</th>
                    <th>Evidence</th>
                    <th>At cutoff</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.timeline.context.resource_states.map((r) => (
                    <tr key={`${r.system_id}:${r.resource_id}`}>
                      <td>
                        {r.system_id}
                        <small>{r.resource_id}</small>
                      </td>
                      <td>
                        {r.state}
                        {r.uncertain ? " · uncertain" : ""}
                      </td>
                      <td>
                        {r.supporting_evidence_ids.map((id) => (
                          <button key={id} onClick={() => onEvidence(id)}>
                            {id}
                          </button>
                        ))}
                      </td>
                      <td>{r.at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>
                {
                  snapshots.timeline.context.excluded_future_observation_ids
                    .length
                }{" "}
                later observations excluded by the real reconstruction.
              </p>
            </div>
          ) : stage === "validation" && answer ? (
            <div className="run-answer">
              <span>
                BACKEND AUDIT RESULT · EXECUTION COMPLETION IS SEPARATE
              </span>
              <h3>{answer.deletion_status ?? "BLOCKED / UNVERIFIED"}</h3>
              <p>
                {answer.ready_for_export
                  ? `${answer.steps.length} validated output steps`
                  : `${answer.blocking_issues.length} blockers prevent export`}
              </p>
              {answer.blocking_issues.map((b, i) => (
                <p className="run-blocker" key={i}>
                  {b}
                </p>
              ))}
              <button onClick={() => onOpen(snapshots.validation)}>
                Open evidence-backed audit folio
                <ArrowUpRight size={15} />
              </button>
              <pre>{JSON.stringify(answer, null, 2)}</pre>
            </div>
          ) : (
            <div className="run-stage-record">
              <p>
                {latest?.event === "stage.skipped"
                  ? String(latest.payload.reason)
                  : "Recorded payload from the backend function. No intermediate decision is fabricated."}
              </p>
              {latest && <pre>{JSON.stringify(latest.payload, null, 2)}</pre>}
            </div>
          )}
        </div>
      </div>
      <div className="run-bottom">
        <section>
          <h2>Model activity</h2>
          {!modelEvents.length ? (
            <p>
              {running
                ? "No model calls have been emitted so far."
                : "No model calls were made. Clear requests and supported structured inputs can use the deterministic path."}
            </p>
          ) : (
            modelEvents.map((e, i) => (
              <div className="run-model-event" key={i}>
                <strong>{e.event}</strong>
                <pre>{JSON.stringify(e.payload, null, 2)}</pre>
              </div>
            ))
          )}
        </section>
        <section>
          <h2>
            Execution journal <span>{events.length} retained events</span>
          </h2>
          <ol className="run-journal">
            {events.map((e, i) => (
              <li key={i}>
                <span>{e.sequence ?? i + 1}</span>
                <time>{e.elapsed_ms ?? 0}ms</time>
                <strong>{e.event}</strong>
                <small>{e.payload.stage ?? e.case_id ?? "run"}</small>
              </li>
            ))}
          </ol>
          {!events.length && (
            <p>Start a run to receive its real ordered events.</p>
          )}
        </section>
      </div>
      {result && (
        <section className="run-final" role="status">
          <div>
            <span>PIPELINE FINISHED</span>
            <h2>
              {String(result.payload.processed)} processed ·{" "}
              {String(result.payload.blocked)} blocked
            </h2>
            <p>
              A finished run can still find incomplete deletion or insufficient
              evidence.
            </p>
          </div>
          <button disabled={!output} onClick={download}>
            <Download size={15} />
            {output
              ? "Download validated CSV"
              : "CSV blocked by unresolved cases"}
          </button>
          <details>
            <summary>All per-case outputs and measured usage</summary>
            <pre>
              {JSON.stringify(
                {
                  answers: result.payload.answers,
                  usage: result.payload.usage,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </section>
  );
}
