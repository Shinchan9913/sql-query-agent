import type { AgentResponse, ExecuteResult, Health, Step, ThreadSummary } from "./types";

export interface ChatHandlers {
  onStep: (step: Step) => void;
  onToken: (text: string) => void;
  onResponse: (response: AgentResponse) => void;
  onError: (message: string) => void;
}

/** POST a chat message and dispatch the server-sent events as they arrive. */
export async function streamChat(
  threadId: string,
  message: string,
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, message }),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    handlers.onError("Couldn't reach the server. Is the backend running?");
    return;
  }
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    handlers.onError(body.detail ?? "Still working on the previous message.");
    return;
  }
  await consume(res, handlers);
}

/** Re-attach to a turn still running on the server. Returns false if nothing is running. */
export async function resumeTurn(threadId: string, handlers: ChatHandlers, signal?: AbortSignal): Promise<boolean> {
  let res: Response;
  try {
    res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/events`, { signal });
  } catch {
    return false;
  }
  if (res.status === 204) return false;
  await consume(res, handlers);
  return true;
}

export async function cancelTurn(threadId: string): Promise<void> {
  await fetch(`/api/threads/${encodeURIComponent(threadId)}/cancel`, { method: "POST" }).catch(() => {});
}

async function consume(res: Response, handlers: ChatHandlers): Promise<void> {
  if (!res.ok || !res.body) {
    handlers.onError(`The server returned an error (${res.status}).`);
    return;
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseEvent(block);
        if (!event) continue;
        if (event.name === "step") handlers.onStep(event.data as Step);
        else if (event.name === "token") handlers.onToken((event.data as { text: string }).text);
        else if (event.name === "response") {
          finished = true;
          handlers.onResponse(event.data as AgentResponse);
        } else if (event.name === "error") {
          finished = true;
          handlers.onError((event.data as { message: string }).message);
        }
      }
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") return; // we detached on purpose; the server keeps going
    throw e;
  }
  if (!finished) handlers.onError("The connection closed before the answer was complete.");
}

function parseEvent(block: string): { name: string; data: unknown } | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // keep-alive comment
    if (line.startsWith("event: ")) name = line.slice(7);
    else if (line.startsWith("data: ")) data.push(line.slice(6));
  }
  if (!data.length) return null;
  return { name, data: JSON.parse(data.join("\n")) };
}

export class ExecuteError extends Error {
  constructor(public errors: string[]) {
    super(errors.join("; "));
  }
}

export async function executeSql(sql: string): Promise<ExecuteResult> {
  const res = await fetch("/api/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ExecuteError(body?.detail?.errors ?? [`Request failed (${res.status})`]);
  return body as ExecuteResult;
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await fetch("/api/threads");
  return res.ok ? res.json() : [];
}

export async function getThread(id: string) {
  const res = await fetch(`/api/threads/${encodeURIComponent(id)}`);
  if (!res.ok) return null;
  return res.json() as Promise<
    ThreadSummary & { messages: { role: "user" | "assistant"; content: string; response?: AgentResponse }[] }
  >;
}

export async function deleteThread(id: string): Promise<void> {
  await fetch(`/api/threads/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch("/api/health");
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}
