'use client';

import type { ExecutionResult, HealthResult } from '@/types';

const COLOR_MAP: Record<string, { fg: string; bg: string }> = {
  healthy:  { fg: '#6ee7b7', bg: '#0a2a1a' },
  ok:       { fg: '#6ee7b7', bg: '#0a2a1a' },
  warning:  { fg: '#fde68a', bg: '#2a1a00' },
  critical: { fg: '#f87171', bg: '#2d1515' },
  unknown:  { fg: '#888',    bg: '#1a1a1a' },
};

const METRIC_KEYS: [keyof HealthResult, string][] = [
  ['equity',         'Equity'],
  ['cash',           'Cash'],
  ['buying_power',   'Buying Power'],
  ['position_count', 'Positions'],
  ['risk_score',     'Risk Score'],
  ['max_drawdown',   'Max Drawdown'],
  ['daily_pnl',      'Daily P&L'],
];

interface Props { result: ExecutionResult }

export default function HealthSection({ result }: Props) {
  const h = result.result as HealthResult;
  if (!h) return null;
  const overall = (h.overall_status ?? h.status ?? h.health_status ?? 'unknown').toLowerCase();
  const col = COLOR_MAP[overall] ?? COLOR_MAP.unknown;
  const desc = h.reason ?? h.description ?? h.message ?? '';

  return (
    <div
      className="health-section"
      style={{ borderColor: col.fg + '44', background: col.bg }}
    >
      <div className="health-section-header">Portfolio Health</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          className="health-badge"
          style={{ color: col.fg, borderColor: col.fg + '66', background: col.fg + '18' }}
        >
          {overall.toUpperCase()}
        </span>
        {desc && (
          <span style={{ fontSize: 12, color: '#aaa' }}>
            {String(desc).slice(0, 120)}
          </span>
        )}
      </div>
      <div className="health-metrics">
        {METRIC_KEYS.slice(0, 6).map(([k, label]) =>
          h[k] !== undefined ? (
            <div className="hm-row" key={k}>
              <span className="hm-key">{label}:</span>
              <span className="hm-val">{String(h[k])}</span>
            </div>
          ) : null,
        )}
      </div>
    </div>
  );
}
