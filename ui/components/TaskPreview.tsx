'use client';

import { useState } from 'react';
import type { Task, TaskPreviewData } from '@/types';

const META_KEYS = new Set([
  'task_id', 'priority', 'depends_on', 'workflow_type',
  'note', 'metrics_requested', 'description', 'retry_count',
]);

function cleanParams(params: Record<string, unknown> = {}): Record<string, unknown> {
  return Object.fromEntries(Object.entries(params).filter(([k]) => !META_KEYS.has(k)));
}

interface TaskTableProps { label: string; tasks: Task[] }
function TaskTable({ label, tasks }: TaskTableProps) {
  if (!tasks.length) return null;
  return (
    <>
      <div className="task-table-label">{label}</div>
      <table className="task-table">
        <thead>
          <tr><th>ID</th><th>Function</th><th>Params</th><th>Pri</th><th>Depends on</th></tr>
        </thead>
        <tbody>
          {tasks.map((t, i) => {
            const clean = cleanParams(t.params);
            const paramStr = JSON.stringify(clean);
            const short = paramStr.length > 60 ? paramStr.slice(0, 57) + '…' : paramStr;
            const deps = (t.depends_on ?? []).join(', ') || '—';
            return (
              <tr key={i}>
                <td>{t.task_id ?? '?'}</td>
                <td>{t.function_name ?? '?'}</td>
                <td>
                  <details style={{ display: 'inline' }}>
                    <summary style={{ cursor: 'pointer', color: '#888', fontSize: 10, listStyle: 'none' }}>
                      {short}
                    </summary>
                    <pre style={{ marginTop: 4, padding: '4px 6px', background: 'rgba(0,0,0,0.35)', borderRadius: 4, fontSize: 10, color: '#9d9d9d', whiteSpace: 'pre-wrap', maxWidth: 360 }}>
                      {JSON.stringify(clean, null, 2)}
                    </pre>
                  </details>
                </td>
                <td>{t.priority ?? 1}</td>
                <td>{deps}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

interface AgentReasoningProps { label: string; text: string }
function AgentReasoning({ label, text }: AgentReasoningProps) {
  return (
    <details className="task-reasoning" open>
      <summary>{label}</summary>
      <div className="task-reasoning-body">{text}</div>
    </details>
  );
}

interface Props {
  data: TaskPreviewData;
  onApprove: () => void;
  onReject: () => void;
}

export default function TaskPreview({ data, onApprove, onReject }: Props) {
  const [busy, setBusy] = useState(false);

  async function handleApprove() {
    setBusy(true);
    await onApprove();
  }
  async function handleReject() {
    setBusy(true);
    await onReject();
  }

  const reasoningItems = [
    { key: 'portfolio_reasoning', label: '🏦 Portfolio Manager reasoning', text: data.portfolio_reasoning },
    { key: 'quant_reasoning',     label: '📊 Quant reasoning',             text: data.quant_reasoning },
    { key: 'backtester_reasoning',label: '📈 Backtester reasoning',        text: data.backtester_reasoning },
    { key: 'order_reasoning',     label: '📋 Order reasoning',             text: data.order_reasoning },
  ] as const;

  const queueItems = [
    { key: 'portfolio_tasks', label: 'Portfolio tasks', tasks: data.portfolio_tasks ?? [] },
    { key: 'quant_tasks',     label: 'Quant tasks',     tasks: data.quant_tasks ?? [] },
    { key: 'backtester_tasks',label: 'Backtester tasks',tasks: data.backtester_tasks ?? [] },
    { key: 'order_tasks',     label: 'Order tasks',     tasks: data.order_tasks ?? [] },
  ] as const;

  return (
    <div className="task-preview">
      <div className="task-preview-header">🔍 Task Preview — Review before execution</div>

      {reasoningItems.map(({ key, label, text }) =>
        text ? <AgentReasoning key={key} label={label} text={text} /> : null,
      )}

      {data.pm_review_notes && (
        <div style={{ background: '#0d1f0d', border: '1px solid #1a4a1a', borderRadius: 6, padding: '8px 12px', marginBottom: 8, fontSize: 12, color: '#6ee7b7' }}>
          <strong style={{ color: '#a3e6bc' }}>🤖 PM Review:</strong> {data.pm_review_notes}
        </div>
      )}

      {queueItems.map(({ key, label, tasks }) => (
        <TaskTable key={key} label={label} tasks={tasks as Task[]} />
      ))}

      <div className="approve-row">
        <button className="btn-approve" disabled={busy} onClick={handleApprove}>
          {busy ? '⏳ Executing…' : '✅ Approve & Execute'}
        </button>
        <button className="btn-reject" disabled={busy} onClick={handleReject}>
          ✗ Reject
        </button>
      </div>
    </div>
  );
}
