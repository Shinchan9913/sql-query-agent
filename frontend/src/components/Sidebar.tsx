import type { ThreadSummary } from "../types";

interface Props {
  threads: ThreadSummary[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function Sidebar({ threads, activeId, onSelect, onNew, onDelete }: Props) {
  return (
    <aside className="sidebar">
      <button className="btn btn-primary new-chat" onClick={onNew}>
        + New conversation
      </button>
      <div className="sidebar-label">History</div>
      <nav className="thread-list">
        {threads.length === 0 && <p className="muted small">No conversations yet.</p>}
        {threads.map((t) => (
          <div key={t.id} className={`thread ${t.id === activeId ? "active" : ""}`}>
            <button className="thread-title" onClick={() => onSelect(t.id)} title={t.title}>
              {t.running && <span className="running-dot" aria-label="Working" />}
              {t.title}
            </button>
            <button
              className="thread-delete"
              aria-label={`Delete conversation ${t.title}`}
              onClick={() => onDelete(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
