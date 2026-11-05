import { ArrowUpRight, FileText, X, Clock3 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clock, loadEvidence } from "./api";
import type { AuditCase, EvidenceDetail } from "./types";
import { SceneLoading } from "./Presentation";

export function Status({ value }: { value: string }) {
  const tone =
    /COMPLETE|PASSED|verified|parsed|ABSENT|REDACTED/.test(value) &&
    !value.includes("INCOMPLETE")
      ? "lime"
      : /CONFLICT|INCOMPLETE|NOT SATISFIED|IDENTIFIABLE|PRESENT|failed/.test(
            value,
          )
        ? "coral"
        : "muted";
  return (
    <span className={`status ${tone}`}>
      <i />
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function EvidenceLink({
  id,
  onOpen,
}: {
  id: string;
  onOpen: (id: string) => void;
}) {
  return (
    <button
      className="evidence-link"
      onClick={() => onOpen(id)}
      aria-label={`Inspect evidence ${id}`}
    >
      <FileText size={12} />
      {id}
      <ArrowUpRight size={12} />
    </button>
  );
}
export function SectionLabel({
  number,
  children,
}: {
  number: string;
  children: React.ReactNode;
}) {
  return (
    <div className="eyebrow">
      <span>{number}</span>
      <i />
      {children}
    </div>
  );
}
export function TimeControl({
  data,
  onChange,
}: {
  data: AuditCase;
  onChange: (time: string) => void;
}) {
  const times = data.events.map((e) => Date.parse(e.time));
  const min = Math.min(Date.parse(data.request.requested_at), ...times),
    max = Math.max(Date.parse(data.request.audit_at), ...times) + 3600000;
  const current = Date.parse(data.request.audit_at);
  const [value, setValue] = useState(current);
  useEffect(() => setValue(current), [current]);
  return (
    <div className="time-control">
      <span>
        <Clock3 size={13} />
        AT TIME <b>{clock(new Date(value).toISOString())} UTC</b>
      </span>
      <input
        aria-label="Identity history cutoff"
        type="range"
        min={min}
        max={max}
        step={60000}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        onPointerUp={() => onChange(new Date(value).toISOString())}
        onKeyUp={(e) => {
          if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End")
            onChange(new Date(value).toISOString());
        }}
      />
      <small>Relationships retain their evidence and validity interval.</small>
    </div>
  );
}
export function EvidenceDrawer({
  id,
  data,
  onClose,
}: {
  id: string;
  data: AuditCase;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null),
    [error, setError] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const c = new AbortController();
    setDetail(null);
    setError("");
    loadEvidence(id, data.case_id, data.mode, c.signal)
      .then(setDetail)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => {
      c.abort();
      previous?.focus();
    };
  }, [id, data.case_id, data.mode]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const all = panel.current?.querySelectorAll<HTMLElement>(
          "button,a[href],input",
        );
        if (!all?.length) return;
        const first = all[0],
          last = all[all.length - 1];
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
  }, [onClose]);
  const raw = `/api/evidence/${encodeURIComponent(id)}/raw?${new URLSearchParams({ case_id: data.case_id, mode: data.mode })}`;
  return (
    <div
      className="drawer-shade"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="evidence-drawer"
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={`Source evidence ${id}`}
      >
        <div className="drawer-heading">
          <span className="eyebrow">TRACE LENS / ORIGINAL SOURCE</span>
          <button
            className="icon-button"
            ref={close}
            onClick={onClose}
            aria-label="Close evidence"
          >
            <X size={20} />
          </button>
        </div>
        <h2>{id}</h2>
        {error ? (
          <p role="alert" className="error-message">
            {error}
          </p>
        ) : !detail ? (
          <SceneLoading source />
        ) : (
          <>
            <div className="source-metadata">
              <span>{detail.format}</span>
              <span>{clock(detail.captured_at)} UTC</span>
              <Status
                value={
                  Date.parse(detail.captured_at) <=
                  Date.parse(data.request.audit_at)
                    ? "ELIGIBLE"
                    : "BEYOND CUTOFF"
                }
              />
            </div>
            <p className="subtle">{detail.locator}</p>
            {!!detail.locators?.length && (
              <p className="fine-print">
                Extraction locations: {detail.locators.slice(0, 12).join(" · ")}
              </p>
            )}
            {detail.truncated && (
              <p className="error-message">
                Partial preview (first 128 KiB). Open the original source for
                its full contents.
              </p>
            )}
            <div className="paper-source">
              {detail.format === "PDF" ? (
                <iframe
                  title="Original PDF evidence"
                  src={`${raw}#page=${detail.pdf_page ?? 1}`}
                />
              ) : detail.format === "IMAGE" ? (
                <img alt={`Original source ${id}`} src={raw} />
              ) : (
                <pre>
                  {detail.content.split("\n").map((line, i) => (
                    <span
                      className={
                        /"state"|"resource_id"/.test(line)
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
              )}
            </div>
            <p className="mono hash">
              SHA-256
              <br />
              {detail.sha256 ??
                "No source hash is available for this structured row."}
            </p>
            <a
              className="text-link"
              href={raw}
              target="_blank"
              rel="noreferrer"
            >
              {detail.format === "CSV" && !detail.raw_available
                ? "Open structured record"
                : "Open original source"}{" "}
              <ArrowUpRight size={14} />
            </a>
            <p className="fine-print">
              {data.mode === "demo" ? "Fictional demonstration evidence. " : ""}
              Inspection does not modify the source.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
