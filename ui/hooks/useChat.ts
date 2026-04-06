'use client';

import { useCallback, useEffect, useReducer } from 'react';

const uuidv4 = () => crypto.randomUUID();
import { loadConversation, reject, streamApprove, streamQuery } from '@/lib/api';
import type {
  ExecutionResult,
  Message,
  MessageContent,
  TaskPreviewData,
} from '@/types';

// ── State ─────────────────────────────────────────────────────────────────────

interface ChatState {
  messages: Message[];
  isStreaming: boolean;
  threadId: string;
  hydrated: boolean;
}

type Action =
  | { type: 'SET_THREAD'; threadId: string }
  | { type: 'RESET' }
  | { type: 'HYDRATE'; threadId: string }
  | { type: 'APPEND_USER'; id: string; text: string }
  | { type: 'APPEND_ASSISTANT'; id: string }
  | { type: 'APPEND_CONTENT'; id: string; content: MessageContent }
  | { type: 'PREPEND_CONTENT'; id: string; content: MessageContent }
  | { type: 'SET_STREAMING'; value: boolean }
  | { type: 'SET_MESSAGES'; messages: Message[] }
  | {
      type: 'UPDATE_THINKING';
      id: string;
      agent: string;
      token: string;
    }
  | {
      type: 'FINALISE_THINKING';
      id: string;
      agent: string;
      taskCount: number;
    };

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'SET_THREAD':
      return { ...state, threadId: action.threadId };
    case 'HYDRATE':
      return { ...state, threadId: action.threadId, hydrated: true };
    case 'RESET':
      return { ...state, messages: [] };
    case 'APPEND_USER':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: action.id, role: 'user', content: [{ type: 'text', markdown: action.text }] },
        ],
      };
    case 'APPEND_ASSISTANT':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: action.id, role: 'assistant', content: [], isStreaming: true },
        ],
      };
    case 'APPEND_CONTENT':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, content: [...m.content, action.content] } : m,
        ),
      };
    case 'PREPEND_CONTENT':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, content: [action.content, ...m.content] } : m,
        ),
      };
    case 'SET_STREAMING':
      return { ...state, isStreaming: action.value };
    case 'SET_MESSAGES':
      return { ...state, messages: action.messages };

    case 'UPDATE_THINKING': {
      return {
        ...state,
        messages: state.messages.map((m) => {
          if (m.id !== action.id) return m;
          const idx = m.content.findIndex(
            (c) => c.type === 'thinking' && c.block.agent === action.agent,
          );
          if (idx === -1) {
            return {
              ...m,
              content: [
                ...m.content,
                { type: 'thinking' as const, block: { agent: action.agent, content: action.token } },
              ],
            };
          }
          const updated = [...m.content];
          const old = updated[idx] as Extract<MessageContent, { type: 'thinking' }>;
          updated[idx] = {
            ...old,
            block: { ...old.block, content: old.block.content + action.token },
          };
          return { ...m, content: updated };
        }),
      };
    }

    case 'FINALISE_THINKING': {
      return {
        ...state,
        messages: state.messages.map((m) => {
          if (m.id !== action.id) return m;
          return {
            ...m,
            content: m.content.map((c) => {
              if (c.type === 'thinking' && c.block.agent === action.agent) {
                return { ...c, block: { ...c.block, taskCount: action.taskCount } };
              }
              return c;
            }),
          };
        }),
      };
    }

    default:
      return state;
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

const STORED_THREAD = 'pm_threadId';
const STORED_API = 'pm_apiUrl';
const DEFAULT_API = 'http://localhost:8001/v1';

export function useChat() {
  const [state, dispatch] = useReducer(reducer, {
    messages: [],
    isStreaming: false,
    threadId: '',
    hydrated: false,
  });

  // Hydrate threadId from localStorage exactly once on the client.
  // Empty string on SSR avoids server/client HTML mismatch.
  useEffect(() => {
    const stored = localStorage.getItem(STORED_THREAD);
    const id = stored ?? uuidv4();
    if (!stored) localStorage.setItem(STORED_THREAD, id);
    dispatch({ type: 'HYDRATE', threadId: id });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // load conversation history after hydration / on threadId change
  useEffect(() => {
    if (!state.threadId) return;   // skip the pre-hydration empty string
    const url = localStorage.getItem(STORED_API) ?? DEFAULT_API;

    loadConversation(url, state.threadId).then(({ turns }) => {
      if (!turns.length) return;
      const msgs: Message[] = [];
      for (const turn of turns) {
        msgs.push({
          id: uuidv4(),
          role: 'user',
          content: [{ type: 'text', markdown: turn.query }],
        });
        const assistant: Message = { id: uuidv4(), role: 'assistant', content: [] };
        if (turn.status === 'pending_approval') {
          assistant.content.push({ type: 'pending_notice' });
        } else if (turn.final_response) {
          if (turn.execution_results?.length) {
            assistant.content.push({ type: 'exec_summary', results: turn.execution_results });
          }
          assistant.content.push({ type: 'text', markdown: turn.final_response });
        } else {
          assistant.content.push({ type: 'text', markdown: '(no response recorded)' });
        }
        msgs.push(assistant);
      }
      dispatch({ type: 'SET_MESSAGES', messages: msgs });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.threadId]);

  // ── newChat ──────────────────────────────────────────────────────────────
  const newChat = useCallback(() => {
    const id = uuidv4();
    localStorage.setItem(STORED_THREAD, id);
    dispatch({ type: 'SET_THREAD', threadId: id });
    dispatch({ type: 'RESET' });
  }, []);

  // ── send ─────────────────────────────────────────────────────────────────
  const send = useCallback(
    async (query: string, backtestMode: boolean, currentApiUrl: string) => {
      if (!query.trim() || state.isStreaming) return;

      dispatch({ type: 'SET_STREAMING', value: true });
      dispatch({ type: 'APPEND_USER', id: uuidv4(), text: query });
      const assistantId = uuidv4();
      dispatch({ type: 'APPEND_ASSISTANT', id: assistantId });

      const isSemiAuto = currentApiUrl.includes(':8000/v1');

      try {
        if (isSemiAuto) {
          await runSemiAuto(query, assistantId, backtestMode, currentApiUrl, dispatch, state.threadId);
        } else {
          await runLegacyStream(query, assistantId, backtestMode, currentApiUrl, dispatch, state.threadId);
        }
      } finally {
        dispatch({ type: 'SET_STREAMING', value: false });
      }
    },
    [state.isStreaming, state.threadId],
  );

  // ── handleApprove ────────────────────────────────────────────────────────
  const handleApprove = useCallback(
    async (msgId: string, threadId: string, currentApiUrl: string) => {
      dispatch({
        type: 'APPEND_CONTENT',
        id: msgId,
        content: { type: 'text', markdown: '⏳ Executing…' },
      });
      try {
        const liveTools = new Set<string>();
        for await (const evt of streamApprove(currentApiUrl, threadId)) {
          if (evt.type === 'tool_call') {
            const tc = (evt as { type: 'tool_call'; data: { function_name: string; status: string; duration_ms?: number | null } }).data;
            if (tc.status === 'started' && !liveTools.has(tc.function_name)) {
              liveTools.add(tc.function_name);
              dispatch({
                type: 'APPEND_CONTENT',
                id: msgId,
                content: { type: 'tool_badge', name: tc.function_name },
              });
            }
          } else if (evt.type === 'telemetry') {
            const data = (evt as { type: 'telemetry'; data: Record<string, unknown> }).data;
            const exec = (data.execution_results as ExecutionResult[]) ?? [];
            const richContent: MessageContent[] = [];

            const healthRes = exec.find(
              (r) => r.function_name === 'check_portfolio_health' && r.status === 'success',
            );
            if (healthRes) richContent.push({ type: 'health', result: healthRes });

            const statsRes = exec.find(
              (r) =>
                (r.function_name === 'get_portfolio_status' ||
                  r.function_name === 'get_positions_summary') &&
                r.status === 'success',
            );
            if (statsRes) richContent.push({ type: 'portfolio_stats', result: statsRes });

            const btResults = exec.filter(
              (r) => r.function_name === 'backtest_strategy' && r.status === 'success',
            ) as ExecutionResult[];
            if (btResults.length) {
              richContent.push({
                type: 'trades',
                results: btResults as import('@/types').BacktestResult[],
              });
            }

            if (exec.length) richContent.push({ type: 'telemetry', results: exec });
            richContent.push({
              type: 'text',
              markdown: (data.final_response as string) ?? '(no response)',
            });

            for (const c of richContent) {
              dispatch({ type: 'APPEND_CONTENT', id: msgId, content: c });
            }
          } else if (evt.type === 'error') {
            dispatch({
              type: 'APPEND_CONTENT',
              id: msgId,
              content: { type: 'error', msg: (evt as { type: 'error'; content: string }).content ?? 'Execution error' },
            });
          } else if (evt.type === 'done') {
            break;
          }
        }
      } catch (e) {
        dispatch({
          type: 'APPEND_CONTENT',
          id: msgId,
          content: { type: 'error', msg: `Approval failed: ${(e as Error).message}` },
        });
      }
    },
    [],
  );

  // ── handleReject ─────────────────────────────────────────────────────────
  const handleReject = useCallback(
    async (msgId: string, threadId: string, currentApiUrl: string) => {
      await reject(currentApiUrl, threadId);
      dispatch({
        type: 'APPEND_CONTENT',
        id: msgId,
        content: { type: 'text', markdown: '↩ Task execution cancelled.' },
      });
    },
    [],
  );

  return { state, send, newChat, handleApprove, handleReject };
}

// ── Semi-Auto flow ────────────────────────────────────────────────────────────

async function runSemiAuto(
  query: string,
  assistantId: string,
  backtestMode: boolean,
  apiUrl: string,
  dispatch: (a: Action) => void,
  threadId: string,
) {
  let interruptData: Record<string, unknown> | null = null;
  let finalText: string | null = null;

  const stream = streamQuery(apiUrl, { query, thread_id: threadId, backtest_mode: backtestMode });

  const nodeSet = new Set<string>();
  for await (const evt of stream) {
    if (evt.type === 'node') {
      const nd = (evt as { type: 'node'; data: { node: string; label: string; status: string } }).data;
      if (nd.status === 'started' && !nodeSet.has(nd.node)) {
        nodeSet.add(nd.node);
        dispatch({
          type: 'APPEND_CONTENT',
          id: assistantId,
          content: { type: 'tool_badge', name: nd.label },
        });
      }
    } else if (evt.type === 'thought_delta' && evt.agent && evt.token) {
      dispatch({ type: 'UPDATE_THINKING', id: assistantId, agent: evt.agent as string, token: evt.token as string });
    } else if (evt.type === 'reasoning' && evt.agent) {
      dispatch({
        type: 'FINALISE_THINKING',
        id: assistantId,
        agent: evt.agent as string,
        taskCount: ((evt.tasks as unknown[]) ?? []).length,
      });
    } else if (evt.type === 'interrupt') {
      interruptData = evt as Record<string, unknown>;
    } else if (evt.type === 'text' && evt.content) {
      finalText = evt.content as string;
    } else if (evt.type === 'error') {
      dispatch({
        type: 'APPEND_CONTENT',
        id: assistantId,
        content: { type: 'error', msg: evt.content as string ?? 'Unknown error' },
      });
    } else if (evt.type === 'done') {
      break;
    }
  }

  if (finalText) {
    dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'text', markdown: finalText } });
    return;
  }

  if (interruptData) {
    const tp = (interruptData.tasks_preview ?? {}) as Record<string, unknown>;
    const previewData: TaskPreviewData = {
      thread_id: (interruptData.thread_id as string) ?? threadId,
      portfolio_tasks: (tp.portfolio as TaskPreviewData['portfolio_tasks']) ?? [],
      quant_tasks:     (tp.quant as TaskPreviewData['quant_tasks'])     ?? [],
      backtester_tasks:(tp.backtester as TaskPreviewData['backtester_tasks']) ?? [],
      order_tasks:     (tp.order as TaskPreviewData['order_tasks'])     ?? [],
    };
    dispatch({
      type: 'APPEND_CONTENT',
      id: assistantId,
      content: { type: 'task_preview', data: previewData },
    });
  }
}

// ── Legacy (LangGraph / Agentic) stream ───────────────────────────────────────

async function runLegacyStream(
  query: string,
  assistantId: string,
  backtestMode: boolean,
  apiUrl: string,
  dispatch: (a: Action) => void,
  threadId: string,
) {
  const toolSet = new Set<string>();
  const stream = streamQuery(apiUrl, {
    query,
    thread_id: threadId,
    apply_middleware: true,
    backtest_mode: backtestMode,
  });

  for await (const evt of stream) {
    if (evt.type === 'reasoning' && evt.content) {
      dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'thinking', block: { agent: 'pm', content: evt.content as string } } });
    } else if (evt.type === 'text' && evt.content) {
      dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'text', markdown: evt.content as string } });
    } else if (evt.type === 'tool_call') {
      const name = 'data' in evt && evt.data && typeof evt.data === 'object' && 'function_name' in evt.data
        ? String(evt.data.function_name)
        : null;
      if (name && !toolSet.has(name)) {
        toolSet.add(name);
        dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'tool_badge', name } });
      }
    } else if (evt.type === 'node') {
      const NODE_LABELS: Record<string, string> = {
        portfolio_agent_node: 'portfolio agent',
        quant_router: 'quant router',
        backtester_router: 'backtester router',
        result_aggregator: 'aggregating results',
        synthesizer: 'synthesizer',
        classify_intent: 'classify intent',
        market_hours_guard: 'market hours',
        portfolio_guard: 'portfolio guard',
      };
      const nodeName = 'data' in evt && evt.data && typeof evt.data === 'object' && 'node' in evt.data
        ? String(evt.data.node)
        : null;
      const label = nodeName ? NODE_LABELS[nodeName] : null;
      if (label && nodeName && !toolSet.has(nodeName)) {
        toolSet.add(nodeName);
        dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'tool_badge', name: label } });
      }
    } else if (evt.type === 'error') {
      dispatch({ type: 'APPEND_CONTENT', id: assistantId, content: { type: 'error', msg: evt.content as string ?? 'Unknown error' } });
    } else if (evt.type === 'done') {
      break;
    }
  }
}

function extractToolName(content: unknown): string | null {
  if (!content) return null;
  if (typeof content === 'string') return content;
  if (typeof content === 'object') {
    const c = content as Record<string, unknown>;
    const msgs = (c.messages ?? []) as Record<string, unknown>[];
    for (const m of msgs) {
      if (m.name && typeof m.name === 'string') return m.name;
      const tcs = (m.tool_calls ?? []) as Record<string, unknown>[];
      for (const tc of tcs) {
        const fn = tc.function as Record<string, unknown> | undefined;
        if (fn?.name && typeof fn.name === 'string') return fn.name;
      }
    }
  }
  return 'tool';
}
