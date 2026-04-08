/**
 * Typed fetch helpers for the sandbox API endpoints.
 * All functions throw Error on non-2xx responses.
 */

// ── Response types ─────────────────────────────────────────────────────────

export interface CreateSandboxResponse {
  sandbox_id: string;
  name: string;
  status: 'creating';
}

export interface SandboxStatusResponse {
  sandbox_id: string;
  name: string;
  status: 'creating' | 'ready' | 'error';
  vscode_url: string;
  error_msg: string | null;
  work_dir: string;
  daytona_sandbox_id: string;
  terminal_url: string;
}

export interface PublishResponse {
  published_files: string[];
  count: number;
  sandbox_destroyed: boolean;
}

export interface DeleteResponse {
  ok: boolean;
}

// SSE event shapes emitted by POST /{id}/agent/stream
export type AgentSSEEvent =
  | { type: 'connected'; sandbox_id: string }
  | { type: 'token'; content: string }
  | { type: 'done' }
  | { type: 'error'; error: string };

// ── Helpers ────────────────────────────────────────────────────────────────

async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiDelete<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── API functions ──────────────────────────────────────────────────────────

/** POST /v1/sandbox/create — returns immediately with status "creating". */
export function createSandbox(apiUrl: string): Promise<CreateSandboxResponse> {
  return apiPost<CreateSandboxResponse>(`${apiUrl}/sandbox/create`);
}

/** GET /v1/sandbox/{id}/status — poll until status === "ready". */
export async function getSandboxStatus(
  apiUrl: string,
  sandboxId: string,
): Promise<SandboxStatusResponse> {
  const res = await fetch(`${apiUrl}/sandbox/${sandboxId}/status`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<SandboxStatusResponse>;
}

/** POST /v1/sandbox/{id}/publish — download changed files, destroy sandbox.
 *  mode: "all" (modified + new) | "new" (untracked only)
 */
export function publishSandbox(
  apiUrl: string,
  sandboxId: string,
  mode: 'all' | 'new' = 'all',
): Promise<PublishResponse> {
  return apiPost<PublishResponse>(`${apiUrl}/sandbox/${sandboxId}/publish?mode=${mode}`);
}

/** DELETE /v1/sandbox/{id} — force-destroy without publishing. */
export function deleteSandbox(apiUrl: string, sandboxId: string): Promise<DeleteResponse> {
  return apiDelete<DeleteResponse>(`${apiUrl}/sandbox/${sandboxId}`);
}

// ── File read / write (via Next.js API routes → Daytona TypeScript SDK) ──────

export interface FileReadResponse { path: string; content: string }
export interface FileListResponse { files: string[] }

/** List all .py files under src/ in the sandbox using Daytona TS SDK. */
export async function listSandboxFiles(
  daytonaSandboxId: string,
  workDir: string,
): Promise<FileListResponse> {
  const params = new URLSearchParams({ daytonaSandboxId, workDir });
  const res = await fetch(`/api/sandbox/files?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<FileListResponse>;
}

/** Read a file by relative path from the sandbox. */
export async function readSandboxFile(
  daytonaSandboxId: string,
  workDir: string,
  path: string,
): Promise<FileReadResponse> {
  const params = new URLSearchParams({ daytonaSandboxId, workDir, path });
  const res = await fetch(`/api/sandbox/file?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<FileReadResponse>;
}

/** Write a file at relative path in the sandbox. */
export async function writeSandboxFile(
  daytonaSandboxId: string,
  workDir: string,
  path: string,
  content: string,
): Promise<void> {
  const res = await fetch('/api/sandbox/file', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ daytonaSandboxId, workDir, path, content }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? `HTTP ${res.status}`);
  }
}

/**
 * POST /v1/sandbox/{id}/agent/stream — returns a ReadableStream of SSE events.
 * Caller is responsible for parsing `data: {...}` lines.
 */
export async function streamAgentQuery(
  apiUrl: string,
  sandboxId: string,
  query: string,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const res = await fetch(`${apiUrl}/sandbox/${sandboxId}/agent/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.body.getReader();
}
