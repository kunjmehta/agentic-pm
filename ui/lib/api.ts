import type { SemiAutoResponse, TaskPreviewData } from '@/types';

// ── helpers ──────────────────────────────────────────────────────────────────

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Semi-Auto ─────────────────────────────────────────────────────────────────

export async function approve(
  apiUrl: string,
  threadId: string,
): Promise<SemiAutoResponse> {
  return post<SemiAutoResponse>(`${apiUrl}/approve/${threadId}`, {});
}

export async function reject(apiUrl: string, threadId: string): Promise<void> {
  await fetch(`${apiUrl}/reject/${threadId}`, { method: 'POST' }).catch(() => {});
}

// ── Conversation history ─────────────────────────────────────────────────────

export async function loadConversation(
  apiUrl: string,
  threadId: string,
): Promise<{ turns: import('@/types').ConversationTurn[] }> {
  const res = await fetch(`${apiUrl}/conversations/${threadId}`);
  if (!res.ok) return { turns: [] };
  return res.json() as Promise<{ turns: import('@/types').ConversationTurn[] }>;
}

// ── SSE types ────────────────────────────────────────────────────────────────

export type SseEvent =
  | { type: 'thought_delta'; agent: string; token: string }
  | { type: 'reasoning'; agent: string; tasks?: unknown[]; content?: string }
  | { type: 'interrupt'; thread_id: string; tasks_preview: TaskPreviewData['portfolio_tasks'] & Record<string, unknown> }
  | { type: 'text'; content: string }
  | { type: 'error'; content: string }
  | { type: 'done' }
  | { type: 'node'; node: string }
  | { type: 'tool_call'; content: unknown }
  | { type: 'status'; message?: string }
  | { type: string; [key: string]: unknown };

export async function* streamQuery(
  apiUrl: string,
  body: Record<string, unknown>,
): AsyncGenerator<SseEvent> {
  const res = await fetch(`${apiUrl}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        yield JSON.parse(line.slice(6)) as SseEvent;
      } catch {
        // skip malformed line
      }
    }
  }
}
