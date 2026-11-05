import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import type { InspectEvidence } from "./types";

export function ConsolePanel({
  title,
  number,
  note,
  children,
  tools,
  className = "",
}: {
  title: string;
  number: string;
  note?: string;
  children: ReactNode;
  tools?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`intel-panel ${className}`}>
      <header className="intel-panel-head">
        <div>
          <span className="intel-index">{number}</span>
          <h2>{title}</h2>
          {note && <p>{note}</p>}
        </div>
        {tools}
      </header>
      <div className="intel-panel-content">{children}</div>
    </section>
  );
}
export function EvidenceRefs({
  ids,
  onInspect,
  context,
}: {
  ids: string[];
  onInspect: InspectEvidence;
  context?: string;
}) {
  return (
    <div className="intel-evidence">
      {ids.length ? (
        ids.map((id) => (
          <button
            key={id}
            onClick={() => onInspect(id, context)}
            aria-label={`Inspect ${id}`}
          >
            {id}
            <ArrowUpRight size={11} />
          </button>
        ))
      ) : (
        <span>No individual citation supplied.</span>
      )}
    </div>
  );
}
export function ConsoleEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="intel-empty">
      <span aria-hidden="true">∅</span>
      <p>{children}</p>
    </div>
  );
}
export function ConsoleStats({
  items,
}: {
  items: { label: string; value: string; note: string; tone?: string }[];
}) {
  return (
    <div className="intel-stats">
      {items.map((s, i) => (
        <div key={s.label} style={{ animationDelay: `${i * 45}ms` }}>
          <span>{s.label}</span>
          <b className={s.tone ?? ""}>{s.value}</b>
          <p>{s.note}</p>
        </div>
      ))}
    </div>
  );
}
