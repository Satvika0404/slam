import Connect from "./Connect";
import Intelligence, { type IntelligenceData } from "./Intelligence";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Asterisk,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Database,
  Download,
  FileSearch,
  FileText,
  Fingerprint,
  FolderOpen,
  History,
  Layers,
  LockKeyhole,
  Network,
  Pause,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import SystemGraph from "../console/SystemGraph";
import { fromCase, human } from "../console/model";
import type { SystemEdge } from "../console/types";
import { consumeExecution, executionStages } from "../live";
import type { ExecutionEvent } from "../live";
import type { AuditCase } from "../types";
import type {
  CaseSummary,
  Action,
  DatasetInput,
  RunInfo,
  Sandbox,
  WorkingRecord,
} from "./types";
import "../console/console.css";
import "./workflow.css";

const Identity = lazy(() => import("../scenes/Identity"));
const phases = ["Dataset", "Audit", "Intelligence console", "Final report"];
const icons = [FolderOpen, FileSearch, Network, ShieldCheck];
const label = (s: string) => s.replaceAll("_", " ").toLowerCase();
const clock = (s: string) =>
  new Date(s).toLocaleTimeString("en-GB", { timeZone: "UTC", hour12: false });
const absent = (s: string) =>
  ["ABSENT", "DELETED", "REMOVED", "PURGED", "NOT_FOUND"].includes(s);

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* preserve status */
    }
    throw new Error(message);
  }
  return response.json();
}
const json = (value: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

function State({ value }: { value: string | null }) {
  return (
    <span
      className={`wf-state ${value === "COMPLETE" || value === "verified" ? "good" : value === "INCOMPLETE" || value === "failed" ? "attention" : "neutral"}`}
    >
      <i />
      {value ? label(value) : "unresolved"}
    </span>
  );
}

export default function Workflow() {
  const [input, setInput] = useState<DatasetInput | null>(null);
  const [loadingInput, setLoadingInput] = useState(true);
  const [stage, setStage] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [graphHistory, setGraphHistory] = useState(false);
  const [run, setRun] = useState<RunInfo | null>(null);
  const [caseId, setCaseId] = useState("");
  const [view, setView] = useState<AuditCase | null>(null);
  const [sandbox, setSandbox] = useState<Sandbox | null>(null);
  const [busy, setBusy] = useState<
    "audit" | "execute" | "upload" | "prepare" | null
  >(null);
  const [error, setError] = useState("");
  const [journal, setJournal] = useState<ExecutionEvent[]>([]);
  const [phase, setPhase] = useState("ingestion");
  const [sources, setSources] = useState<Map<string, string>>(new Map());
  const [summaries, setSummaries] = useState<CaseSummary[]>([]);
  const [detail, setDetail] = useState("findings");
  const [evidence, setEvidence] = useState<{
    id: string;
    sandbox: string | null;
  } | null>(null);
  const [system, setSystem] = useState<string | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<string | null>(null);
  const [edge, setEdge] = useState<SystemEdge | null>(null);
  const [query, setQuery] = useState("");
  const [replay, setReplay] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [history, setHistory] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const main = useRef<HTMLElement>(null);
  const identityDetail = useRef<HTMLDetailsElement>(null);
  const copies = useRef(new Map<string, string>());
  const inputVersion = useRef(0);

  useEffect(() => {
    let current = true;
    const version = inputVersion.current;
    document.body.dataset.workspace = "workflow";
    const saved = sessionStorage.getItem("aftertrace.workflow.run");
    async function load() {
      try {
        if (saved) {
          try {
            const existing = await api<RunInfo>(`/api/workflow/runs/${saved}`);
            if (!current || version !== inputVersion.current) return;
            setRun(existing);
            setInput(existing.input);
            setSummaries(existing.cases);
            for (const [key, value] of Object.entries(
              existing.working_copies ?? {},
            )) {
              copies.current.set(`${existing.id}:${key}`, value);
            }
            const selection = JSON.parse(
              sessionStorage.getItem("aftertrace.workflow.selection") ?? "null",
            ) as { run_id: string; case_id: string; stage: number } | null;
            const restored =
              selection?.run_id === existing.id &&
              existing.cases.some((c) => c.case_id === selection.case_id)
                ? selection
                : null;
            setCaseId(
              restored?.case_id ??
                (
                  existing.cases.find(
                    (c) =>
                      c.actions > 0 && !c.uncertain && c.executable !== false,
                  ) ?? existing.cases[0]
                )?.case_id ??
                "",
            );
            setStage(
              existing.status === "completed" ? (restored?.stage ?? 2) : 1,
            );
            return;
          } catch {
            sessionStorage.removeItem("aftertrace.workflow.run");
          }
        }
        const result = await api<{
          available: boolean;
          input: DatasetInput | null;
        }>("/api/workflow/input");
        if (current && version === inputVersion.current) setInput(result.input);
      } catch (e) {
        if (current && version === inputVersion.current)
          setError((e as Error).message);
      } finally {
        if (current && version === inputVersion.current) setLoadingInput(false);
      }
    }
    void load();
    return () => {
      current = false;
      controller.current?.abort();
      delete document.body.dataset.workspace;
    };
  }, []);

  useEffect(() => {
    setView(null);
    setSandbox(null);
    setSystem(null);
    setSelectedRecord(null);
    setEdge(null);
    setEvidence(null);
    setReplay(null);
    setPlaying(false);
    if (!run?.id || !caseId) return;
    const c = new AbortController();
    api<AuditCase>(`/api/workflow/runs/${run.id}/cases/${caseId}`, {
      signal: c.signal,
    })
      .then(setView)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    const sid = copies.current.get(`${run.id}:${caseId}`);
    if (sid)
      api<Sandbox>(`/api/workflow/sandboxes/${sid}`, { signal: c.signal })
        .then(setSandbox)
        .catch(() => {});
    return () => c.abort();
  }, [run?.id, caseId]);

  useEffect(() => {
    if (run?.id && caseId)
      sessionStorage.setItem(
        "aftertrace.workflow.selection",
        JSON.stringify({ run_id: run.id, case_id: caseId, stage }),
      );
  }, [run?.id, caseId, stage]);

  useEffect(() => {
    if (!playing || !sandbox?.receipts.length) return;
    const timer = setTimeout(
      () =>
        setReplay((current) => {
          const next = (current ?? -1) + 1;
          if (next >= sandbox.receipts.length) {
            setPlaying(false);
            return null;
          }
          return next;
        }),
      900,
    );
    return () => clearTimeout(timer);
  }, [playing, replay, sandbox?.receipts.length]);

  function navigate(next: number) {
    setStage(next);
    main.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function inspect(id: string) {
    setEvidence({
      id,
      sandbox:
        id.startsWith("execution_") || id.startsWith("readback_")
          ? (sandbox?.id ?? null)
          : null,
    });
  }
  function remember(event: ExecutionEvent) {
    setJournal((items) => [...items.slice(-999), event]);
  }
  function reset() {
    inputVersion.current += 1;
    controller.current?.abort();
    sessionStorage.removeItem("aftertrace.workflow.run");
    sessionStorage.removeItem("aftertrace.workflow.selection");
    copies.current.clear();
    setRun(null);
    setView(null);
    setCaseId("");
    setSandbox(null);
    setSummaries([]);
    setSources(new Map());
    setJournal([]);
    setError("");
    setStage(0);
  }
  async function loadZip(file: File) {
    reset();
    setInput(null);
    setBusy("upload");
    try {
      setInput(
        await api<DatasetInput>("/api/workflow/input", {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/zip" },
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingInput(false);
      setBusy(null);
    }
  }
  async function audit() {
    if (!input) return;
    setBusy("audit");
    setError("");
    setSummaries([]);
    setSources(new Map());
    setJournal([]);
    setView(null);
    setSandbox(null);
    setCaseId("");
    setPhase("ingestion");
    navigate(1);
    const c = new AbortController();
    controller.current = c;
    let id = "";
    try {
      await consumeExecution(
        await fetch("/api/workflow/runs", {
          ...json({ input_id: input.id, request_text: prompt.trim() || null }),
          signal: c.signal,
        }),
        (event) => {
          remember(event);
          const p = event.payload;
          if (event.event === "run.started") {
            id = String(p.run_id);
            setRun({
              id,
              input,
              request_count: Number(p.request_count),
              status: "running",
              cases: [],
              errors: {},
            });
            sessionStorage.setItem("aftertrace.workflow.run", id);
          }
          if (p.stage) setPhase(p.stage);
          if (event.event === "source.completed") {
            const source = p.source as {
              source_id: string;
              parse_status: string;
            };
            setSources((items) =>
              new Map(items).set(source.source_id, source.parse_status),
            );
          }
          if (event.event === "case.completed")
            setSummaries((items) => [...items, p as unknown as CaseSummary]);
          if (event.event === "run.failed") throw new Error(String(p.message));
        },
      );
      const completed = await api<RunInfo>(`/api/workflow/runs/${id}`);
      if (completed.status !== "completed")
        throw new Error("Audit was interrupted; no completed run is assumed.");
      setRun(completed);
      if (Object.keys(completed.errors).length)
        setError(
          `${Object.keys(completed.errors).length} requests failed. Their results are unresolved and the full CSV is blocked.`,
        );
      setSummaries(completed.cases);
      setCaseId(
        (
          completed.cases.find(
            (c) => c.actions > 0 && !c.uncertain && c.executable !== false,
          ) ?? completed.cases[0]
        )?.case_id ?? "",
      );
      navigate(2);
    } catch (e) {
      setError(
        (e as Error).name === "AbortError"
          ? "Stopped following. The backend stops at its next execution checkpoint."
          : (e as Error).message,
      );
    } finally {
      setBusy(null);
      controller.current = null;
    }
  }
  async function prepare() {
    if (!run || !view) return;
    setBusy("prepare");
    setError("");
    try {
      const copy = await api<Sandbox>(
        "/api/workflow/sandboxes",
        json({ run_id: run.id, case_id: view.case_id }),
      );
      copies.current.set(`${run.id}:${view.case_id}`, copy.id);
      setSandbox(copy);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function execute() {
    if (!sandbox) return;
    setBusy("execute");
    setError("");
    setReplay(null);
    setPlaying(false);
    const c = new AbortController();
    controller.current = c;
    try {
      await consumeExecution(
        await fetch(`/api/workflow/sandboxes/${sandbox.id}/execute`, {
          method: "POST",
          signal: c.signal,
        }),
        (event) => {
          remember(event);
          if (event.payload.snapshot)
            setSandbox(event.payload.snapshot as unknown as Sandbox);
          if (event.event === "action.failed" || event.event === "run.failed")
            setError(
              String(event.payload.message ?? "Execution did not finish"),
            );
          // Keep the atlas in view so the verified changes can be inspected.
          // The final report is the next explicit step, never a timed scene change.
        },
      );
    } catch (e) {
      setError(
        (e as Error).name === "AbortError"
          ? "Stopped following. Inspect the working copy before resuming; committed actions remain recorded."
          : (e as Error).message,
      );
    } finally {
      setBusy(null);
      controller.current = null;
    }
  }

  const records: WorkingRecord[] = useMemo(() => {
    if (!view) return [];
    if (sandbox && replay === null) return sandbox.records;
    return view.context.resource_states.map((r) => {
      const preview = view.record_previews?.find(
        (p) => p.system_id === r.system_id && p.resource_id === r.resource_id,
      );
      const receipt =
        replay !== null
          ? sandbox?.receipts
              .slice(0, replay + 1)
              .filter(
                (p) =>
                  p.system_id === r.system_id &&
                  p.resource_id === r.resource_id,
              )
              .at(-1)
          : undefined;
      const state = receipt?.state ?? r.state;
      return {
        ...r,
        before_state: r.state,
        state,
        present: !absent(state),
        receipt: receipt ?? null,
        fields:
          receipt && receipt.operation !== "DELETE_RECORD"
            ? preview?.proposed_fields
            : preview?.fields,
      };
    });
  }, [view, sandbox, replay]);
  const graph = useMemo(() => {
    if (!view) return null;
    const data = fromCase(view);
    data.graph.nodes = data.graph.nodes.map((node) => {
      const own = records.filter((r) => r.system_id === node.id);
      const running =
        replay === null &&
        sandbox?.actions.some(
          (a) => a.system_id === node.id && a.status === "running",
        );
      return {
        ...node,
        remaining: own.filter((r) => r.present).length,
        original_resources: own.length,
        live_state:
          replay === null &&
          sandbox?.actions.some(
            (a) => a.system_id === node.id && a.status === "failed",
          )
            ? "failed"
            : running
              ? "running"
              : own.some((r) => r.receipt)
                ? "verified"
                : "observed",
      };
    });
    data.graph.edges = data.graph.edges.map((e) => {
      const control = records.find((r) => r.resource_id === e.resource_id);
      const receipt = control?.receipt;
      const ended =
        control?.state === "DISABLED" || control?.state === "BLOCKED";
      return {
        ...e,
        active: ended ? false : e.active,
        execution_state: ended && receipt ? "ended" : "observed",
        proof_id: receipt?.id,
        event_at: receipt?.at,
      };
    });
    const systems = [...data.graph.nodes];
    for (const record of records) {
      const parent = systems.find((n) => n.id === record.system_id);
      if (!parent) continue;
      const id = `row:${record.system_id}:${record.resource_id}`;
      const running = sandbox?.actions.some(
        (a) =>
          a.resource_id === record.resource_id &&
          a.system_id === record.system_id &&
          a.status === "running",
      );
      const removed = !record.present && !!record.receipt;
      data.graph.nodes.push({
        ...parent,
        tier: "row",
        id,
        label: record.resource_id,
        category: record.category,
        resources: 1,
        original_resources: 1,
        remaining: record.present ? 1 : 0,
        live_state: removed
          ? graphHistory
            ? "ended"
            : "deleted"
          : replay === null &&
              sandbox?.actions.some(
                (a) =>
                  a.system_id === record.system_id &&
                  a.resource_id === record.resource_id &&
                  a.status === "failed",
              )
            ? "failed"
            : running
              ? "running"
              : record.receipt
                ? "verified"
                : "observed",
      });
      data.graph.edges.push({
        source: record.system_id,
        target: id,
        kind: "contains record",
        op: "contains",
        events: 0,
        fail_rate: null,
        active: false,
        restore: false,
        resource_id: record.resource_id,
        execution_state: removed
          ? graphHistory
            ? "ended"
            : "deleted"
          : "observed",
        evidence_ids: view.context.resource_states.find(
          (r) =>
            r.resource_id === record.resource_id &&
            r.system_id === record.system_id,
        )?.supporting_evidence_ids,
        proof_id: record.receipt?.id,
      });
    }
    return data;
  }, [view, records, sandbox, replay, graphHistory]);
  const filteredCases = summaries.filter((c) =>
    c.case_id.toLowerCase().includes(query.toLowerCase()),
  );
  const requestCount = run?.request_count ?? input?.requests ?? 0;
  const visibleRecords = records.filter(
    (r) =>
      (!system || r.system_id === system) &&
      (history || r.present || !r.receipt),
  );
  const selectedEvidence = view?.context.resource_states.find(
    (r) => `row:${r.system_id}:${r.resource_id}` === selectedRecord,
  );
  const actions: Action[] =
    sandbox?.actions ??
    view?.answer.steps
      .filter((s) => s.phase === "REMEDIATION")
      .map((s) => ({
        ...s,
        id: `action_${s.step_no}`,
        status: "pending",
        proof_id: null,
      })) ??
    [];
  const verifiedCount =
    sandbox?.actions.filter((a) => a.status === "verified").length ?? 0;
  const originalStatus = view?.answer.deletion_status ?? null;
  const uncertainties = [
    ...new Set([
      ...(view?.answer.trace?.not_certified_because ?? []),
      ...(sandbox?.after?.answer.trace?.not_certified_because ?? []),
    ]),
  ];
  const finalStatus = sandbox?.after?.answer.deletion_status ?? null;
  const blocked =
    !!view &&
    (view.answer.trace?.not_certified_because?.length ||
      view.context.unresolved_conflicts.length ||
      view.context.coverage_issues.length ||
      view.context.resource_states.some(
        (r) => !r.supporting_evidence_ids.length,
      ) ||
      view.answer.deletion_status === "NOT_APPLICABLE");

  return (
    <div className="workflow-app">
      <a className="wf-skip" href="#workflow-main">
        Skip to workflow
      </a>
      <header className="wf-topbar">
        <button className="wf-wordmark" onClick={() => navigate(run ? 2 : 0)}>
          <span>
            <Asterisk size={24} />
          </span>
          aftertrace<span className="wf-wordmark-dot">.</span>
        </button>
        <nav aria-label="Audit workflow" className="wf-stepper">
          {phases.map((name, i) => {
            const Icon = icons[i];
            const unlocked = i < 2 || !!view;
            return (
              <button
                key={name}
                aria-current={stage === i ? "step" : undefined}
                disabled={!unlocked || (busy === "execute" && i === 0)}
                className={`${stage === i ? "active" : ""} ${stage > i ? "passed" : ""}`}
                onClick={() => navigate(i)}
              >
                <span className="wf-step-icon">
                  {stage > i ? <Check size={14} /> : <Icon size={14} />}
                </span>
                <span>{name}</span>
                {i < 3 && (
                  <ChevronRight className="wf-step-chevron" size={14} />
                )}
              </button>
            );
          })}
        </nav>
        <span className="wf-local">
          <i />
          LOCAL · NO API CALLS
        </span>
      </header>
      {input && stage > 0 && (
        <div className="wf-run-ribbon">
          <span>
            <Database size={13} />
            {input.name}
          </span>
          <code>{input.fingerprint.slice(0, 12)}</code>
          <span>
            {input.requests} requests · {input.sources} sources
          </span>
          {run && <code className="wf-run-id">RUN {run.id.slice(0, 8)}</code>}
          <button disabled={!!busy} onClick={reset}>
            Change input <RotateCcw size={12} />
          </button>
        </div>
      )}
      {error && (
        <div className="wf-error" role="alert">
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      <main id="workflow-main" ref={main} tabIndex={-1}>
        {stage === 0 && (
          <section className="wf-input-stage wf-enter">
            <div className="wf-input-copy">
              <span className="wf-eyebrow">
                <i />
                THE DELETION WORKFLOW
              </span>
              <h1>
                One dataset.
                <br />
                Every trace.
                <br />
                <em>Accounted for.</em>
              </h1>
              <p>
                Follow your evidence from the first audit to verified
                remediation. One continuous workspace. One source of truth.
              </p>
              <div className="wf-input-cta">
                <button
                  className="wf-primary"
                  disabled={!input || !!busy || loadingInput}
                  onClick={audit}
                >
                  {loadingInput ? "Checking local dataset…" : "Begin the audit"}
                  <ArrowUpRight size={18} />
                </button>
                <button
                  className="wf-secondary"
                  disabled={!!busy}
                  onClick={() => upload.current?.click()}
                >
                  <Upload size={15} />
                  {busy === "upload"
                    ? "Validating input…"
                    : "Use a dataset ZIP"}
                </button>
                <input
                  ref={upload}
                  type="file"
                  accept=".zip"
                  aria-label="Upload dataset ZIP"
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void loadZip(file);
                    e.target.value = "";
                  }}
                />
              </div>
              <div className="wf-request-prompt">
                <label htmlFor="deletion-prompt">Deletion request</label>
                <textarea
                  id="deletion-prompt"
                  placeholder="Delete personal data for person@example.com, or leave blank to audit the supplied requests"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </div>
              <Connect
                onInput={(value) => {
                  inputVersion.current += 1;
                  reset();
                  setInput(value);
                  setLoadingInput(false);
                }}
              />
              <span className="wf-input-note">
                <LockKeyhole size={13} />
                Source evidence stays read-only. Execution uses an isolated
                copy.
              </span>
            </div>
            <div className="wf-input-object">
              <div className="wf-object-top">
                <span className="wf-eyebrow">INPUT / 01</span>
                <span className="wf-ready">
                  <i />
                  {input ? "READY TO INVESTIGATE" : "AWAITING DATASET"}
                </span>
              </div>
              <div className="wf-data-sculpture" aria-hidden="true">
                <div className="wf-data-sheet sheet-back" />
                <div className="wf-data-sheet sheet-mid" />
                <div className="wf-data-sheet sheet-front">
                  <Fingerprint size={42} strokeWidth={1} />
                  <span>
                    EVIDENCE
                    <br />
                    COLLECTION
                  </span>
                  <div className="wf-sheet-lines">
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                  <small>
                    {input?.fingerprint.slice(0, 18) ??
                      "LOAD YOUR SOURCE FILES"}
                  </small>
                </div>
                <span className="wf-format-tag tag-a">
                  {input ? `${input.requests} requests` : "CSV + evidence"}
                </span>
                <span className="wf-format-tag tag-b">
                  {input ? `${input.sources} sources` : "One input"}
                </span>
              </div>
              <div className="wf-object-summary">
                <div>
                  <FolderOpen size={18} />
                  <strong>{input?.name ?? "Choose your dataset"}</strong>
                </div>
                <p>
                  {input
                    ? Object.entries(input.formats)
                        .map(([kind, n]) => `${n} ${kind.toUpperCase()}`)
                        .join(" · ")
                    : "Six CSV tables and their manifest-linked evidence. Upload a ZIP or install the local participant dataset."}
                </p>
                <div className="wf-object-fingerprint">
                  <span>CONTENT FINGERPRINT</span>
                  <code>
                    {input?.fingerprint.slice(0, 32) ??
                      "Verified after loading"}
                  </code>
                </div>
              </div>
            </div>
            <div className="wf-input-path">
              {[
                "Read the evidence",
                "Reconstruct the truth",
                "Execute in a working copy",
                "Verify the outcome",
              ].map((s, i) => (
                <span key={s}>
                  <b>0{i + 1}</b>
                  {s}
                  {i < 3 && <ArrowRight size={15} />}
                </span>
              ))}
            </div>
          </section>
        )}

        {stage === 1 && (
          <section className="wf-audit-stage wf-enter">
            <div className="wf-section-heading">
              <div>
                <span className="wf-eyebrow">02 / AUDIT</span>
                <h1>
                  Evidence becomes
                  <br />
                  <em>understanding.</em>
                </h1>
              </div>
              <div className="wf-audit-counter">
                <strong>
                  {summaries.length}
                  <span>/{requestCount}</span>
                </strong>
                <p>
                  {busy === "audit"
                    ? "requests reconstructed"
                    : "completed request audits"}
                </p>
                {busy === "audit" && (
                  <button onClick={() => controller.current?.abort()}>
                    <Square size={12} />
                    Stop following
                  </button>
                )}
              </div>
            </div>
            <div
              className="wf-audit-progress"
              role="progressbar"
              aria-label="Requests audited"
              aria-valuemin={0}
              aria-valuemax={requestCount}
              aria-valuenow={summaries.length}
            >
              <i
                style={{
                  width: `${requestCount ? (summaries.length / requestCount) * 100 : 0}%`,
                }}
              />
            </div>
            <div className="wf-audit-body">
              {journal
                .filter((e) => e.event === "recovery.completed")
                .map((e, i) => (
                  <div
                    className={`wf-inline-recovery ${e.payload.status}`}
                    role="status"
                    key={i}
                  >
                    <Activity size={18} />
                    <div>
                      <strong>
                        {String(e.payload.component)} ·{" "}
                        {e.payload.status === "recovered"
                          ? "Recovered this run"
                          : "Recovery blocked"}
                      </strong>
                      <p>
                        {String(e.payload.adapter_version)} · validated input
                        copy; original preserved
                      </p>
                    </div>
                  </div>
                ))}
              <div className="wf-phase-list">
                {executionStages.map((p, i) => {
                  const latest = journal
                    .filter((e) => e.payload.stage === p.id)
                    .at(-1);
                  const done =
                    latest?.event === "stage.completed" ||
                    latest?.event === "stage.skipped";
                  return (
                    <div
                      key={p.id}
                      className={`${phase === p.id && busy === "audit" ? "current" : ""} ${done ? "done" : ""}`}
                    >
                      <span className="wf-phase-dot">
                        {done ? (
                          <Check size={13} />
                        ) : (
                          <b>{String(i + 1).padStart(2, "0")}</b>
                        )}
                      </span>
                      <div>
                        <strong>{p.name}</strong>
                        <small>{p.tech}</small>
                      </div>
                      {phase === p.id && busy === "audit" && (
                        <Activity size={16} />
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="wf-evidence-feed">
                <header>
                  <span className="wf-eyebrow">SOURCE ACCOUNTING</span>
                  <b>
                    {sources.size || view?.sources.length || 0} /{" "}
                    {input?.sources ?? 0}
                  </b>
                </header>
                {sources.size
                  ? [...sources]
                      .slice(-9)
                      .reverse()
                      .map(([id, status]) => (
                        <div className="wf-source-arrival" key={id}>
                          <FileText size={16} />
                          <code>{id}</code>
                          <State value={status} />
                        </div>
                      ))
                  : (view?.sources.slice(0, 7).map((source) => (
                      <button
                        key={source.source_id}
                        onClick={() => inspect(source.source_id)}
                      >
                        <FileText size={16} />
                        <code>{source.source_id}</code>
                        <State value={source.parse_status} />
                      </button>
                    )) ?? (
                      <div className="wf-empty">
                        <FileSearch size={35} />
                        <p>The actual parsers will report each source here.</p>
                      </div>
                    ))}
                <footer>
                  Transitions follow server events. Fast stages remain available
                  in the execution journal.
                </footer>
              </div>
            </div>
            {view && (
              <AuditDetail
                view={view}
                detail={detail}
                setDetail={setDetail}
                inspect={inspect}
              />
            )}
            {run?.status === "completed" && (
              <button className="wf-primary" onClick={() => navigate(2)}>
                Continue to Intelligence Console <ArrowRight size={16} />
              </button>
            )}
            <details className="wf-journal">
              <summary>
                <Activity size={14} />
                Execution journal <span>{journal.length} retained events</span>
                <ChevronDown size={14} />
              </summary>
              <ol>
                {journal.slice(-100).map((e, i) => (
                  <li key={`${e.sequence}:${i}`}>
                    <code>{e.sequence}</code>
                    <time>{e.at ? clock(e.at) : ""}</time>
                    <strong>{e.event}</strong>
                    <span>
                      {String(e.payload.case_id ?? e.payload.stage ?? "input")}
                    </span>
                  </li>
                ))}
              </ol>
            </details>
          </section>
        )}

        {(stage === 2 || stage === 3) && (
          <>
            <div
              className={`wf-context-bar ${stage === 2 ? "wf-console-context" : ""}`}
            >
              <div>
                <span className="wf-eyebrow">
                  {stage === 2
                    ? "03 / INTELLIGENCE CONSOLE"
                    : "04 / FINAL REPORT"}
                </span>
                <h1>
                  {stage === 2 ? (
                    <>
                      See the change.
                      <br />
                      <em>Keep the proof.</em>
                    </>
                  ) : (
                    <>
                      A result you can
                      <br />
                      <em>trace back.</em>
                    </>
                  )}
                </h1>
              </div>
              <div className="wf-case-context">
                {view ? (
                  <>
                    <span>
                      {view.case_id} / {view.name}
                    </span>
                    <strong>{view.request.email}</strong>
                    <small>
                      Original audit ·{" "}
                      {new Date(view.request.audit_at).toLocaleString("en-GB", {
                        timeZone: "UTC",
                      })}{" "}
                      UTC
                    </small>
                  </>
                ) : (
                  <span role="status">Loading the audited request…</span>
                )}
              </div>
            </div>
            <div
              className={`wf-workspace-grid ${stage === 2 ? "wf-console-workspace" : ""}`}
            >
              <aside className="wf-request-index">
                <header>
                  <span className="wf-eyebrow">REQUESTS</span>
                  <b>{summaries.length}</b>
                </header>
                <label className="wf-search">
                  <Search size={14} />
                  <input
                    aria-label="Search audit requests"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Find a request ID"
                  />
                </label>
                <div className="wf-request-list">
                  {filteredCases
                    .slice(0, expanded ? undefined : 45)
                    .map((c) => (
                      <button
                        key={c.case_id}
                        className={caseId === c.case_id ? "selected" : ""}
                        disabled={busy === "execute"}
                        onClick={() => {
                          setCaseId(c.case_id);
                          setError("");
                        }}
                      >
                        <span>
                          <code>{c.case_id}</code>
                          <i
                            className={
                              c.status === "COMPLETE"
                                ? "good"
                                : c.status === "INCOMPLETE"
                                  ? "attention"
                                  : "neutral"
                            }
                          />
                        </span>
                        <small>
                          {c.uncertain
                            ? "Evidence needs review"
                            : c.actions
                              ? `${c.actions} planned actions`
                              : label(c.status ?? "unresolved")}
                        </small>
                      </button>
                    ))}
                  {filteredCases.length > 45 && !expanded && (
                    <button
                      className="wf-show-more"
                      onClick={() => setExpanded(true)}
                    >
                      Show all {filteredCases.length} requests
                    </button>
                  )}
                </div>
                <footer>
                  <Fingerprint size={14} />
                  <span>
                    All views use
                    <br />
                    the same pinned run.
                  </span>
                </footer>
              </aside>
              {!view ? (
                <div className="wf-loading" role="status">
                  <div className="wf-loading-orbit" />
                  <span>Opening the recorded audit…</span>
                </div>
              ) : stage === 2 ? (
                <div className="wf-investigation">
                  <div className="wf-console-toolbar">
                    <div>
                      <span className="wf-eyebrow">
                        {sandbox
                          ? "ISOLATED WORKING COPY"
                          : "ORIGINAL AUDIT SNAPSHOT"}
                      </span>
                      <h2>
                        {sandbox
                          ? "The record atlas"
                          : "What the evidence found"}
                      </h2>
                    </div>
                    <State value={sandbox?.status ?? originalStatus} />
                  </div>
                  <div className="wf-graph-shell">
                    {graph && (
                      <SystemGraph
                        data={graph}
                        readOnly
                        workflow
                        onInspect={inspect}
                        onSelectSystem={(id) => {
                          const row = records.find(
                            (r) => `row:${r.system_id}:${r.resource_id}` === id,
                          );
                          setSystem(row?.system_id ?? id);
                          setSelectedRecord(row ? id : null);
                          setEdge(null);
                        }}
                        onSelectEdge={(e) => {
                          setEdge(e);
                          setSelectedRecord(null);
                          setSystem(e.source);
                        }}
                      />
                    )}
                    {!graph?.graph.edges.length && (
                      <span className="wf-no-links">
                        No explicit flow connections were supplied for this
                        request. Records remain inspectable.
                      </span>
                    )}
                  </div>
                  {sandbox?.after && (
                    <div className="wf-execution-complete" role="status">
                      <ShieldCheck size={19} />
                      <div>
                        <strong>Execution finished. Evidence recorded.</strong>
                        <span>
                          {verifiedCount} actions verified · working copy{" "}
                          {label(finalStatus ?? "unresolved")}
                        </span>
                      </div>
                      <button onClick={() => navigate(3)}>
                        Continue to final report <ArrowRight size={14} />
                      </button>
                    </div>
                  )}
                  <label className="wf-graph-history">
                    <input
                      type="checkbox"
                      checked={graphHistory}
                      onChange={(e) => setGraphHistory(e.target.checked)}
                    />
                    Show deleted nodes in graph history
                  </label>
                  <Intelligence
                    key={`${run?.id}:${caseId}`}
                    runId={run!.id}
                    data={run?.intelligence as IntelligenceData | undefined}
                    sandbox={sandbox}
                    requestEmail={view.request.email}
                    caseId={view.case_id}
                    onEvidence={inspect}
                    resourceId={view.context.resource_states[0]?.resource_id}
                  />
                  <div className="wf-graph-key">
                    <span>
                      <i className="key-observed" />
                      Observed system
                    </span>
                    <span>
                      <i className="key-running" />
                      Action running
                    </span>
                    <span>
                      <i className="key-verified" />
                      Read-back verified
                    </span>
                    <span>
                      <i className="key-ended" />
                      Ended connection
                    </span>
                    <label>
                      <input
                        type="checkbox"
                        checked={history}
                        onChange={(e) => setHistory(e.target.checked)}
                      />
                      Show removed records
                    </label>
                  </div>
                  {sandbox?.receipts.length ? (
                    <div className="wf-history-strip">
                      <button
                        className={replay === -1 ? "active" : ""}
                        onClick={() => {
                          setReplay(-1);
                          setPlaying(false);
                        }}
                      >
                        <History size={13} />
                        Before
                      </button>
                      <div>
                        {sandbox.receipts.map((r, i) => (
                          <button
                            key={r.id}
                            className={replay === i ? "active" : ""}
                            onClick={() => {
                              setReplay(i);
                              setPlaying(false);
                            }}
                            title={`${human(r.operation)} · ${clock(r.at)} UTC`}
                          >
                            <span>{i + 1}</span>
                            <i />
                          </button>
                        ))}
                      </div>
                      <button
                        className={replay === null ? "active" : ""}
                        onClick={() => {
                          setReplay(null);
                          setPlaying(false);
                        }}
                      >
                        Latest state
                      </button>
                      <button
                        aria-label={
                          playing
                            ? "Pause recorded playback"
                            : "Replay recorded changes"
                        }
                        onClick={() => {
                          setReplay(-1);
                          setPlaying(!playing);
                        }}
                      >
                        {playing ? <Pause size={13} /> : <Play size={13} />}
                      </button>
                      <small>
                        {playing
                          ? "RECORDED PLAYBACK"
                          : replay !== null
                            ? "RECORDED STATE"
                            : "BACKEND STATE"}
                      </small>
                    </div>
                  ) : null}
                  <div className="wf-records-heading">
                    <h3>
                      {edge
                        ? "Selected connection"
                        : system
                          ? human(system)
                          : "Imported records"}
                    </h3>
                    {system && (
                      <button
                        onClick={() => {
                          setSystem(null);
                          setSelectedRecord(null);
                          setEdge(null);
                        }}
                      >
                        Show all systems <X size={12} />
                      </button>
                    )}
                    <span>{visibleRecords.length} records</span>
                  </div>
                  {selectedEvidence && view && (
                    <section
                      className="wf-evidence-chain"
                      aria-label="Record evidence chain"
                    >
                      <div>
                        <Fingerprint size={16} />
                        <span>Resolved subject</span>
                        <strong>
                          {view.context.subject_id ?? "Unresolved"}
                        </strong>
                        <button
                          onClick={() => {
                            setDetail("identity");
                            if (identityDetail.current) {
                              identityDetail.current.open = true;
                              identityDetail.current.scrollIntoView({
                                block: "center",
                              });
                            }
                          }}
                        >
                          Explore current and historical identity
                          <ArrowUpRight size={12} />
                        </button>
                      </div>
                      <ChevronRight size={16} />
                      <div>
                        <Database size={16} />
                        <span>Observed resource</span>
                        <strong>
                          {selectedEvidence.system_id}/
                          {selectedEvidence.resource_id}
                        </strong>
                      </div>
                      <ChevronRight size={16} />
                      <div>
                        <FileText size={16} />
                        <span>Source at audit cutoff</span>
                        <strong>
                          {selectedEvidence.state} ·{" "}
                          {clock(selectedEvidence.at)} UTC
                        </strong>
                        {selectedEvidence.supporting_evidence_ids.map((id) => (
                          <button key={id} onClick={() => inspect(id)}>
                            {id}
                            <ArrowUpRight size={12} />
                          </button>
                        ))}
                        {selectedEvidence.conflicting_evidence_ids.map((id) => (
                          <button key={id} onClick={() => inspect(id)}>
                            Conflicting: {id}
                          </button>
                        ))}
                      </div>
                      <small>
                        Original evidence chain. Execution changes have separate
                        read-back receipts below.
                      </small>
                    </section>
                  )}
                  {edge && (
                    <div className="wf-edge-detail">
                      <span>
                        {human(edge.source)} <ArrowRight size={14} />
                        {human(edge.target)}
                      </span>
                      <State
                        value={
                          edge.execution_state ??
                          (edge.active ? "ACTIVE" : "OBSERVED")
                        }
                      />
                      <p>
                        {human(edge.op)} · {edge.kind}
                      </p>
                      {edge.event_at && (
                        <small>
                          Observed transition: {clock(edge.event_at)} UTC
                        </small>
                      )}
                      {(edge.evidence_ids ?? []).map((id) => (
                        <button key={id} onClick={() => inspect(id)}>
                          <FileText size={12} />
                          {id}
                        </button>
                      ))}
                      {edge.proof_id && (
                        <button onClick={() => inspect(edge.proof_id!)}>
                          Open execution proof <ArrowUpRight size={12} />
                        </button>
                      )}
                    </div>
                  )}
                  <div className="wf-record-grid">
                    {visibleRecords.map((record) => (
                      <RecordTile
                        key={`${record.system_id}:${record.resource_id}`}
                        record={record}
                        preview={view.record_previews?.find(
                          (p) =>
                            p.system_id === record.system_id &&
                            p.resource_id === record.resource_id,
                        )}
                        inspect={inspect}
                      />
                    ))}
                    {!visibleRecords.length && (
                      <div className="wf-empty">
                        <CheckCheck size={28} />
                        <p>
                          No present records in this selection. Turn on history
                          to inspect the removed records and their proof.
                        </p>
                      </div>
                    )}
                  </div>
                  <details className="wf-inspect-audit" ref={identityDetail}>
                    <summary>
                      Inspect identity, original evidence and policy{" "}
                      <ChevronDown size={15} />
                    </summary>
                    <AuditDetail
                      view={view}
                      detail={detail}
                      setDetail={setDetail}
                      inspect={inspect}
                    />
                  </details>
                </div>
              ) : (
                <div className="wf-report">
                  <div className="wf-outcome">
                    <span className="wf-eyebrow">
                      {sandbox?.after
                        ? "FRESH SANDBOX VERIFICATION"
                        : "ORIGINAL AUDIT RESULT"}
                    </span>
                    <div className="wf-outcome-line">
                      <State value={originalStatus} />
                      {sandbox?.after && (
                        <>
                          <ArrowRight size={23} />
                          <State value={finalStatus} />
                        </>
                      )}
                    </div>
                    <h2>
                      {sandbox?.after
                        ? finalStatus === "COMPLETE"
                          ? "Verified in the working copy."
                          : "More work remains."
                        : originalStatus === "COMPLETE"
                          ? "The evidence supports completion."
                          : originalStatus === "NOT_APPLICABLE"
                            ? "No deletion was authorized."
                            : "The audit found unfinished work."}
                    </h2>
                    <p>
                      {sandbox?.after
                        ? sandbox.after.scope
                        : "This result describes the imported evidence at the original audit cutoff. Proposed remediation has not been executed."}
                    </p>
                    {sandbox?.after && (
                      <button
                        className="wf-proof-link"
                        onClick={() => inspect(sandbox.after!.proof_id)}
                      >
                        <ShieldCheck size={15} />
                        Open fresh read-back evidence <ArrowUpRight size={13} />
                      </button>
                    )}
                  </div>
                  <div className="wf-report-measures">
                    <div>
                      <span>Imported scope</span>
                      <strong>
                        {records.length}
                        <small> resources</small>
                      </strong>
                    </div>
                    <div>
                      <span>Executed & verified</span>
                      <strong>
                        {verifiedCount}
                        <small> / {actions.length} actions</small>
                      </strong>
                    </div>
                    <div>
                      <span>Preserved records</span>
                      <strong>
                        {
                          records.filter(
                            (r) =>
                              view.context.policy_rules.some(
                                (p) =>
                                  p.category === r.category &&
                                  p.required_action === "RETAIN",
                              ) && r.present,
                          ).length
                        }
                      </strong>
                    </div>
                  </div>
                  {!!uncertainties.length && (
                    <div className="wf-uncertainty">
                      <h3>Unresolved evidence</h3>
                      {uncertainties.map((reason) => (
                        <p key={reason}>{reason}</p>
                      ))}
                    </div>
                  )}
                  <div className="wf-report-section">
                    <h3>Original findings & ordered plan</h3>
                    <span>Preserved exactly as audited</span>
                    {view.answer.steps.map((step) => (
                      <div className="wf-report-step" key={step.step_no}>
                        <b>{String(step.step_no).padStart(2, "0")}</b>
                        <div>
                          <small>{step.phase}</small>
                          <strong>{human(step.operation)}</strong>
                          <code>
                            {step.system_id} / {step.resource_id}
                          </code>
                        </div>
                        {step.evidence_id ? (
                          <button onClick={() => inspect(step.evidence_id)}>
                            <FileText size={13} />
                            Evidence
                          </button>
                        ) : (
                          <span>Proposed / future check</span>
                        )}
                      </div>
                    ))}
                  </div>
                  {!!sandbox?.receipts.length && (
                    <div className="wf-report-section">
                      <h3>Execution evidence</h3>
                      {sandbox.receipts.map((r) => (
                        <div className="wf-report-step" key={r.id}>
                          <CircleCheck size={19} />
                          <div>
                            <strong>{human(r.operation)}</strong>
                            <code>
                              {r.resource_id} · {clock(r.at)} UTC
                            </code>
                          </div>
                          <button onClick={() => inspect(r.id)}>
                            Read-back proof <ArrowUpRight size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="wf-report-downloads">
                    {run?.csv_available && (
                      <a
                        className="wf-primary"
                        href={`/api/workflow/runs/${run.id}/export`}
                        download
                      >
                        <Download size={15} />
                        Original audit CSV
                      </a>
                    )}
                    {sandbox && (
                      <a
                        className="wf-secondary"
                        href={`/api/workflow/sandboxes/${sandbox.id}/export`}
                        download
                      >
                        <Download size={15} />
                        Execution report
                      </a>
                    )}
                    <button
                      className="wf-secondary"
                      onClick={() => navigate(2)}
                    >
                      Return to the graph <Network size={15} />
                    </button>
                  </div>
                </div>
              )}
              {view && stage === 2 && (
                <aside className="wf-action-panel">
                  <div className="wf-action-title">
                    <span className="wf-eyebrow">REMEDIATION</span>
                    <h2>
                      A controlled
                      <br /> <em>next step.</em>
                    </h2>
                  </div>
                  <div className="wf-copy-boundary">
                    <LockKeyhole size={17} />
                    <p>
                      Actual SQLite changes in an isolated copy of this request.
                      Original files and external systems remain unchanged.
                    </p>
                  </div>
                  <div className="wf-action-progress">
                    <span>{verifiedCount} verified</span>
                    <span>{actions.length} planned</span>
                    <div>
                      <i
                        style={{
                          width: `${actions.length ? (verifiedCount / actions.length) * 100 : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                  <ol className="wf-action-list">
                    {actions.map((a, i) => (
                      <li key={a.id} className={a.status}>
                        <span className="wf-action-number">
                          {a.status === "verified" ? (
                            <Check size={13} />
                          ) : (
                            i + 1
                          )}
                        </span>
                        <div>
                          <strong>{human(a.operation)}</strong>
                          <code>{a.resource_id}</code>
                          <small>
                            {a.status === "verified"
                              ? "Committed + read-back verified"
                              : a.status === "running"
                                ? "Executing in SQLite"
                                : a.status === "failed"
                                  ? "Failed; dependent actions stopped"
                                  : "Waiting for execution"}
                          </small>
                          {a.error && (
                            <small className="wf-action-error">{a.error}</small>
                          )}
                          {a.proof_id && (
                            <button onClick={() => inspect(a.proof_id!)}>
                              Inspect proof <ArrowUpRight size={11} />
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                  {!actions.length && (
                    <p className="wf-small-note">
                      {originalStatus === "NOT_APPLICABLE"
                        ? "This request does not authorize deletion."
                        : "No executable remediation appears in this audit."}
                    </p>
                  )}
                  {blocked ? (
                    <div className="wf-blocked">
                      <LockKeyhole size={16} />
                      <p>
                        Execution is blocked until the evidence or authorization
                        is resolved.
                      </p>
                    </div>
                  ) : !sandbox ? (
                    <button
                      className="wf-primary"
                      disabled={!!busy}
                      onClick={prepare}
                    >
                      <Layers size={15} />
                      {busy === "prepare"
                        ? "Preparing working copy…"
                        : "Prepare working copy"}
                    </button>
                  ) : (
                    <button
                      className="wf-primary"
                      disabled={!!busy}
                      onClick={execute}
                    >
                      {busy === "execute" ? (
                        <Activity size={15} />
                      ) : sandbox.status === "verified" ? (
                        <ShieldCheck size={15} />
                      ) : (
                        <Play size={15} />
                      )}{" "}
                      {busy === "execute"
                        ? "Executing & verifying…"
                        : sandbox.status === "verified"
                          ? "Verify again"
                          : actions.length
                            ? "Execute reviewed plan"
                            : "Verify working copy"}
                    </button>
                  )}
                  {busy === "execute" && (
                    <button
                      className="wf-stop"
                      onClick={() => controller.current?.abort()}
                    >
                      <Square size={12} />
                      Stop following
                    </button>
                  )}
                  <button
                    className="wf-text-button"
                    disabled={!!busy}
                    onClick={() => navigate(3)}
                  >
                    View final report <ArrowRight size={14} />
                  </button>
                  <span className="wf-action-footer">
                    <ShieldCheck size={13} />
                    Required retention is preserved.
                  </span>
                </aside>
              )}
            </div>
          </>
        )}
      </main>
      <footer className="wf-page-footer">
        <span>AFTERTRACE / EVIDENCE BEFORE CERTAINTY</span>
        <span>
          {run
            ? `One input · ${run.id.slice(0, 8)}`
            : "Local-first investigation"}
          <i />
          Audit and execution are recorded separately.
        </span>
      </footer>
      {evidence && run && (
        <EvidenceModal
          runId={run.id}
          evidence={evidence}
          close={() => setEvidence(null)}
        />
      )}
    </div>
  );
}

function RecordTile({
  record,
  inspect,
  preview,
}: {
  record: WorkingRecord;
  inspect: (id: string) => void;
  preview?: NonNullable<AuditCase["record_previews"]>[number];
}) {
  const removed = !record.present && !!record.receipt;
  return (
    <article
      className={`wf-record ${removed ? "removed" : ""} ${record.receipt ? "changed" : ""}`}
      data-resource-id={record.resource_id}
      data-state={record.state}
    >
      <div>
        <span className="wf-record-icon">
          {removed ? (
            <Trash2 size={17} />
          ) : record.receipt ? (
            <ShieldCheck size={17} />
          ) : (
            <Database size={17} />
          )}
        </span>
        <State value={record.state} />
      </div>
      <code>{record.resource_id}</code>
      <small>{human(record.category)}</small>
      <p>
        {record.receipt ? (
          <>
            <span>{label(record.before_state)}</span>
            <ArrowRight size={12} />
            <strong>{label(record.state)}</strong>
          </>
        ) : (
          <span>Observed in {human(record.system_id)}</span>
        )}
      </p>
      {!!(record.fields && Object.keys(record.fields).length) && (
        <details className="wf-fields">
          <summary>
            {preview?.operation === "REDACT_RECORD" ||
            preview?.operation === "ANONYMIZE_RECORD"
              ? "Inspect field treatment"
              : "Inspect record fields"}
          </summary>
          <span>
            {record.receipt
              ? "Committed read-back"
              : "Before execution · proposed changes"}
          </span>
          {Object.entries(record.fields)
            .slice(0, 40)
            .map(([path, value]) => {
              const change = record.receipt?.field_changes?.find(
                (c) => c.path === path,
              );
              const proposed =
                preview?.changed_fields.includes(path) && !record.receipt;
              return (
                <div
                  key={path}
                  className={
                    change
                      ? "changed-field field-committed"
                      : proposed
                        ? "changed-field"
                        : ""
                  }
                  data-field-path={path}
                >
                  <code>{path}</code>
                  <span>{String(value ?? "∅").slice(0, 180)}</span>
                  {proposed && (
                    <strong>
                      → {String(preview?.proposed_fields[path] ?? "REMOVED")}
                    </strong>
                  )}
                </div>
              );
            })}
          {record.receipt?.field_changes
            ?.filter((c) => !(c.path in (record.fields ?? {})))
            .map((c) => (
              <div
                key={c.path}
                className="changed-field field-committed"
                data-field-path={c.path}
              >
                <code>{c.path}</code>
                <del>{String(c.before).slice(0, 100)}</del>
                <strong>REMOVED · verified</strong>
              </div>
            ))}
          {(preview?.observation_ids ?? []).map((id) => (
            <small key={id}>Observation {id}</small>
          ))}
        </details>
      )}
      {record.receipt && (
        <button onClick={() => inspect(record.receipt!.id)}>
          Verified {clock(record.receipt.at)} UTC <ArrowUpRight size={12} />
        </button>
      )}
    </article>
  );
}

function AuditDetail({
  view,
  detail,
  setDetail,
  inspect,
}: {
  view: AuditCase;
  detail: string;
  setDetail: (s: string) => void;
  inspect: (id: string) => void;
}) {
  return (
    <div className="wf-audit-detail">
      <nav aria-label="Audit evidence views">
        {["findings", "identity", "evidence", "timeline"].map((tab) => (
          <button
            key={tab}
            aria-pressed={detail === tab}
            className={detail === tab ? "active" : ""}
            onClick={() => setDetail(tab)}
          >
            {tab}
          </button>
        ))}
      </nav>
      {detail === "identity" ? (
        <div className="wf-identity-embed">
          <Suspense fallback={<p>Loading identity evidence…</p>}>
            <Identity
              data={view}
              loading={false}
              onEvidence={inspect}
              onScene={() => {}}
              onCutoff={() => {}}
            />
          </Suspense>
          <p className="wf-small-note">
            Identity and history are pinned to this run's original audit cutoff.
          </p>
        </div>
      ) : detail === "evidence" ? (
        <div className="wf-source-browser">
          {view.sources.map((source) => (
            <button
              key={source.source_id}
              onClick={() => inspect(source.source_id)}
            >
              <FileText size={16} />
              <div>
                <code>{source.source_id}</code>
                <small>
                  {source.origin} · {source.kind.toUpperCase()}
                </small>
              </div>
              <State value={source.parse_status} />
              <ArrowUpRight size={13} />
            </button>
          ))}
        </div>
      ) : detail === "timeline" ? (
        <div className="wf-timeline">
          <div className="wf-cutoff-label">
            <History size={15} />
            Audit cutoff: {new Date(view.request.audit_at).toISOString()}
            <span>Later evidence stays excluded</span>
          </div>
          {view.events.map((event) => (
            <button
              key={event.id}
              className={event.eligible ? "eligible" : "future"}
              onClick={() => inspect(event.evidence_id)}
            >
              <time>
                {clock(event.time)}
                <small>UTC</small>
              </time>
              <i />
              <div>
                <strong>{event.resource}</strong>
                <span>
                  {human(event.system)} · {label(event.state)}
                </span>
              </div>
              <small>{event.eligible ? "Eligible" : "Beyond cutoff"}</small>
              <ArrowUpRight size={13} />
            </button>
          ))}
        </div>
      ) : (
        <div className="wf-findings">
          <div>
            <State value={view.answer.deletion_status} />
            <p>
              {view.answer.steps.filter((s) => s.phase === "FINDING").length}{" "}
              findings · {view.context.resource_states.length} reconstructed
              resources · {view.context.eligible_observation_ids.length}{" "}
              eligible observations
            </p>
          </div>
          {view.answer.steps
            .filter((s) => s.phase === "FINDING")
            .map((s) => (
              <button key={s.step_no} onClick={() => inspect(s.evidence_id)}>
                <span>{human(s.operation)}</span>
                <code>
                  {s.system_id}/{s.resource_id}
                </code>
                <FileText size={14} />
              </button>
            ))}
          {view.answer.trace?.not_certified_because?.map((reason) => (
            <p className="wf-uncertainty-note" key={reason}>
              {reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function EvidenceModal({
  runId,
  evidence,
  close,
}: {
  runId: string;
  evidence: { id: string; sandbox: string | null };
  close: () => void;
}) {
  const [data, setData] = useState<Record<string, unknown> | null>(null),
    [error, setError] = useState("");
  const panel = useRef<HTMLDivElement>(null),
    closeButton = useRef<HTMLButtonElement>(null);
  const base = evidence.sandbox
    ? `/api/workflow/sandboxes/${evidence.sandbox}/evidence/${encodeURIComponent(evidence.id)}`
    : `/api/workflow/runs/${runId}/evidence/${encodeURIComponent(evidence.id)}`;
  useEffect(() => {
    const c = new AbortController();
    const previous = document.activeElement as HTMLElement;
    closeButton.current?.focus();
    setData(null);
    setError("");
    api<Record<string, unknown>>(base, { signal: c.signal })
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => {
      c.abort();
      previous?.focus();
    };
  }, [base]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const elements = panel.current?.querySelectorAll<HTMLElement>(
          "button,a[href],iframe",
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [close]);
  return (
    <div
      className="wf-modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className="wf-evidence-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Evidence ${evidence.id}`}
        ref={panel}
      >
        <header>
          <span className="wf-eyebrow">
            {evidence.sandbox ? "EXECUTION PROOF" : "ORIGINAL RUN EVIDENCE"}
          </span>
          <button ref={closeButton} aria-label="Close evidence" onClick={close}>
            <X size={20} />
          </button>
        </header>
        <h2>{evidence.id}</h2>
        {error ? (
          <p role="alert">{error}</p>
        ) : !data ? (
          <div className="wf-loading">Reading source…</div>
        ) : (
          <>
            <p>
              {String(data.scope ?? data.kind ?? "Evidence")} ·{" "}
              {data.at ? new Date(String(data.at)).toISOString() : ""}
            </p>
            {data.kind === "pdf" ? (
              <iframe title="Original PDF evidence" src={`${base}/raw`} />
            ) : data.kind === "image" ? (
              <img
                alt={`Original evidence ${evidence.id}`}
                src={`${base}/raw`}
              />
            ) : (
              <pre>
                {typeof data.content === "string"
                  ? data.content
                  : JSON.stringify(data, null, 2)}
              </pre>
            )}
            <div className="wf-proof-hash">
              <span>SHA-256</span>
              <code>
                {String(data.sha256 ?? "Structured row; no file hash")}
              </code>
            </div>
            {!evidence.sandbox && (
              <a href={`${base}/raw`} target="_blank" rel="noreferrer">
                Open original source <ArrowUpRight size={13} />
              </a>
            )}
          </>
        )}
      </div>
    </div>
  );
}
