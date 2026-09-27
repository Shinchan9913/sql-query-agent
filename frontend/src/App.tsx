import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelTurn,
  deleteThread,
  executeSql,
  ExecuteError,
  getHealth,
  getThread,
  listThreads,
  resumeTurn,
  streamChat,
  type ChatHandlers,
} from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { ResultPanel, type RunState, type Tab } from "./components/ResultPanel";
import { Sidebar } from "./components/Sidebar";
import type { ChatMessage, Health, ThreadSummary } from "./types";
import { newId, storageGet, storageSet } from "./utils";

type Theme = "light" | "dark";

export default function App() {
  const [threadId, setThreadId] = useState(() => storageGet("threadId") ?? newId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("sql");
  const [runs, setRuns] = useState<Record<string, RunState>>({});
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [theme, setTheme] = useState<Theme | null>(() => storageGet("theme") as Theme | null);

  // The thread on screen. Stream callbacks check it so a turn that finishes after
  // the user switched away doesn't write into the wrong conversation.
  const threadRef = useRef(threadId);
  // The open stream for the thread on screen. Aborting only detaches the browser;
  // the turn keeps running on the server.
  const streamRef = useRef<AbortController | null>(null);

  const refreshThreads = useCallback(() => listThreads().then(setThreads), []);

  useEffect(() => {
    refreshThreads();
    getHealth().then(setHealth);
  }, [refreshThreads]);

  // While any conversation is working in the background, keep the sidebar indicator fresh.
  const anyRunning = threads.some((t) => t.running);
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(refreshThreads, 3000);
    return () => clearInterval(timer);
  }, [anyRunning, refreshThreads]);

  const updateMessage = (id: string, change: (m: ChatMessage) => ChatMessage) =>
    setMessages((all) => all.map((m) => (m.id === id ? change(m) : m)));

  /** Stream a turn's events into the pending assistant message `assistantId` of thread `tid`. */
  const follow = useCallback(
    async (tid: string, assistantId: string, start: (h: ChatHandlers, signal: AbortSignal) => Promise<unknown>) => {
      const controller = new AbortController();
      streamRef.current = controller;
      setBusy(true);
      const onScreen = () => threadRef.current === tid && !controller.signal.aborted;

      await start(
        {
          onStep: (step) =>
            onScreen() && updateMessage(assistantId, (m) => ({ ...m, steps: [...(m.steps ?? []), step] })),
          onToken: (token) =>
            onScreen() && updateMessage(assistantId, (m) => ({ ...m, content: m.content + token })),
          onResponse: (response) => {
            if (!onScreen()) return;
            updateMessage(assistantId, (m) => ({ ...m, content: response.message, response, pending: false }));
            if (response.sql) {
              setSelectedId(assistantId);
              setTab("sql");
            }
          },
          onError: (message) =>
            onScreen() &&
            updateMessage(assistantId, (m) => ({ ...m, content: message, pending: false, error: true })),
        },
        controller.signal,
      );

      if (streamRef.current === controller) {
        streamRef.current = null;
        setBusy(false);
      }
      refreshThreads();
    },
    [refreshThreads],
  );

  // Load the conversation on screen; if a turn is still running there, re-attach to it.
  useEffect(() => {
    threadRef.current = threadId;
    storageSet("threadId", threadId);
    let cancelled = false;

    getThread(threadId).then((thread) => {
      if (cancelled) return;
      if (!thread) {
        setMessages([]);
        return;
      }
      const loaded: ChatMessage[] = thread.messages.map((m) => ({
        id: newId(),
        role: m.role,
        content: m.response?.message ?? m.content,
        response: m.response,
        error: m.response?.type === "error",
      }));
      setSelectedId([...loaded].reverse().find((m) => m.response?.sql)?.id ?? null);

      if (!thread.running) {
        setMessages(loaded);
        return;
      }
      const assistantId = newId();
      setMessages([...loaded, { id: assistantId, role: "assistant", content: "", pending: true, steps: [] }]);
      follow(threadId, assistantId, async (handlers, signal) => {
        const attached = await resumeTurn(threadId, handlers, signal);
        if (!attached && !signal.aborted) {
          // Finished between loading and re-attaching: reload to show the saved answer.
          const fresh = await getThread(threadId);
          const last = fresh?.messages[fresh.messages.length - 1];
          if (last?.response) {
            if (last.response.type === "error") handlers.onError(last.response.message);
            else handlers.onResponse(last.response);
          }
        }
      });
    });

    return () => {
      cancelled = true;
      streamRef.current?.abort();
      streamRef.current = null;
      setBusy(false);
    };
  }, [threadId, follow]);

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }, [theme]);

  const send = (text: string) => {
    const assistantId = newId();
    setMessages((all) => [
      ...all,
      { id: newId(), role: "user", content: text },
      { id: assistantId, role: "assistant", content: "", pending: true, steps: [] },
    ]);
    const tid = threadId;
    follow(tid, assistantId, (handlers, signal) => streamChat(tid, text, handlers, signal));
    // Show the new conversation in the sidebar right away.
    setTimeout(refreshThreads, 300);
  };

  const stop = () => cancelTurn(threadId); // the server records "Stopped." and ends the stream

  const startNewConversation = () => {
    setThreadId(newId());
    setMessages([]);
    setSelectedId(null);
    setRuns({});
  };

  const openThread = (id: string) => {
    if (id === threadId) return;
    setRuns({});
    setSelectedId(null);
    setThreadId(id);
  };

  const removeThread = async (id: string) => {
    await deleteThread(id);
    if (id === threadId) startNewConversation();
    refreshThreads();
  };

  const selected = messages.find((m) => m.id === selectedId) ?? null;

  const runSelected = async () => {
    const sql = selected?.response?.sql;
    if (!selected || !sql) return;
    const id = selected.id;
    setTab("results");
    setRuns((r) => ({ ...r, [id]: { loading: true } }));
    try {
      const result = await executeSql(sql);
      setRuns((r) => ({ ...r, [id]: { loading: false, result } }));
    } catch (e) {
      const errors = e instanceof ExecuteError ? e.errors : ["Couldn't reach the server."];
      setRuns((r) => ({ ...r, [id]: { loading: false, errors } }));
    }
  };

  const effectiveTheme: Theme =
    theme ?? (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const toggleTheme = () => {
    const next = effectiveTheme === "dark" ? "light" : "dark";
    setTheme(next);
    storageSet("theme", next);
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">SQL</span> Query Agent
        </div>
        <div className="header-right">
          {health && <span className="muted small model">{health.model}</span>}
          <button className="btn btn-ghost" onClick={toggleTheme} aria-label="Toggle dark mode">
            {effectiveTheme === "dark" ? "☀︎" : "☾"}
          </button>
        </div>
      </header>
      {health && !health.llm_ready && (
        <div className="banner" role="alert">
          The language model isn't configured: {health.llm_error}
        </div>
      )}
      {health === null && messages.length === 0 && (
        <div className="banner" role="alert">Can't reach the backend. Start it with uvicorn on port 8000.</div>
      )}
      <main className="layout">
        <Sidebar
          threads={threads}
          activeId={threadId}
          onSelect={openThread}
          onNew={startNewConversation}
          onDelete={removeThread}
        />
        <ChatPanel
          messages={messages}
          busy={busy}
          selectedId={selectedId}
          onSend={send}
          onSelect={setSelectedId}
          onStop={stop}
        />
        <ResultPanel
          response={selected?.response ?? null}
          tab={tab}
          onTab={setTab}
          run={selected ? runs[selected.id] : undefined}
          onRun={runSelected}
        />
      </main>
    </div>
  );
}
