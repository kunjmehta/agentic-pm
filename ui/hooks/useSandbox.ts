/**
 * useSandbox — React hook for Daytona sandbox lifecycle and agent streaming.
 *
 * States:
 *   idle        → no sandbox exists
 *   creating    → POST /create sent; polling /status every 3s
 *   ready       → vscode_url available; agent chat enabled
 *   error       → creation or API call failed
 *   publishing  → publish in flight
 *   destroying  → delete in flight
 */

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createSandbox,
  deleteSandbox,
  getSandboxStatus,
  publishSandbox,
  streamAgentQuery,
  type PublishResponse,
} from '@/lib/sandboxApi';

// ── Types ─────────────────────────────────────────────────────────────────

export type SandboxPhase =
  | 'idle'
  | 'creating'
  | 'ready'
  | 'error'
  | 'not_found'
  | 'publishing'
  | 'destroying';

export interface AgentMessage {
  role: 'user' | 'assistant';
  content: string;
  /** true while the assistant turn is still streaming */
  streaming?: boolean;
}

export interface UseSandboxReturn {
  phase: SandboxPhase;
  sandboxId: string | null;
  sandboxName: string | null;
  vsCodeUrl: string | null;
  errorMsg: string | null;
  messages: AgentMessage[];
  isAgentStreaming: boolean;
  /** Actual Daytona sandbox ID (for TypeScript SDK file ops) */
  daytonaSandboxId: string | null;
  /** Working directory inside the sandbox (e.g. /home/daytona/name) */
  workDir: string | null;
  /** Daytona web terminal URL (port 22222) */
  terminalUrl: string | null;
  /** Start sandbox provisioning */
  create: () => Promise<void>;
  /** Publish changed files → destroy sandbox */
  publish: (mode?: 'all' | 'new') => Promise<PublishResponse | null>;
  /** Force-destroy without publishing */
  destroy: () => Promise<void>;
  /** Send a message to the DeepAgent */
  sendQuery: (query: string) => Promise<void>;
  /** Attempt to resume an existing sandbox by its ID */
  resumeFrom: (id: string) => Promise<void>;
  /** Last publish result */
  lastPublish: PublishResponse | null;
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useSandbox(apiUrl: string): UseSandboxReturn {
  const [phase, setPhase] = useState<SandboxPhase>('idle');
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [sandboxName, setSandboxName] = useState<string | null>(null);
  const [vsCodeUrl, setVsCodeUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [isAgentStreaming, setIsAgentStreaming] = useState(false);
  const [lastPublish, setLastPublish] = useState<PublishResponse | null>(null);
  const [daytonaSandboxId, setDaytonaSandboxId] = useState<string | null>(null);
  const [workDir, setWorkDir] = useState<string | null>(null);
  const [terminalUrl, setTerminalUrl] = useState<string | null>(null);

  // Polling interval ref so we can clear it on unmount / status change
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // ── Cleanup on unmount ────────────────────────────────────────────────
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // ── Poll /status ──────────────────────────────────────────────────────
  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const status = await getSandboxStatus(apiUrl, id);
          if (status.status === 'ready') {
            stopPolling();
            setVsCodeUrl(status.vscode_url);
            setDaytonaSandboxId(status.daytona_sandbox_id || null);
            setWorkDir(status.work_dir || null);
            setTerminalUrl(status.terminal_url || null);
            setPhase('ready');
          } else if (status.status === 'error') {
            stopPolling();
            setErrorMsg(status.error_msg ?? 'Unknown error during sandbox creation.');
            setPhase('error');
          }
          // "creating" → keep polling
        } catch (err) {
          stopPolling();
          setErrorMsg(err instanceof Error ? err.message : String(err));
          setPhase('error');
        }
      }, 3000);
    },
    [apiUrl, stopPolling],
  );

  // ── create ────────────────────────────────────────────────────────────
  const create = useCallback(async () => {
    setPhase('creating');
    setErrorMsg(null);
    setMessages([]);
    setLastPublish(null);

    try {
      const res = await createSandbox(apiUrl);
      setSandboxId(res.sandbox_id);
      setSandboxName(res.name);
      startPolling(res.sandbox_id);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setPhase('error');
    }
  }, [apiUrl, startPolling]);

  // ── publish ───────────────────────────────────────────────────────────
  const publish = useCallback(async (mode: 'all' | 'new' = 'all'): Promise<PublishResponse | null> => {
    if (!sandboxId) return null;
    setPhase('publishing');

    try {
      const res = await publishSandbox(apiUrl, sandboxId, mode);
      setLastPublish(res);
      // Reset state
      setSandboxId(null);
      setSandboxName(null);
      setVsCodeUrl(null);
      setDaytonaSandboxId(null);
      setWorkDir(null);
      setTerminalUrl(null);
      setMessages([]);
      setPhase('idle');
      return res;
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setPhase('error');
      return null;
    }
  }, [apiUrl, sandboxId]);

  // ── destroy ───────────────────────────────────────────────────────────
  const destroy = useCallback(async () => {
    if (!sandboxId) {
      setPhase('idle');
      return;
    }
    setPhase('destroying');
    stopPolling();

    try {
      await deleteSandbox(apiUrl, sandboxId);
    } catch {
      // Best-effort; reset state regardless
    } finally {
      setSandboxId(null);
      setSandboxName(null);
      setVsCodeUrl(null);
      setDaytonaSandboxId(null);
      setWorkDir(null);
      setTerminalUrl(null);
      setMessages([]);
      setErrorMsg(null);
      setPhase('idle');
    }
  }, [apiUrl, sandboxId, stopPolling]);

  // ── resumeFrom ────────────────────────────────────────────────────────
  const resumeFrom = useCallback(async (id: string) => {
    setPhase('creating'); // show spinner while we check
    try {
      const status = await getSandboxStatus(apiUrl, id);
      if (status.status === 'ready') {
        setSandboxId(id);
        setSandboxName(status.name);
        setVsCodeUrl(status.vscode_url);
        setDaytonaSandboxId(status.daytona_sandbox_id || null);
        setWorkDir(status.work_dir || null);
        setTerminalUrl(status.terminal_url || null);
        setPhase('ready');
      } else if (status.status === 'creating') {
        setSandboxId(id);
        setSandboxName(status.name);
        startPolling(id);
      } else {
        setPhase('not_found');
      }
    } catch {
      setPhase('not_found');
    }
  }, [apiUrl, startPolling]);

  // ── sendQuery ─────────────────────────────────────────────────────────
  const sendQuery = useCallback(
    async (query: string) => {
      if (!sandboxId || phase !== 'ready' || isAgentStreaming) return;

      setMessages((prev) => [...prev, { role: 'user', content: query }]);
      setIsAgentStreaming(true);

      // Append placeholder assistant message that we'll stream into
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '', streaming: true },
      ]);

      try {
        const reader = await streamAgentQuery(apiUrl, sandboxId, query);
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const event = JSON.parse(line.slice(6)) as {
                type: string;
                content?: string;
                error?: string;
              };
              if (event.type === 'token' && event.content) {
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last?.role === 'assistant') {
                    next[next.length - 1] = {
                      ...last,
                      content: last.content + event.content,
                    };
                  }
                  return next;
                });
              } else if (event.type === 'done') {
                // Mark streaming complete
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last?.role === 'assistant') {
                    next[next.length - 1] = { ...last, streaming: false };
                  }
                  return next;
                });
              } else if (event.type === 'error') {
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last?.role === 'assistant') {
                    next[next.length - 1] = {
                      ...last,
                      content: last.content || `[Error: ${event.error ?? 'unknown'}]`,
                      streaming: false,
                    };
                  }
                  return next;
                });
              }
            } catch {
              // Ignore malformed SSE lines
            }
          }
        }
      } catch (err) {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === 'assistant') {
            next[next.length - 1] = {
              ...last,
              content: `[Connection error: ${err instanceof Error ? err.message : String(err)}]`,
              streaming: false,
            };
          }
          return next;
        });
      } finally {
        setIsAgentStreaming(false);
      }
    },
    [apiUrl, sandboxId, phase, isAgentStreaming],
  );

  return {
    phase,
    sandboxId,
    sandboxName,
    vsCodeUrl,
    errorMsg,
    messages,
    isAgentStreaming,
    daytonaSandboxId,
    workDir,
    terminalUrl,
    create,
    publish,
    destroy,
    sendQuery,
    resumeFrom,
    lastPublish,
  };
}
