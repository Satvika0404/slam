import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useState,
  useRef,
  Component,
} from "react";
import { flushSync } from "react-dom";
import type { ErrorInfo, ReactNode } from "react";
import {
  Asterisk,
  Orbit,
  Network,
  ScanLine,
  History,
  Triangle,
  BookOpen,
  FlaskConical,
  Command,
  ArrowUpRight,
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  X,
  RefreshCw,
  Activity,
  Radio,
} from "lucide-react";
import { loadCase, request } from "./api";
import { EvidenceDrawer, Status } from "./components";
import { RecoveryState, SceneLoading } from "./Presentation";
import type { AuditCase, Mode, Scene, SceneProps } from "./types";
const loaders = {
  identity: () => import("./scenes/Identity"),
  timeline: () => import("./scenes/Timeline"),
  decision: () => import("./scenes/Decision"),
  supporting: () => import("./scenes/Supporting"),
  console: () => import("./scenes/Console"),
  run: () => import("./scenes/Run"),
};
const Identity = lazy(loaders.identity);
const Timeline = lazy(loaders.timeline);
const Decision = lazy(loaders.decision);
const Supporting = lazy(loaders.supporting);
const Console = lazy(loaders.console);
const Run = lazy(loaders.run);
function preload(scene: Scene) {
  void (
    scene === "identity"
      ? loaders.identity()
      : scene === "timeline"
        ? loaders.timeline()
        : scene === "decision"
          ? loaders.decision()
          : scene === "run"
            ? loaders.run()
            : scene === "console"
              ? loaders.console()
              : loaders.supporting()
  ).catch(() => {});
}
const chapters: { id: Scene; name: string; icon: typeof Orbit }[] = [
  { id: "portal", name: "The portal", icon: Asterisk },
  { id: "sources", name: "Source nebula", icon: Orbit },
  { id: "identity", name: "Identity constellation", icon: Network },
  { id: "desk", name: "Forensic desk", icon: ScanLine },
  { id: "timeline", name: "Time machine", icon: History },
  { id: "decision", name: "Decision chamber", icon: Triangle },
  { id: "folio", name: "Audit folio", icon: BookOpen },
  { id: "observatory", name: "Experiment observatory", icon: FlaskConical },
  { id: "console", name: "Intelligence console", icon: Activity },
  { id: "run", name: "Live backend execution", icon: Radio },
];
class Boundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info);
  }
  render() {
    return this.state.error ? (
      <div className="empty-state">
        <h2>This scene could not be displayed.</h2>
        <p>Your evidence remains unchanged. Reload to retry.</p>
        <button onClick={() => location.reload()}>Reload workspace</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
export default function App() {
  const [scene, setScene] = useState<Scene>("portal"),
    [mode, setMode] = useState<Mode>("demo"),
    [caseId, setCaseId] = useState("demo_024"),
    [cutoff, setCutoff] = useState<string | null>(null),
    [data, setData] = useState<AuditCase | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [cases, setCases] = useState<
      { case_id: string; name: string; label: string }[]
    >([]),
    [evidence, setEvidence] = useState<string | null>(null),
    [evidenceData, setEvidenceData] = useState<AuditCase | null>(null),
    [palette, setPalette] = useState(false),
    [search, setSearch] = useState(""),
    [story, setStory] = useState(false),
    [playing, setPlaying] = useState(false),
    [consoleOpened, setConsoleOpened] = useState(false),
    [runOpened, setRunOpened] = useState(false),
    [run, setRun] = useState(false),
    [retryKey, setRetryKey] = useState(0),
    [runMessage, setRunMessage] = useState("");
  const transition = useRef<ViewTransition | null>(null);
  const navigationVersion = useRef(0);
  const runResults = useRef(new Map<string, AuditCase>());
  const resultKey = (view: AuditCase) =>
    `${view.mode}:${view.case_id}:${view.request.audit_at}`;
  useEffect(() => {
    if (scene === "console") setConsoleOpened(true);
    if (scene === "run") setRunOpened(true);
  }, [scene]);
  const navigate = useCallback(
    (next: Scene) => {
      if (next === scene) return;
      const version = ++navigationVersion.current;
      const update = () => {
        if (version !== navigationVersion.current) return;
        setScene(next);
        document.getElementById("main")?.focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: "instant" });
      };
      transition.current?.skipTransition();
      if (
        typeof document.startViewTransition === "function" &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ) {
        document.documentElement.dataset.sceneMotion = "active";
        const current = document.startViewTransition(() => flushSync(update));
        transition.current = current;
        void current.finished
          .catch(() => {})
          .then(() => {
            if (transition.current === current)
              delete document.documentElement.dataset.sceneMotion;
          });
      } else update();
    },
    [scene],
  );
  useEffect(() => {
    const controller = new AbortController();
    request<typeof cases>(`/api/cases?mode=${mode}`, controller.signal)
      .then((list) => {
        setCases(list);
        if (!list.some((c) => c.case_id === caseId) && list[0]) {
          setCaseId(list[0].case_id);
          setCutoff(null);
        }
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setCases([]);
          setError(e.message);
        }
      });
    return () => controller.abort();
  }, [mode, caseId, retryKey]);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError("");
    (cutoff && runResults.current.has(`${mode}:${caseId}:${cutoff}`)
      ? Promise.resolve(runResults.current.get(`${mode}:${caseId}:${cutoff}`)!)
      : loadCase(caseId, mode, cutoff, c.signal)
    )
      .then((value) => {
        setData(value);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setData(null);
          setLoading(false);
        }
      });
    return () => c.abort();
  }, [caseId, mode, cutoff, retryKey]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
      if (e.key === "Escape") {
        setPalette(false);
        setStory(false);
        setPlaying(false);
      }
    }
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!palette) return;
    function trap(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const items = document.querySelectorAll<HTMLElement>(
        ".command-palette input, .command-palette button",
      );
      const first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
    document.addEventListener("keydown", trap);
    return () => document.removeEventListener("keydown", trap);
  }, [palette]);
  useEffect(() => {
    if (!story || !playing) return;
    const timer = setInterval(() => {
      setScene((old) => {
        const i = chapters.findIndex((c) => c.id === old);
        if (i === chapters.length - 1) {
          setPlaying(false);
          return old;
        }
        return chapters[i + 1].id;
      });
    }, 10000);
    return () => clearInterval(timer);
  }, [story, playing]);
  const closeEvidence = useCallback(() => {
    setEvidence(null);
    setEvidenceData(null);
  }, []);
  const openEvidence = useCallback((id: string) => {
    setEvidenceData(null);
    setEvidence(id);
  }, []);
  const props: SceneProps | null = data
    ? {
        data,
        loading,
        onEvidence: openEvidence,
        onScene: navigate,
        onCutoff: setCutoff,
      }
    : null;
  async function ingest() {
    setRun(true);
    setRunMessage("");
    try {
      const result = await request<{ message: string }>(
        "/api/runs?mode=" + mode,
        undefined,
        "POST",
      );
      setRunMessage(result.message);
      setCutoff(null);
      const c = new AbortController();
      setData(await loadCase(caseId, mode, null, c.signal));
    } catch (e) {
      setRunMessage((e as Error).message);
    } finally {
      setRun(false);
    }
  }
  return (
    <div
      className={`app-shell ${scene === "identity" || scene === "run" ? "identity-workspace" : ""}`}
    >
      <a className="skip-link" href="#main">
        Skip to investigation
      </a>
      <aside className="nav-rail" aria-label="Investigation chapters">
        <button
          className="brand-mark"
          onClick={() => navigate("portal")}
          aria-label="AFTERTRACE home"
        >
          <Asterisk size={29} />
        </button>
        <nav>
          {chapters.map((item, index) => (
            <button
              key={item.id}
              className={scene === item.id ? "nav-item active" : "nav-item"}
              aria-label={item.name}
              aria-current={scene === item.id ? "page" : undefined}
              title={`${String(index + 1).padStart(2, "0")} · ${item.name}`}
              onClick={() => navigate(item.id)}
              onPointerEnter={() => preload(item.id)}
              onFocus={() => preload(item.id)}
            >
              <item.icon size={19} />
              <span className="nav-index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="nav-tooltip">{item.name}</span>
            </button>
          ))}
        </nav>
        <button
          className="nav-item command-button"
          aria-label="Open command palette"
          onClick={() => setPalette(true)}
        >
          <Command size={18} />
        </button>
        <span className="rail-foot">AT / 01</span>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button className="wordmark" onClick={() => navigate("portal")}>
            AFTERTRACE<span>®</span>
          </button>
          <div className="header-divider" />
          <span className="workspace-name">EVIDENCE WORKSPACE</span>
          <div className="header-right">
            <button
              className="presentation-button live-execution-button"
              onClick={() => navigate("run")}
            >
              <Radio size={14} />
              Run live
            </button>
            <label className="mode-control">
              <span className={mode === "demo" ? "demo-dot" : "live-dot"} />
              <select
                aria-label="Data mode"
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as Mode);
                  setData(null);
                  setCutoff(null);
                  setRunMessage("");
                }}
              >
                <option value="demo">FICTIONAL DEMO</option>
                <option value="dataset">LOCAL DATASET</option>
              </select>
            </label>
            <button
              className="presentation-button"
              onClick={() => {
                setStory(true);
                navigate("portal");
                setPlaying(false);
              }}
            >
              <Play size={13} />
              Present case
            </button>
            <button
              className="header-command"
              onClick={() => setPalette(true)}
              aria-label="Open navigation search"
            >
              ⌘ K
            </button>
          </div>
        </header>
        <div className="case-bar">
          <span className="case-chip">
            INVESTIGATION / {caseId.replace("demo_", "D—")}
          </span>
          <select
            aria-label="Select investigation case"
            value={cases.some((c) => c.case_id === caseId) ? caseId : ""}
            onChange={(e) => {
              setCaseId(e.target.value);
              setCutoff(null);
              setEvidence(null);
            }}
          >
            {!cases.length && <option value="">No cases available</option>}
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.name} · {c.label}
              </option>
            ))}
          </select>
          <span className="case-bar-right">
            {loading ? (
              <span className="busy" role="status">
                <i className="request-pulse" aria-hidden="true" />
                RECONSTRUCTING STATE
              </span>
            ) : data ? (
              <>
                <span className="source-indicator" />
                PYTHON ENGINE CONNECTED
              </>
            ) : (
              <span className="coral-text">DATA UNAVAILABLE</span>
            )}
            <button
              className="icon-button"
              title="Reload sources"
              aria-label="Reload sources"
              disabled={run}
              onClick={ingest}
            >
              <RefreshCw size={14} className={run ? "spin" : ""} />
            </button>
          </span>
        </div>
        {runMessage && (
          <div className="run-notice" role="status">
            {runMessage}
            <button
              onClick={() => setRunMessage("")}
              aria-label="Dismiss message"
            >
              <X size={14} />
            </button>
          </div>
        )}
        <main id="main" tabIndex={-1} aria-busy={loading}>
          {(scene === "run" || runOpened) && (
            <div hidden={scene !== "run"}>
              <Boundary>
                <Suspense fallback={<SceneLoading />}>
                  <div className="scene-wrap run-scene-wrap">
                    <Run
                      mode={mode}
                      caseId={caseId}
                      cutoff={cutoff}
                      onEvidence={(id, view) => {
                        setEvidenceData(view ?? null);
                        setEvidence(id);
                      }}
                      onScene={navigate}
                      onResult={(view) => {
                        runResults.current.set(resultKey(view), view);
                      }}
                      onOpen={(view) => {
                        runResults.current.set(resultKey(view), view);
                        setMode(view.mode);
                        setCaseId(view.case_id);
                        setCutoff(view.request.audit_at);
                        setData(view);
                        navigate("folio");
                      }}
                    />
                  </div>
                </Suspense>
              </Boundary>
            </div>
          )}
          {(scene === "console" || consoleOpened) && (
            <div hidden={scene !== "console"}>
              <Boundary>
                <Suspense fallback={<SceneLoading />}>
                  <div className="scene-wrap console-scene-wrap">
                    <Console
                      data={data}
                      loading={loading}
                      onEvidence={openEvidence}
                    />
                  </div>
                </Suspense>
              </Boundary>
            </div>
          )}
          {scene !== "console" && scene !== "run" && (
            <Boundary key={scene}>
              {error ? (
                <RecoveryState
                  error={error}
                  mode={mode}
                  onRetry={() => setRetryKey((v) => v + 1)}
                  onDemo={() => {
                    setMode("demo");
                    setCaseId("demo_024");
                    setCutoff(null);
                    setRetryKey((v) => v + 1);
                  }}
                />
              ) : !props ? (
                <SceneLoading />
              ) : (
                <Suspense fallback={<SceneLoading />}>
                  <div
                    className={`scene-wrap ${loading ? "reconstructing" : ""}`}
                    key={`${scene}:${props.data.case_id}:${props.data.mode}`}
                  >
                    {scene === "identity" ? (
                      <Identity {...props} />
                    ) : scene === "timeline" ? (
                      <Timeline {...props} />
                    ) : scene === "decision" ? (
                      <Decision {...props} />
                    ) : (
                      <Supporting {...props} scene={scene} />
                    )}
                  </div>
                </Suspense>
              )}
            </Boundary>
          )}
        </main>
        <footer className="workspace-footer">
          <span>
            <i className="tiny-cross" />
            EVERY ACTION LEAVES A TRACE.
          </span>
          <span>
            {scene === "console"
              ? "CONSOLE SOURCE / SEE ANALYSIS SELECTOR"
              : data
                ? `${data.sources.length} SOURCES · ${data.events.filter((e) => e.eligible).length} ELIGIBLE OBSERVATIONS`
                : "NO EVIDENCE LOADED"}
          </span>
          <span>
            {scene === "console" && "SELECTED CASE / "}
            {data ? (
              <Status value={data.answer.deletion_status ?? "UNVERIFIED"} />
            ) : (
              <span>NO RESULT</span>
            )}
          </span>
        </footer>
      </div>
      {evidence && (evidenceData || data) && (
        <EvidenceDrawer
          id={evidence}
          data={(evidenceData ?? data)!}
          onClose={closeEvidence}
        />
      )}{" "}
      {palette && (
        <div className="palette-backdrop" onClick={() => setPalette(false)}>
          <div
            className="command-palette"
            role="dialog"
            aria-modal="true"
            aria-label="Scene navigation"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              autoFocus
              placeholder="Where would you like to investigate?"
              aria-label="Search scenes"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {chapters
              .filter((c) =>
                c.name.toLowerCase().includes(search.toLowerCase()),
              )
              .map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    navigate(c.id);
                    setPalette(false);
                    setSearch("");
                  }}
                >
                  <c.icon size={17} />
                  {c.name}
                  <ArrowUpRight size={15} />
                </button>
              ))}
            {!chapters.some((c) =>
              c.name.toLowerCase().includes(search.toLowerCase()),
            ) && (
              <p className="palette-empty">
                No chapter matches. Try identity, time or evidence.
              </p>
            )}
          </div>
        </div>
      )}
      {story && (
        <div className="story-bar" aria-label="Investigation presentation">
          <span className="eyebrow">
            CASE STORY / {chapters.findIndex((c) => c.id === scene) + 1} OF{" "}
            {chapters.length}
          </span>
          <button
            aria-label="Previous story scene"
            onClick={() =>
              navigate(
                chapters[
                  Math.max(0, chapters.findIndex((c) => c.id === scene) - 1)
                ].id,
              )
            }
          >
            <ChevronLeft size={18} />
          </button>
          <button
            aria-label={playing ? "Pause story" : "Resume story"}
            onClick={() => setPlaying((v) => !v)}
          >
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </button>
          <button
            aria-label="Next story scene"
            onClick={() =>
              navigate(
                chapters[
                  Math.min(
                    chapters.length - 1,
                    chapters.findIndex((c) => c.id === scene) + 1,
                  )
                ].id,
              )
            }
          >
            <ChevronRight size={18} />
          </button>
          <b>{chapters.find((c) => c.id === scene)?.name}</b>
          <button
            aria-label="Exit presentation"
            onClick={() => {
              setStory(false);
              setPlaying(false);
            }}
          >
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}
