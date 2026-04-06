'use client';

import type { ExecutionResult } from '@/types';
import CompactTable from './CompactTable';

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
      <div style={{ padding: '8px 12px' }}>
        <CompactTable
          columns={[
            { key: 'task_id', label: 'Task ID', sortable: true },
            { key: 'function_name', label: 'Function', sortable: true },
            { key: 'status', label: 'Status', sortable: true, render: (v) => {
              const status = String(v);
              const color = status === 'success' ? '#6ee7b7' : status === 'error' ? '#f87171' : '#888';
              return <span style={{ color }}>{status}</span>;
            }},
            { key: 'duration_ms', label: 'Duration', align: 'right', sortable: true, render: (v) =>
              v != null ? `${Number(v).toFixed(0)} ms` : '—'
            },
          ]}
          data={results.map((r) => ({
            task_id: r.task_id ?? '—',
            function_name: r.function_name,
            status: r.status,
            duration_ms: r.duration_ms,
          }))}
          maxHeight={300}
        />
      </div>
    </details>
  );
}
