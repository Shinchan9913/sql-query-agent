import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import type { ChatMessage, Step } from "../types";

const EXAMPLES = [
  "Show all employees hired after January 2024",
  "Top 5 customers by total order amount",
  "Which products have never been ordered?",
  "Optimize: SELECT * FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID WHERE strftime('%Y', o.OrderDate) = '2024'",
  "Fix this: SELECT FirstName, HireDat FROM Employee WHERE Salary > 100000",
  "Who won the FIFA World Cup?",
];

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  selectedId: string | null;
  onSend: (text: string) => void;
  onSelect: (id: string) => void;
  onStop: () => void;
}

export function ChatPanel({ messages, busy, selectedId, onSend, onSelect, onStop }: Props) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    onSend(text);
    setDraft("");
  };

  return (
    <section className="chat">
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>Ask about your data in plain English</h2>
            <p className="muted">
              I write read-only SQL for the sample company database, explain it, and help optimize or debug
              queries you paste in.
            </p>
            <div className="examples">
              {EXAMPLES.map((e) => (
                <button key={e} className="example" onClick={() => onSend(e)} disabled={busy}>
                  {e}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} message={m} selected={m.id === selectedId} onSelect={() => onSelect(m.id)} />
        ))}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask a question, or paste SQL to explain, optimize or debug…"
          rows={2}
          aria-label="Message"
        />
        {busy ? (
          <button type="button" className="btn" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
            Send
          </button>
        )}
      </form>
    </section>
  );
}

function Message({ message, selected, onSelect }: { message: ChatMessage; selected: boolean; onSelect: () => void }) {
  if (message.role === "user") {
    return <div className="msg msg-user">{message.content}</div>;
  }

  const response = message.response;
  const kind = message.error ? "error" : response?.type ?? "pending";
  const hasSql = Boolean(response?.sql);

  return (
    <div className={`msg msg-assistant kind-${kind} ${selected ? "selected" : ""}`}>
      {message.pending && <Progress steps={message.steps ?? []} />}
      {kind === "rejected" && <div className="badge badge-warn">Out of scope</div>}
      {kind === "clarification" && <div className="badge">Needs clarification</div>}
      {message.content && (
        <div className="markdown">
          <Markdown>{message.content}</Markdown>
        </div>
      )}
      {hasSql && (
        <button className="sql-preview" onClick={onSelect} title="Show in SQL panel">
          <code>{response!.sql!.split("\n").slice(0, 3).join(" ").slice(0, 90)}…</code>
          <span>{selected ? "Shown in panel" : "Open in panel →"}</span>
        </button>
      )}
    </div>
  );
}

function Progress({ steps }: { steps: Step[] }) {
  const last = steps[steps.length - 1];
  const lookups = steps.flatMap((s) => (Array.isArray(s.detail) ? s.detail : []));
  return (
    <div className="progress" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{last ? `${last.label}…` : "Thinking…"}</span>
      {lookups.length > 0 && (
        <ul className="lookups">
          {lookups.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
