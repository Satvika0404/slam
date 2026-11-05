import type { AuditCase } from "./types";
export interface ExecutionEvent {
  event: string;
  run_id?: string;
  sequence?: number;
  at?: string;
  elapsed_ms?: number;
  case_id?: string | null;
  payload: Record<string, unknown> & { stage?: string; snapshot?: AuditCase };
}
export const executionStages = [
  {
    id: "ingestion",
    name: "Read & extract",
    tech: "Manifest · parsers · OCR / optional model",
  },
  {
    id: "linking",
    name: "Learn attribution",
    tech: "Ownership index · validated timing groups",
  },
  {
    id: "intent",
    name: "Interpret request",
    tech: "Rules · optional grounded model proposal",
  },
  {
    id: "identity",
    name: "Resolve identity",
    tech: "Exact current + historical identifiers",
  },
  {
    id: "ownership",
    name: "Link resources",
    tech: "Explicit ownership · closure · candidates",
  },
  {
    id: "timeline",
    name: "Reconstruct state",
    tech: "Audit cutoff · evidence precedence",
  },
  {
    id: "graph",
    name: "Analyse dependencies",
    tech: "NetworkX · flows · restore paths · cycles",
  },
  {
    id: "planning",
    name: "Apply policy & order",
    tech: "Policy rules · dependency ordering",
  },
  {
    id: "validation",
    name: "Validate output",
    tech: "Pydantic · citation / export checks",
  },
];

export async function consumeExecution(
  response: Response,
  onEvent: (event: ExecutionEvent) => void,
) {
  if (!response.ok) {
    let message = `Run request failed (${response.status})`;
    try {
      const b = await response.json();
      if (typeof b.detail === "string") message = b.detail;
    } catch {
      /* preserve status */
    }
    throw new Error(message);
  }
  if (!response.body)
    throw new Error("This browser cannot stream the backend response.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  function frames() {
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const frame of parts) {
      const data = frame
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      const event = JSON.parse(data) as ExecutionEvent;
      if (!event.event || !event.payload)
        throw new Error("Backend emitted an invalid execution event.");
      if (event.event === "run.completed" || event.event === "run.failed")
        terminal = true;
      onEvent(event);
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      frames();
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      buffer += "\n\n";
      frames();
    }
    if (!terminal)
      throw new Error(
        "Execution connection closed before a terminal backend event. No completed run is assumed.",
      );
  } finally {
    reader.releaseLock();
  }
}
