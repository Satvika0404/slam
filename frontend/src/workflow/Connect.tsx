import { useRef, useState } from "react";
import { Database, X } from "lucide-react";
import type { DatasetInput } from "./types";

interface Table {
  name: string;
  columns: string[];
  rows: number;
}
export default function Connect({
  onInput,
}: {
  onInput: (input: DatasetInput) => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [connection, setConnection] = useState<{
    id: string;
    tables: Table[];
  } | null>(null);
  const [mapping, setMapping] = useState<
    Record<
      string,
      { key: string; email: string; subject: string; action: string }
    >
  >({});
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function load(value: File) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/workflow/databases", {
        method: "POST",
        body: value,
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.detail);
      setConnection(result);
      setMapping(
        Object.fromEntries(
          result.tables.map((t: Table) => [
            t.name,
            {
              key:
                t.columns.find((c) => /^(id|resource_id)$/i.test(c)) ??
                t.columns[0],
              email: t.columns.find((c) => /email/i.test(c)) ?? "",
              subject: t.columns.find((c) => /^user_id$/i.test(c)) ?? "",
              action: "DELETE",
            },
          ]),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    if (!connection) return;
    setBusy(true);
    setError("");
    try {
      const tables = connection.tables
        .filter((t) => mapping[t.name].email)
        .map((t, i) => ({
          table: t.name,
          ...mapping[t.name],
          subject: mapping[t.name].subject || null,
          category: `MAPPED_${i}`,
        }));
      const response = await fetch(
        `/api/workflow/databases/${connection.id}/map`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tables }),
        },
      );
      const result = await response.json();
      if (!response.ok) throw Error(result.detail);
      onInput(result);
      setConnection(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        className="wf-secondary"
        disabled={busy}
        onClick={() => file.current?.click()}
      >
        <Database size={15} />
        {busy ? "Inspecting schema…" : "Connect SQLite"}
      </button>
      <input
        hidden
        type="file"
        accept=".sqlite,.sqlite3,.db"
        aria-label="Connect SQLite database"
        ref={file}
        onChange={(e) => {
          if (e.target.files?.[0]) void load(e.target.files[0]);
          e.target.value = "";
        }}
      />
      {error && <p role="alert">{error}</p>}
      {connection && (
        <div className="wf-modal-backdrop">
          <section
            className="wf-evidence-modal"
            role="dialog"
            aria-label="Map database tables"
          >
            <header>
              <h2>Connect your tables</h2>
              <button
                onClick={() => setConnection(null)}
                aria-label="Close database mapping"
              >
                <X />
              </button>
            </header>
            <p>
              Choose the stable row key, email and policy action. Tables without
              an email mapping are excluded.
            </p>
            {connection.tables.map((t) => (
              <div className="wf-mapping" key={t.name}>
                <h3>
                  {t.name} <small>{t.rows} rows</small>
                </h3>
                {["key", "email", "subject", "action"].map((field) => (
                  <label key={field}>
                    {field}
                    <select
                      aria-label={`${t.name} ${field}`}
                      value={mapping[t.name][field as "key"]}
                      onChange={(e) =>
                        setMapping((m) => ({
                          ...m,
                          [t.name]: { ...m[t.name], [field]: e.target.value },
                        }))
                      }
                    >
                      {field !== "action" && (
                        <option value="">
                          {field === "email" ? "Exclude table" : "Optional"}
                        </option>
                      )}
                      {(field === "action"
                        ? ["DELETE", "REDACT", "ANONYMIZE", "RETAIN"]
                        : t.columns
                      ).map((c) => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            ))}
            <button className="wf-primary" disabled={busy} onClick={connect}>
              Use mapped snapshot
            </button>
          </section>
        </div>
      )}
    </>
  );
}
