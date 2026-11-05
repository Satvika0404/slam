import type { AuditCase, EvidenceDetail, Mode } from "./types";
export async function request<T>(
  path: string,
  signal?: AbortSignal,
  method = "GET",
): Promise<T> {
  const response = await fetch(path, { signal, method });
  if (!response.ok) {
    let message = `Server returned ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep HTTP status */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export const query = (mode: Mode, cutoff?: string | null) =>
  new URLSearchParams({ mode, ...(cutoff ? { cutoff } : {}) }).toString();
export const loadCase = (
  id: string,
  mode: Mode,
  cutoff: string | null,
  signal: AbortSignal,
) =>
  request<AuditCase>(
    `/api/cases/${encodeURIComponent(id)}?${query(mode, cutoff)}`,
    signal,
  );
export const loadEvidence = (
  id: string,
  caseId: string,
  mode: Mode,
  signal: AbortSignal,
) =>
  request<EvidenceDetail>(
    `/api/evidence/${encodeURIComponent(id)}?${new URLSearchParams({ case_id: caseId, mode })}`,
    signal,
  );
export const clock = (value: string) =>
  new Date(value).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
export const label = (value: string) =>
  value.replaceAll("_", " ").toLowerCase();
