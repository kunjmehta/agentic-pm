'use client';

import type { ExecutionResult, PortfolioStatResult } from '@/types';

const STAT_DEFS: { key: keyof PortfolioStatResult; label: string }[] = [
  { key: 'equity',         label: 'Equity' },
  { key: 'cash',           label: 'Cash' },
  { key: 'unrealized_pl',  label: 'Unrealized P&L' },
  { key: 'realized_pl',    label: 'Realized P&L' },
  { key: 'daily_change',   label: 'Daily Change' },
  { key: 'total_return',   label: 'Total Return' },
  { key: 'sharpe_ratio',   label: 'Sharpe Ratio' },
  { key: 'max_drawdown',   label: 'Max Drawdown' },
  { key: 'win_rate',       label: 'Win Rate' },
  { key: 'position_count', label: 'Positions' },
];

interface Props { result: ExecutionResult }

export default function StatsSection({ result }: Props) {
  const d = result.result as PortfolioStatResult;
  if (!d) return null;
  const available = STAT_DEFS.filter((s) => d[s.key] !== undefined).slice(0, 8);
  if (!available.length) return null;

  return (
    <div className="stats-section">
      <div className="stats-section-header">Portfolio Stats</div>
      <div className="stats-cards">
        {available.map(({ key, label }) => {
          const val = d[key] as number;
          const isPos = typeof val === 'number' && val > 0;
          const isNeg = typeof val === 'number' && val < 0;
          const formatted =
            typeof val === 'number'
              ? Math.abs(val) >= 1000
                ? '$' + val.toLocaleString(undefined, { maximumFractionDigits: 0 })
                : val.toFixed(2)
              : String(val);
          return (
            <div className="stat-card" key={key}>
              <div className="sc-label">{label}</div>
              <div className={`sc-value${isPos ? ' positive' : isNeg ? ' negative' : ''}`}>
                {formatted}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
