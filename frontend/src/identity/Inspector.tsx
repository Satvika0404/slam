import { ArrowUpRight, CheckCircle2, Focus, ShieldAlert } from "lucide-react";
import { EvidenceLink, TimeControl } from "../components";
import { label } from "../api";
import { edgeStatus, fullTime, isEnded, statusName } from "./model";
import type { IdentityEdge, SceneProps } from "../types";

export default function IdentityInspector({
  data,
  onEvidence,
  onCutoff,
  loading,
  selected,
  active,
  edges,
  onEdge,
  onNode,
  onFocus,
}: {
  selected: string;
  active?: IdentityEdge;
  edges: IdentityEdge[];
  onEdge: (id: string) => void;
  onNode: (id: string) => void;
  onFocus: () => void;
} & SceneProps) {
  const node = data.identity_nodes.find((n) => n.id === selected),
    status = active ? edgeStatus(active, data.request.audit_at) : null;
  const related = edges.filter(
    (e) => e.source === selected || e.target === selected,
  );
  const proof = [...new Set(related.flatMap((e) => e.evidence_ids))];
  const ended = related.filter((e) =>
    isEnded(edgeStatus(e, data.request.audit_at)),
  ).length;
  const entityDeleted =
    node?.entity_state === "DELETED" &&
    !!node.entity_event_at &&
    Date.parse(node.entity_event_at) <= Date.parse(data.request.audit_at) &&
    !!node.entity_evidence_ids?.length;
  return (
    <aside
      className="identity-inspector"
      aria-label="Relationship and identity inspector"
    >
      <div className="inspector-kicker">
        <Focus size={15} /> TRACE INSPECTOR <span>↗</span>
      </div>
      <span className="small-label">
        {active
          ? "SELECTED RELATIONSHIP"
          : node
            ? "SELECTED IDENTIFIER"
            : "INVESTIGATION GRAPH"}
      </span>
      <h3>
        {active
          ? label(active.relationship)
          : node?.kind === "subject"
            ? data.name
            : (node?.label ?? "Select a trace")}
      </h3>
      {active && status ? (
        <>
          <div className={`relationship-state ${status}`}>
            {status === "conflict" ? (
              <ShieldAlert size={14} />
            ) : status === "verified" ? (
              <CheckCircle2 size={14} />
            ) : (
              <i />
            )}
            {statusName[status]}
          </div>
          <dl className="inspector-details">
            <dt>Source node</dt>
            <dd>
              <button onClick={() => onNode(active.source)}>
                {active.source}
                <ArrowUpRight size={11} />
              </button>
            </dd>
            <dt>Target node</dt>
            <dd>
              <button onClick={() => onNode(active.target)}>
                {active.target}
                <ArrowUpRight size={11} />
              </button>
            </dd>
            <dt>Verification</dt>
            <dd>{active.verification_state ?? active.state}</dd>
            {active.valid_from && (
              <>
                <dt>Effective start</dt>
                <dd>{fullTime(active.valid_from)}</dd>
              </>
            )}
            {active.valid_to && (
              <>
                <dt>Effective end</dt>
                <dd>{fullTime(active.valid_to)}</dd>
              </>
            )}
            {active.event_at && (
              <>
                <dt>Recorded event</dt>
                <dd>{fullTime(active.event_at)}</dd>
              </>
            )}
            {active.lifecycle_event && (
              <>
                <dt>Observed change</dt>
                <dd>
                  {active.lifecycle_event.kind.toUpperCase()} ·{" "}
                  {fullTime(active.lifecycle_event.at)}
                </dd>
                {active.lifecycle_event.reason && (
                  <>
                    <dt>Source reason</dt>
                    <dd>{active.lifecycle_event.reason}</dd>
                  </>
                )}
              </>
            )}
            {!!active.system_ids?.length && (
              <>
                <dt>Relevant systems</dt>
                <dd>{active.system_ids.join(", ")}</dd>
              </>
            )}
          </dl>
          {isEnded(status) && (
            <p className="identity-history-note">
              This association ended. The endpoint entities and their historical
              evidence remain separate from the relationship’s lifecycle.
            </p>
          )}
          <span className="small-label">SUPPORTING EVIDENCE</span>
          <div className="evidence-stack">
            {active.evidence_ids.map((id) => (
              <EvidenceLink key={id} id={id} onOpen={onEvidence} />
            ))}
            {!active.evidence_ids.length && (
              <p className="inspector-copy">
                No supporting source was supplied. Verification is unavailable.
              </p>
            )}
          </div>
          {active.evidence?.map((e) => (
            <div className="identity-source-row" key={e.source_id}>
              <strong>{e.origin ?? e.source_id}</strong>
              {e.locator && <span>{e.locator}</span>}
              {e.captured_at && <span>Captured {fullTime(e.captured_at)}</span>}
              <small>
                {e.eligible
                  ? "Eligible at this audit cutoff"
                  : "Not eligible at this audit cutoff"}
              </small>
            </div>
          ))}
          {!!active.conflicting_evidence_ids?.length && (
            <div className="identity-conflict-proof">
              <span className="small-label">CONFLICTING OBSERVATIONS</span>
              {active.conflicting_evidence_ids.map((id) => (
                <EvidenceLink key={id} id={id} onOpen={onEvidence} />
              ))}
            </div>
          )}
          <button className="outline-button" onClick={onFocus}>
            <Focus size={14} />
            Focus selected path
          </button>
        </>
      ) : node ? (
        <>
          <p className="identity-full-identifier">{node.id}</p>
          <div className="identity-node-summary">
            <span>{related.length - ended} active / unverified links</span>
            <span>{ended} historical links</span>
          </div>
          {entityDeleted && (
            <div className="identity-entity-state">
              <strong>ENTITY DELETED</strong>
              <span>{fullTime(node.entity_event_at!)}</span>
              {node.entity_evidence_ids!.map((id) => (
                <EvidenceLink key={id} id={id} onOpen={onEvidence} />
              ))}
            </div>
          )}
          <p className="inspector-copy">
            {node.kind === "subject"
              ? "Stable user reference. Node size indicates its role, not a confidence score."
              : "An identifier in the backend identity map. Its associations and the entity’s own state are separate."}
          </p>
          <span className="small-label">CONNECTED RELATIONSHIPS</span>
          <div className="relationship-list">
            {related.map((e) => (
              <button
                key={e.id}
                aria-label={`${label(e.relationship)} ${e.state}`}
                onClick={() => onEdge(e.id)}
              >
                <span
                  className={`relation-dot ${edgeStatus(e, data.request.audit_at)}`}
                />
                <span>
                  {label(e.relationship)}
                  <small>
                    {statusName[edgeStatus(e, data.request.audit_at)]}
                  </small>
                </span>
                <ArrowUpRight size={13} />
              </button>
            ))}
            {!related.length && (
              <p className="inspector-copy">
                No relationships are available in this view. Absence is not
                evidence of deletion.
              </p>
            )}
          </div>
          <button className="text-link" onClick={onFocus}>
            Focus these relationships
            <Focus size={14} />
          </button>
          {proof.length > 0 && (
            <details className="identity-node-proof">
              <summary>All supporting evidence ({proof.length})</summary>
              {proof.map((id) => (
                <EvidenceLink key={id} id={id} onOpen={onEvidence} />
              ))}
            </details>
          )}
        </>
      ) : (
        <p className="inspector-copy">
          Select a connection for its evidence and validity interval, or an
          identifier for its neighbourhood. Every connection shown comes from
          the backend response.
        </p>
      )}
      <div className="inspector-bottom">
        <TimeControl data={data} onChange={onCutoff} />
        {loading && (
          <span role="status" className="small-label">
            Reconstructing from sources…
          </span>
        )}
      </div>
    </aside>
  );
}
