'use client';

import type { ExecutionResult } from '@/types';

interface Props { results: ExecutionResult[] }

export default function ExecSummary({ results }: Props) {
  if (!results.length) return null;
  return (
    <div className="exec-summary">
      {results.map((r, i) => (
        <div className="exec-summary-row" key={r.task_id ?? i}>
          <span className="esid">{r.task_id ?? '—'}</span>
          <span className="esfn">{r.function_name}</span>
          <span className={`esstatus ${r.status}`}>{r.status}</span>
          {r.duration_ms != null && (
            <span className="esdur">{r.duration_ms.toFixed(0)} ms</span>
          )}
        </div>
      ))}
    </div>
  );
}
