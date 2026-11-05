import type { IdentityEdge, IdentityNode } from "../types";
export type RelationshipStatus =
  | "verified"
  | "confirmed"
  | "candidate"
  | "conflict"
  | "ended"
  | "removed"
  | "deleted"
  | "unknown"
  | "future";
export const statusName: Record<RelationshipStatus, string> = {
  verified: "ACTIVE · VERIFIED",
  confirmed: "ACTIVE · CONFIRMED",
  candidate: "CANDIDATE / UNVERIFIED",
  conflict: "CONFLICTING",
  ended: "ENDED",
  removed: "REMOVED",
  deleted: "DELETED RELATIONSHIP",
  unknown: "UNVERIFIED",
  future: "AFTER AUDIT CUTOFF",
};
export const fullTime = (time: string) =>
  new Date(time).toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }) + " UTC";
export const isEnded = (status: RelationshipStatus) =>
  ["ended", "removed", "deleted"].includes(status);

export function validateEdge(
  edge: IdentityEdge,
  nodes: Set<string>,
): string | null {
  if (!edge.id || !nodes.has(edge.source) || !nodes.has(edge.target))
    return "Missing edge ID or endpoint node";
  for (const time of [
    edge.valid_from,
    edge.valid_to,
    edge.event_at,
    edge.lifecycle_event?.at,
  ])
    if (time && !Number.isFinite(Date.parse(time)))
      return "Invalid relationship timestamp";
  if (
    edge.valid_from &&
    edge.valid_to &&
    Date.parse(edge.valid_to) < Date.parse(edge.valid_from)
  )
    return "End precedes start";
  return null;
}

export function edgeStatus(
  edge: IdentityEdge,
  cutoff: string,
): RelationshipStatus {
  const time = Date.parse(cutoff);
  const evidence = edge.evidence ?? [];
  const established = new Set([
    ...edge.evidence_ids,
    ...(edge.conflicting_evidence_ids ?? []),
  ]);
  const eligible = (id: string) =>
    established.has(id) &&
    (!evidence.length ||
      evidence.some(
        (e) =>
          e.source_id === id &&
          e.eligible &&
          !!e.captured_at &&
          Date.parse(e.captured_at) <= time,
      ));
  if (
    edge.state === "future" ||
    (edge.valid_from && Date.parse(edge.valid_from) > time)
  )
    return "future";
  if (
    evidence.length &&
    !evidence.some(
      (e) => e.eligible && !!e.captured_at && Date.parse(e.captured_at) <= time,
    )
  )
    return evidence.some(
      (e) => !!e.captured_at && Date.parse(e.captured_at) > time,
    )
      ? "future"
      : "unknown";
  const event = edge.lifecycle_event;
  if (
    event &&
    Date.parse(event.at) <= time &&
    event.evidence_ids.some(eligible)
  )
    return event.kind;
  if (
    edge.valid_to &&
    Date.parse(edge.valid_to) <= time &&
    edge.evidence_ids.some(eligible)
  )
    return "ended";
  if (
    (edge.conflicting_evidence_ids ?? []).some(eligible) ||
    edge.verification_state === "conflict" ||
    edge.state === "conflict"
  )
    return "conflict";
  if (!edge.evidence_ids.length) return "unknown";
  const verification = edge.verification_state ?? edge.state;
  if (
    verification === "verified" ||
    verification === "confirmed" ||
    verification === "candidate"
  )
    return verification;
  if (edge.state === "historical") return "unknown"; // No reliable interval: a historic label is not a deletion event.
  return "unknown";
}

export function shortestPath(
  edges: IdentityEdge[],
  from: string,
  to: string,
): { nodes: Set<string>; edges: Set<string> } {
  const queue = [from],
    seen = new Set([from]),
    previous = new Map<string, { node: string; edge: string }>();
  for (let i = 0; i < queue.length && !seen.has(to); i++)
    for (const e of edges) {
      const next =
        e.source === queue[i]
          ? e.target
          : e.target === queue[i]
            ? e.source
            : null;
      if (next && !seen.has(next)) {
        seen.add(next);
        previous.set(next, { node: queue[i], edge: e.id });
        queue.push(next);
      }
    }
  const result = { nodes: new Set<string>(), edges: new Set<string>() };
  if (!seen.has(to)) return result;
  let cursor = to;
  result.nodes.add(cursor);
  while (cursor !== from) {
    const p = previous.get(cursor)!;
    result.edges.add(p.edge);
    result.nodes.add(p.node);
    cursor = p.node;
  }
  return result;
}

export function neighborhood(
  edges: IdentityEdge[],
  roots: string[],
  hops: number,
): Set<string> {
  const seen = new Set(roots);
  let frontier = [...roots];
  for (let i = 0; i < hops; i++) {
    const next: string[] = [];
    for (const e of edges) {
      if (frontier.includes(e.source) && !seen.has(e.target)) {
        seen.add(e.target);
        next.push(e.target);
      }
      if (frontier.includes(e.target) && !seen.has(e.source)) {
        seen.add(e.source);
        next.push(e.source);
      }
    }
    frontier = next;
    if (!frontier.length) break;
  }
  return seen;
}

/** Preserve the original eight anchors. Extra nodes get repeatable, non-overlapping rows. */
export const anchors = [
  [490, 248],
  [236, 110],
  [765, 130],
  [780, 377],
  [227, 387],
  [480, 450],
  [100, 255],
  [895, 250],
];
export function layoutIdentity(
  nodes: IdentityNode[],
): Record<string, number[]> {
  const sorted = [...nodes].sort((a, b) =>
    a.kind === "subject"
      ? -1
      : b.kind === "subject"
        ? 1
        : a.id.localeCompare(b.id),
  );
  return Object.fromEntries(
    sorted.map((n, i) => [
      n.id,
      sorted.length <= 8
        ? anchors[i]
        : [110 + (i % 5) * 195, 90 + Math.floor(i / 5) * 140],
    ]),
  );
}
