import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Database,
  FileCheck2,
  FileJson,
  GitBranch,
  ShieldAlert,
  X,
} from "lucide-react";
import snapshot from "../console/snapshot.json";
import provenance from "../console/provenance.json";
import type { AuditCase } from "../types";
import type { ConsoleData } from "../console/types";
import { date, fromCase, number } from "../console/model";
import Patterns from "../console/Patterns";
import Retention from "../console/Retention";
import SystemGraph from "../console/SystemGraph";
import { ConsolePanel } from "../console/Shared";
import "../console/console.css";

const imported = snapshot as ConsoleData;
const tabs = [
  { id: "patterns", name: "Error patterns", icon: Activity },
  { id: "retention", name: "Retention conflicts", icon: ShieldAlert },
  { id: "graph", name: "System graph", icon: GitBranch },
] as const;
type Tab = (typeof tabs)[number]["id"];
export default function Console({
  data,
  loading,
  onEvidence,
}: {
  data: AuditCase | null;
  loading: boolean;
  onEvidence: (id: string) => void;
}) {
  const [source, setSource] = useState("snapshot"),
    [originalGraph, setOriginalGraph] = useState(false),
    [tab, setTab] = useState<Tab>("patterns"),
    [citation, setCitation] = useState<{ id: string; context?: string } | null>(
      null,
    );
  const citationTitle = useRef<HTMLHeadingElement>(null);
  const citationTrigger = useRef<HTMLElement | null>(null);
  const current = useMemo(() => (data ? fromCase(data) : null), [data]);
  const isImported = source === "snapshot",
    view = isImported ? imported : current;
  useEffect(() => {
    setCitation(null);
  }, [source, data?.case_id, data?.mode]);
  useEffect(() => {
    if (citation) {
      citationTitle.current?.focus({ preventScroll: true });
      citationTitle.current?.scrollIntoView({
        block: "nearest",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
    }
  }, [citation]);
  const inspect = (id: string, context?: string) => {
    if (isImported) {
      citationTrigger.current = document.activeElement as HTMLElement;
      setCitation({ id, context });
    } else onEvidence(id);
  };
  const related = citation
    ? {
        patterns: imported.patterns
          .filter((p) => p.examples.includes(citation.id))
          .map((p) => ({
            id: p.id,
            title: p.name,
            reported_count: p.count,
            interpretation: p.note,
          })),
        register: imported.register.filter((r) => r.ev.includes(citation.id)),
        replica_snapshots: imported.drift.filter(
          (r) => r.file_id === citation.id,
        ),
      }
    : null;
  const counts = view
    ? [view.patterns.length, view.register.length, view.graph.nodes.length]
    : [0, 0, 0];
  return (
    <section
      className="intelligence-console"
      aria-label="Ghost Data intelligence console"
    >
      <header className="intel-heading">
        <div>
          <span className="eyebrow">
            <span>09</span> THE INTELLIGENCE CONSOLE
          </span>
          <h1>
            Read the pattern.
            <br />
            <em>Anticipate the return.</em>
          </h1>
          <p>
            From individual evidence to the systems that let data persist.
            <br />
            Inspect the signal. Respect the policy. Rehearse the consequences.
          </p>
        </div>
        <div className="intel-source-picker">
          <FileJson size={21} />
          <label>
            Analysis source
            <select
              value={source}
              aria-label="Console analysis source"
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="snapshot">Imported console snapshot</option>
              <option value="case" disabled={!data}>
                Current investigation
              </option>
            </select>
          </label>
          <span>
            {isImported
              ? "USER-SUPPLIED ANALYSIS"
              : data?.mode === "demo"
                ? "FICTIONAL DEMO · REAL ENGINE"
                : "PARTICIPANT DATASET · REAL ENGINE"}
          </span>
        </div>
      </header>
      <div
        className={`intel-provenance-strip ${isImported ? "is-imported" : ""}`}
      >
        <FileCheck2 size={17} />
        <div>
          <strong>
            {isImported
              ? "Imported snapshot · 01 Oct 2026"
              : `Case ${data?.case_id} · ${view ? date(view.meta.as_of) : "No case loaded"}`}
          </strong>
          <p>
            {isImported
              ? "Figures and forecasts come from your HTML file. Original dataset files and the calculation script were not supplied; these figures do not support current audit decisions."
              : "Uses the selected case and its audit cutoff. Unavailable corpus statistics stay empty; imported figures are never substituted."}
          </p>
        </div>
        <button
          onClick={() =>
            document.getElementById("intel-provenance")?.scrollIntoView({
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
            })
          }
        >
          Source record
          <ArrowUpRight size={14} />
        </button>
      </div>
      {!isImported && loading && (
        <p className="intel-loading-note" role="status">
          Reconstructing the selected investigation. The previous read model
          remains visible until the response arrives.
        </p>
      )}
      <div
        className="intel-tabs"
        role="tablist"
        aria-label="Intelligence console views"
      >
        {tabs.map((t, i) => (
          <button
            key={t.id}
            id={`intel-tab-${t.id}`}
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`intel-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => {
              const delta =
                e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
              if (!delta && e.key !== "Home" && e.key !== "End") return;
              e.preventDefault();
              const next =
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? tabs.length - 1
                    : (i + delta + tabs.length) % tabs.length;
              setTab(tabs[next].id);
              document.getElementById(`intel-tab-${tabs[next].id}`)?.focus();
            }}
          >
            <t.icon size={17} />
            <span>{t.name}</span>
            <b>{counts[i]}</b>
          </button>
        ))}
      </div>
      {citation && (
        <aside
          className="intel-citation"
          role="region"
          aria-label="Imported citation inspector"
        >
          <header>
            <div>
              <span className="intel-label">
                IMPORTED CITATION / SOURCE NOT ATTACHED
              </span>
              <h2 ref={citationTitle} tabIndex={-1}>
                {citation.id}
              </h2>
            </div>
            <button
              aria-label="Close imported citation"
              onClick={() => {
                setCitation(null);
                citationTrigger.current?.focus();
              }}
            >
              <X size={18} />
            </button>
          </header>
          <p>{citation.context}</p>
          <p>
            This ID is referenced by the supplied HTML. The original evidence
            file or activity row is not included in that attachment, so its
            contents, capture hash and claims cannot be verified here.
          </p>
          <details open>
            <summary>Inspect the supplied aggregate references</summary>
            <pre>{JSON.stringify(related, null, 2)}</pre>
          </details>
        </aside>
      )}
      {view ? (
        <div
          key={
            source +
            (!isImported
              ? `${data?.mode}:${data?.case_id}:${data?.request.audit_at}`
              : "")
          }
        >
          <div
            role="tabpanel"
            id="intel-panel-patterns"
            aria-labelledby="intel-tab-patterns"
            hidden={tab !== "patterns"}
          >
            <Patterns data={view} onInspect={inspect} imported={isImported} />
          </div>
          <div
            role="tabpanel"
            id="intel-panel-retention"
            aria-labelledby="intel-tab-retention"
            hidden={tab !== "retention"}
          >
            <Retention data={view} onInspect={inspect} imported={isImported} />
          </div>
          <div
            role="tabpanel"
            id="intel-panel-graph"
            aria-labelledby="intel-tab-graph"
            hidden={tab !== "graph"}
          >
            {isImported && (
              <div className="original-graph-switch">
                <button
                  onClick={() => setOriginalGraph((v) => !v)}
                  aria-pressed={originalGraph}
                >
                  {originalGraph
                    ? "Return to native console graph"
                    : "Open preserved original HTML graph"}
                </button>
                <span>
                  Original node-link JSON, SVG renderer and handlers retained.
                </span>
              </div>
            )}
            {isImported && originalGraph ? (
              <iframe
                className="original-graph-frame"
                title="Preserved original Ghost Data graph"
                src="/reference/ghost-data-console.html?embed=graph#graph"
                sandbox="allow-scripts allow-same-origin"
              />
            ) : (
              <SystemGraph data={view} onInspect={inspect} />
            )}
          </div>
        </div>
      ) : (
        <div className="intel-empty">
          <Database size={30} />
          <p>
            The current investigation is unavailable. Choose the imported
            snapshot or reconnect the dataset.
          </p>
        </div>
      )}
      <div id="intel-provenance" className="intel-source-record">
        <ConsolePanel
          number="SOURCE"
          title="Know what the numbers know"
          note="Analysis provenance stays visible, including the limits of the supplied inputs."
        >
          <div className="intel-provenance-grid">
            <div>
              <span className="intel-label">
                {isImported ? "ORIGINAL ATTACHMENT" : "CURRENT READ MODEL"}
              </span>
              <h3>{isImported ? provenance.filename : data?.case_id}</h3>
              <p>
                {isImported
                  ? provenance.scope
                  : "Derived from SLAM’s case response at the selected audit cutoff. Graph changes are local simulations, never written back to the case."}
              </p>
              <span className="intel-label">
                {isImported
                  ? "SHA-256 OF ORIGINAL HTML"
                  : "CASE RESPONSE FINGERPRINT"}
              </span>
              <code>{isImported ? provenance.sha256 : data?.fingerprint}</code>
            </div>
            <dl className="intel-dl">
              <dt>Analysis cutoff</dt>
              <dd>{view ? date(view.meta.as_of) : "Unavailable"}</dd>
              <dt>Reported activity events</dt>
              <dd>{isImported ? number(view?.meta.events) : "Not exposed"}</dd>
              <dt>Evidence sources</dt>
              <dd>{number(view?.meta.evidence_files)}</dd>
              <dt>Policy rules</dt>
              <dd>{number(view?.meta.rules)}</dd>
              <dt>Source graph</dt>
              <dd>
                {view?.graph.nodes.length ?? 0} systems ·{" "}
                {view?.graph.edges.length ?? 0} links
              </dd>
              <dt>Forecast validation</dt>
              <dd>Not established</dd>
            </dl>
          </div>
        </ConsolePanel>
      </div>
    </section>
  );
}
