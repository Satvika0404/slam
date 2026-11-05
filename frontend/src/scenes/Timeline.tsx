import { useRef, useState } from "react";
import { ArrowDownRight, Clock3, Minus, Plus, Scale } from "lucide-react";
import { clock, label } from "../api";
import { EvidenceLink, SectionLabel, Status } from "../components";
import type { SceneProps } from "../types";
import { EmptyField } from "../Presentation";
export default function Timeline({
  data,
  onEvidence,
  onCutoff,
  loading,
}: SceneProps) {
  const [preview, setPreview] = useState<number | null>(null),
    [selected, setSelected] = useState(
      data.events[3]?.id ?? data.events[0]?.id ?? "",
    ),
    [zoom, setZoom] = useState(1),
    [compare, setCompare] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const allTimes = data.events.map((e) => Date.parse(e.time));
  const fullMin =
      Math.min(Date.parse(data.request.requested_at), ...allTimes) - 1800000,
    fullMax =
      Math.max(Date.parse(data.request.audit_at), ...allTimes) + 3600000;
  const cutoff = preview ?? Date.parse(data.request.audit_at);
  const width = (fullMax - fullMin) / zoom;
  const min = Math.max(
      fullMin,
      Math.min(
        fullMax - width,
        Date.parse(data.request.audit_at) - width * 0.65,
      ),
    ),
    max = min + width;
  const x = (time: number) => 160 + ((time - min) / (max - min)) * 790;
  const systems = [...new Set(data.events.map((e) => e.system))];
  const event = data.events.find((e) => e.id === selected);
  const before = event
    ? data.events
        .filter((e) => e.resource === event.resource && e.id !== event.id)
        .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))[0]
    : undefined;
  const ticks = Array.from(
    { length: 7 },
    (_, i) => min + ((max - min) * i) / 6,
  );
  function fromPointer(clientX: number) {
    const rect = svg.current!.getBoundingClientRect();
    return Math.max(
      fullMin,
      Math.min(
        fullMax,
        min +
          ((((clientX - rect.left) * 1000) / rect.width - 160) / 790) *
            (max - min),
      ),
    );
  }
  return (
    <section className="timeline-scene">
      <div className="scene-heading">
        <div>
          <SectionLabel number="05">THE TIME MACHINE</SectionLabel>
          <h1>
            The truth has
            <br />
            <em>a timestamp.</em>
          </h1>
        </div>
        <p className="heading-aside">
          Move the boundary.
          <br />
          Reconstruct what was known.<span>LATER EVIDENCE STAYS VISIBLE.</span>
        </p>
      </div>
      {!data.events.length && (
        <EmptyField title="No timeline has been established.">
          No subject observations are available. The empty time landscape is not
          evidence of deletion.
        </EmptyField>
      )}
      <div className="timeline-topline">
        <span className="small-label">
          {new Date(data.request.audit_at)
            .toLocaleDateString("en-GB", {
              day: "2-digit",
              month: "long",
              year: "numeric",
              timeZone: "UTC",
            })
            .toUpperCase()}{" "}
          · ALL TIMES UTC{data.mode === "dataset" ? " · SOURCE TIMESTAMPS" : ""}
        </span>
        <div className="timeline-zoom">
          <button
            className="icon-button"
            aria-label="Zoom timeline out"
            onClick={() => setZoom((z) => Math.max(1, z / 2))}
          >
            <Minus size={15} />
          </button>
          <span>{zoom}×</span>
          <button
            className="icon-button"
            aria-label="Zoom timeline in"
            onClick={() => setZoom((z) => Math.min(4, z * 2))}
          >
            <Plus size={15} />
          </button>
        </div>
      </div>
      <div className="time-landscape">
        <svg
          ref={svg}
          viewBox={`0 0 1000 ${systems.length * 100 + 90}`}
          role="group"
          aria-label="System events and audit cutoff"
          onPointerMove={(e) => {
            if (dragging.current) setPreview(fromPointer(e.clientX));
          }}
          onPointerUp={(e) => {
            if (dragging.current) {
              dragging.current = false;
              const value = fromPointer(e.clientX);
              setPreview(null);
              onCutoff(new Date(value).toISOString());
            }
          }}
        >
          <defs>
            <linearGradient id="future">
              <stop stopColor="#090d14" stopOpacity=".25" />
              <stop offset="1" stopColor="#090d14" stopOpacity=".65" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={x(t)}
                x2={x(t)}
                y1="48"
                y2={systems.length * 100 + 45}
                className="timeline-grid"
              />
              <text
                x={x(t)}
                y="25"
                className="timeline-tick"
                textAnchor="middle"
              >
                {clock(new Date(t).toISOString())}
              </text>
            </g>
          ))}
          {systems.map((system, i) => (
            <g key={system}>
              <text x="0" y={i * 100 + 90} className="system-label">
                {label(system).split(" ")[0]}
              </text>
              <text x="0" y={i * 100 + 109} className="system-detail">
                {label(system).split(" ").slice(1).join(" ") || "SYSTEM"}
              </text>
              <line
                x1="160"
                x2="960"
                y1={i * 100 + 90}
                y2={i * 100 + 90}
                className="system-track"
              />
              {data.events
                .filter(
                  (e) =>
                    e.system === system &&
                    Date.parse(e.time) >= min &&
                    Date.parse(e.time) <= max,
                )
                .map((e) => (
                  <g
                    key={e.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${label(e.system)}, ${e.state}, ${clock(e.time)} UTC, ${e.eligible ? "eligible" : "beyond cutoff"}`}
                    className={`timeline-event ${e.eligible ? "eligible" : "future"} ${selected === e.id ? "selected" : ""}`}
                    onClick={() => setSelected(e.id)}
                    onKeyDown={(key) => {
                      if (key.key === "Enter" || key.key === " ") {
                        key.preventDefault();
                        setSelected(e.id);
                      }
                    }}
                  >
                    <circle
                      cx={x(Date.parse(e.time))}
                      cy={i * 100 + 90}
                      r="17"
                      className="event-halo"
                    />
                    <path
                      d={`M ${x(Date.parse(e.time))} ${i * 100 + 82} l 8 8 -8 8 -8 -8Z`}
                      className={`event-diamond ${e.state === "ABSENT" || e.state === "REDACTED" ? "compliant" : ""}`}
                    />
                    <text
                      x={x(Date.parse(e.time))}
                      y={i * 100 + 126}
                      textAnchor="middle"
                      className="event-state"
                    >
                      {e.state}
                    </text>
                  </g>
                ))}
            </g>
          ))}
          {x(cutoff) >= 160 && x(cutoff) <= 950 && (
            <>
              <rect
                x={x(cutoff)}
                y="46"
                width={960 - x(cutoff)}
                height={systems.length * 100}
                fill="url(#future)"
                pointerEvents="none"
              />
              <g
                className="audit-boundary"
                role="slider"
                tabIndex={0}
                aria-label="Drag audit cutoff"
                aria-valuemin={Math.round(fullMin)}
                aria-valuemax={Math.round(fullMax)}
                aria-valuenow={cutoff}
                aria-valuetext={`${clock(new Date(cutoff).toISOString())} UTC`}
                onPointerDown={(e) => {
                  dragging.current = true;
                  svg.current?.setPointerCapture(e.pointerId);
                }}
                onKeyDown={(e) => {
                  let next = cutoff;
                  if (e.key === "ArrowLeft") next -= 900000;
                  else if (e.key === "ArrowRight") next += 900000;
                  else if (e.key === "Home") next = fullMin;
                  else if (e.key === "End") next = fullMax;
                  else return;
                  e.preventDefault();
                  onCutoff(
                    new Date(
                      Math.max(fullMin, Math.min(fullMax, next)),
                    ).toISOString(),
                  );
                }}
              >
                <line
                  x1={x(cutoff)}
                  x2={x(cutoff)}
                  y1="40"
                  y2={systems.length * 100 + 55}
                  className="cutoff-light"
                />
                <line
                  x1={x(cutoff)}
                  x2={x(cutoff)}
                  y1="35"
                  y2={systems.length * 100 + 60}
                  className="cutoff-hit"
                />
                <rect
                  x={x(cutoff) - 49}
                  y={systems.length * 100 + 47}
                  width="98"
                  height="26"
                  rx="4"
                />
                <text
                  x={x(cutoff)}
                  y={systems.length * 100 + 65}
                  textAnchor="middle"
                >
                  {clock(new Date(cutoff).toISOString())} / AUDIT
                </text>
                <path d={`M${x(cutoff) - 7} 35h14l-7 9Z`} />
              </g>
            </>
          )}
        </svg>
        <div className="timeline-slider">
          <span>CAPTURED EVIDENCE</span>
          <input
            type="range"
            aria-label="Audit cutoff time"
            min={fullMin}
            max={fullMax}
            step={60000}
            value={cutoff}
            onChange={(e) => setPreview(Number(e.target.value))}
            onPointerUp={(e) => {
              onCutoff(new Date(Number(e.currentTarget.value)).toISOString());
              setPreview(null);
            }}
            onKeyUp={(e) => {
              if (
                e.key.startsWith("Arrow") ||
                e.key === "Home" ||
                e.key === "End"
              ) {
                onCutoff(new Date(Number(e.currentTarget.value)).toISOString());
                setPreview(null);
              }
            }}
          />
          <span>BEYOND CUTOFF</span>
        </div>
      </div>
      <div className="timeline-bottom">
        <div className="event-inspector">
          <div className="inspector-kicker">
            <Clock3 size={14} />
            OBSERVATION DETAIL{" "}
            <button
              className={compare ? "text-link lime-text" : "text-link"}
              onClick={() => setCompare((v) => !v)}
            >
              <Scale size={13} />
              {compare ? "Hide comparison" : "Compare observations"}
            </button>
          </div>
          <select
            className="event-picker"
            aria-label="Inspect any timeline observation"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {data.events.map((e) => (
              <option key={e.id} value={e.id}>
                {clock(e.time)} / {label(e.system)} / {e.state}
              </option>
            ))}
          </select>
          {event && (
            <div className="event-detail">
              <div>
                <span className="big-clock">
                  {clock(event.time)}
                  <small>UTC</small>
                </span>
                <Status value={event.state} />
              </div>
              <p>
                {event.resource}
                <small>
                  {event.eligible
                    ? "Eligible: observed and captured at or before the selected audit cutoff."
                    : "Excluded: this observation was observed or captured after the selected audit cutoff."}
                </small>
              </p>
              <EvidenceLink id={event.evidence_id} onOpen={onEvidence} />
            </div>
          )}
          {compare && before && (
            <div className="comparison-row">
              <span>OTHER OBSERVATION</span>
              <b>
                {clock(before.time)} / {before.state}
              </b>
              <EvidenceLink id={before.evidence_id} onOpen={onEvidence} />
            </div>
          )}
        </div>
        <aside className="state-snapshot">
          <div className="inspector-kicker">
            <ArrowDownRight size={15} />
            RECONSTRUCTED AT {clock(data.request.audit_at)} UTC{" "}
            {loading && <span>UPDATING</span>}
          </div>
          {data.context.resource_states.map((state) => (
            <div
              className="resource-state"
              key={state.system_id + state.resource_id}
            >
              <span>
                {label(state.system_id)}
                <small>{state.resource_id}</small>
              </span>
              <Status value={state.uncertain ? "CONFLICT" : state.state} />
            </div>
          ))}
          <p className="fine-print">
            Recomputed by Python from eligible evidence. The boundary does not
            execute deletion.
          </p>
        </aside>
      </div>
    </section>
  );
}
