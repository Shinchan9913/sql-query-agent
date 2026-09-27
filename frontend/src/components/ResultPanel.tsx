import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import type { AgentResponse, ExecuteResult } from "../types";
import { copyText, downloadFile, toCsv } from "../utils";
import { SqlCode } from "./SqlCode";

export type Tab = "sql" | "explanation" | "results";

export interface RunState {
  loading: boolean;
  result?: ExecuteResult;
  errors?: string[];
}

interface Props {
  response: AgentResponse | null;
  tab: Tab;
  onTab: (tab: Tab) => void;
  run?: RunState;
  onRun: () => void;
}

const DIALECT_LABELS: Record<string, string> = { sqlite: "SQLite", postgres: "PostgreSQL", mysql: "MySQL" };

export function ResultPanel({ response, tab, onTab, run, onRun }: Props) {
  if (!response?.sql) {
    return (
      <section className="panel panel-empty">
        <p className="muted">Generated SQL, its explanation and query results appear here.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="tabs" role="tablist">
        {(["sql", "explanation", "results"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => onTab(t)}>
            {t === "sql" ? "SQL" : t === "explanation" ? "Explanation" : "Results"}
            {t === "results" && run?.result && <span className="count">{run.result.row_count}</span>}
          </button>
        ))}
      </div>
      <div className="panel-body">
        {tab === "sql" && <SqlTab response={response} onRun={onRun} running={Boolean(run?.loading)} />}
        {tab === "explanation" && <ExplanationTab response={response} />}
        {tab === "results" && <ResultsTab run={run} onRun={onRun} />}
      </div>
    </section>
  );
}

function SqlTab({ response, onRun, running }: { response: AgentResponse; onRun: () => void; running: boolean }) {
  const dialects = response.optimization?.dialects ?? { sqlite: response.sql! };
  const [dialect, setDialect] = useState("sqlite");
  const [copied, setCopied] = useState(false);
  useEffect(() => setDialect("sqlite"), [response]);

  const code = dialects[dialect] ?? response.sql!;
  const copy = async () => {
    if (await copyText(code)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const opt = response.optimization;
  return (
    <>
      <div className="toolbar">
        <select value={dialect} onChange={(e) => setDialect(e.target.value)} aria-label="SQL dialect">
          {Object.keys(dialects).map((d) => (
            <option key={d} value={d}>
              {DIALECT_LABELS[d] ?? d}
            </option>
          ))}
        </select>
        <div className="spacer" />
        <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        <button className="btn" onClick={() => downloadFile(`query.${dialect}.sql`, code + "\n", "text/plain")}>
          Download
        </button>
        <button className="btn btn-primary" onClick={onRun} disabled={running} title="Runs the SQLite version, read-only">
          {running ? "Running…" : "▶ Run"}
        </button>
      </div>
      <SqlCode code={code} />

      {response.warnings && response.warnings.length > 0 && (
        <Notice tone="warn" title="Validation warnings" items={response.warnings} />
      )}
      {response.assumptions && response.assumptions.length > 0 && (
        <Notice title="Assumptions" items={response.assumptions} />
      )}
      {opt && (
        <div className="analysis">
          <h3>
            Performance <span className={`cost cost-${opt.cost.level}`}>{opt.cost.level} cost</span>
          </h3>
          <p className="muted small">
            {opt.cost.full_scans.length
              ? `Full scan of ${opt.cost.full_scans.join(", ")} (~${opt.cost.rows_scanned_estimate} rows).`
              : "Uses indexed lookups; no full table scans."}
            {opt.cost.uses_temp_sort && " Needs a temporary sort."}
          </p>
          {opt.suggestions.length > 0 && <Notice title="Suggestions" items={opt.suggestions} />}
          {opt.index_recommendations.length > 0 && (
            <>
              <h4>Recommended indexes</h4>
              <SqlCode code={opt.index_recommendations.join("\n")} />
            </>
          )}
        </div>
      )}
    </>
  );
}

function ExplanationTab({ response }: { response: AgentResponse }) {
  return (
    <div className="markdown">
      <Markdown>{response.explanation ?? ""}</Markdown>
      {response.notes && response.notes.length > 0 && (
        <Notice title={response.intent === "optimize" ? "Changes made" : "Issues found"} items={response.notes} />
      )}
      {response.input_sql && (
        <>
          <h4>Your original SQL</h4>
          <SqlCode code={response.input_sql} />
        </>
      )}
    </div>
  );
}

function ResultsTab({ run, onRun }: { run?: RunState; onRun: () => void }) {
  if (!run) {
    return (
      <div className="panel-empty inner">
        <p className="muted">The query hasn't been run yet.</p>
        <button className="btn btn-primary" onClick={onRun}>▶ Run query</button>
      </div>
    );
  }
  if (run.loading) return <p className="muted">Running…</p>;
  if (run.errors) return <Notice tone="error" title="The query couldn't run" items={run.errors} />;

  const r = run.result!;
  return (
    <>
      <div className="toolbar">
        <span className="muted small">
          {r.row_count} row{r.row_count === 1 ? "" : "s"}
          {r.truncated && " (truncated)"} · {r.elapsed_ms} ms
        </span>
        <div className="spacer" />
        <button className="btn" onClick={() => downloadFile("results.csv", toCsv(r.columns, r.rows), "text/csv")}>
          Download CSV
        </button>
      </div>
      {r.row_count === 0 ? (
        <p className="muted">No rows matched.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>{r.columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {r.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((v, j) => (
                    <td key={j} className={typeof v === "number" ? "num" : ""}>
                      {v === null ? <span className="null">NULL</span> : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Notice({ title, items, tone }: { title: string; items: string[]; tone?: "warn" | "error" }) {
  return (
    <div className={`notice ${tone ? `notice-${tone}` : ""}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
