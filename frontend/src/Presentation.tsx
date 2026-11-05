import {
  ArrowUpRight,
  CircleDashed,
  FileSearch,
  RotateCcw,
  Unplug,
} from "lucide-react";
import type { ReactNode } from "react";

/** Presentation-only states. They never stand in for engine results. */
export function EmptyField({
  title,
  children,
  compact = false,
}: {
  title: string;
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty-field ${compact ? "compact" : ""}`}>
      <span className="empty-field-mark" aria-hidden="true">
        <FileSearch size={22} />
      </span>
      <div>
        <span className="small-label">INVESTIGATION / AWAITING EVIDENCE</span>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </div>
  );
}

export function SceneLoading({ source = false }: { source?: boolean }) {
  return (
    <div
      className={`scene-loading ${source ? "source-loading" : ""}`}
      role="status"
      aria-label={
        source ? "Loading source evidence" : "Loading investigation workspace"
      }
    >
      <div className="loading-instrument" aria-hidden="true">
        <i />
        <i />
        <i />
        <CircleDashed size={29} />
      </div>
      <div>
        <span className="small-label">
          {source ? "RETRIEVING ORIGINAL CONTENT" : "OPENING THE INVESTIGATION"}
        </span>
        <h2>
          {source ? "A trace, in context." : "Bringing the record into focus."}
        </h2>
        <p>
          {source
            ? "Waiting for the cited source to respond."
            : "Waiting for the workspace and its evidence. No audit result is assumed."}
        </p>
      </div>
      <span className="loading-caption">
        {source ? "SOURCE REQUEST IN PROGRESS" : "NO SIMULATED PROGRESS"}
      </span>
    </div>
  );
}

export function RecoveryState({
  error,
  mode,
  onRetry,
  onDemo,
}: {
  error: string;
  mode: string;
  onRetry: () => void;
  onDemo: () => void;
}) {
  return (
    <section className="recovery-scene">
      <div className="recovery-title">
        <span className="eyebrow">CONNECTION / INPUT UNAVAILABLE</span>
        <h1>
          Every finding needs
          <br />
          <em>a source.</em>
        </h1>
        <p className="recovery-intro">
          The investigation can wait.
          <br />
          The evidence cannot be assumed.
        </p>
        <div className="recovery-actions">
          <button className="primary-button" onClick={onRetry}>
            <RotateCcw size={15} />
            Retry connection
          </button>
          <button className="text-link" onClick={onDemo}>
            Open demonstration <ArrowUpRight size={15} />
          </button>
        </div>
      </div>
      <aside className="recovery-record">
        <span className="recovery-icon" aria-hidden="true">
          <Unplug size={30} />
        </span>
        <span className="small-label">
          INPUT STATUS / {mode === "demo" ? "FICTIONAL DEMO" : "LOCAL DATASET"}
        </span>
        <h2>
          A missing connection.
          <br />
          <em>An explicit boundary.</em>
        </h2>
        <p className="recovery-error" role="alert">
          {error}
        </p>
        <dl>
          <dt>What happened</dt>
          <dd>The requested evidence is unavailable.</dd>
          <dt>Next step</dt>
          <dd>
            {mode === "dataset"
              ? "Check the participant dataset and the local Python API, then retry."
              : "Check that the local Python API is running, then retry."}
          </dd>
          <dt>Audit outcome</dt>
          <dd>Not established.</dd>
        </dl>
      </aside>
    </section>
  );
}
