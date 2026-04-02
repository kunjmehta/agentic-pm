'use client';

import type { ExecutionResult } from '@/types';

interface Props { results: ExecutionResult[] }

export default function TelemetryPanel({ results }: Props) {
  if (!results.length) return null;
  const totalMs    = results.reduce((s, r) => s + (r.duration_ms ?? 0), 0);
  const errorCount = results.filter((r) => r.status === 'error').length;

  return (
    <details className="telemetry-detail">
      <summary>
        ⚡ Telemetry — {results.length} task{results.length !== 1 ? 's' : ''},{' '}
        {totalMs.toFixed(0)} ms{errorCount ? `, ${errorCount} error${errorCount !== 1 ? 's' : ''}` : ''}
      </summary>
      <table className="telemetry-table">
        <thead>
          <tr>
            <th>Task ID</th>
            <th>Function</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => (
            <tr key={r.task_id ?? i}>
              <td>{r.task_id ?? '—'}</td>
              <td>{r.function_name}</td>
              <td style={{ color: r.status === 'success' ? '#6ee7b7' : r.status === 'error' ? '#f87171' : '#888' }}>
                {r.status}
              </td>
              <td>{r.duration_ms != null ? `${r.duration_ms.toFixed(0)} ms` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
