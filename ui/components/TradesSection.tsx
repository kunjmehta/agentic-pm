'use client';

import type { BacktestResult, Trade } from '@/types';

function fmtPrice(v: unknown): string {
  const n = Number(v);
  return isNaN(n) ? '—' : n.toFixed(2);
}
function fmtShares(t: Trade): string {
  const v = t.quantity ?? t.shares ?? t.qty;
  return v !== undefined ? String(v) : '—';
}
function fmtDate(v: unknown): string {
  return v ? String(v).substring(0, 10) : '—';
}
function fmtTime(v: unknown): string {
  if (!v) return '—';
  const s = String(v);
  const m = s.match(/T?(\d{2}:\d{2})/);
  return m ? m[1] : s.substring(11, 16) || s.substring(0, 10);
}
function signalLabel(sig: unknown): string {
  if (!sig || typeof sig !== 'object') return '—';
  const s = sig as Record<string, unknown>;
  return (s.signal ?? s.type ?? Object.keys(s)[0] ?? '—') as string;
}

interface SingleBacktestProps { btRes: BacktestResult }

function SingleBacktest({ btRes }: SingleBacktestProps) {
  const d = btRes.result ?? {};
  const trades = d.trades ?? [];
  const strategy = d.strategy ?? d.strategy_name ?? btRes.task_id ?? 'backtest';
  const symbol = d.symbol ?? d.ticker ?? '';
  const closed = trades.filter((t) => t.exit_date != null);
  const open = trades.filter((t) => t.exit_date == null);
  const metrics = d.metrics ?? {};

  const perfItems = [
    { label: 'Return',   val: metrics.total_return_pct !== undefined ? (Number(metrics.total_return_pct) >= 0 ? '+' : '') + Number(metrics.total_return_pct).toFixed(2) + '%' : null, signed: true },
    { label: 'Sharpe',   val: metrics.sharpe_ratio !== undefined ? Number(metrics.sharpe_ratio).toFixed(3) : null, signed: false },
    { label: 'Max DD',   val: metrics.max_drawdown_pct !== undefined ? Number(metrics.max_drawdown_pct).toFixed(2) + '%' : null, signed: true },
    { label: 'Win Rate', val: metrics.win_rate !== undefined ? (Number(metrics.win_rate) * (Number(metrics.win_rate) <= 1 ? 100 : 1)).toFixed(1) + '%' : null, signed: false },
    { label: 'Final Cap',val: d.final_capital !== undefined ? '$' + Number(d.final_capital).toLocaleString('en-US', { maximumFractionDigits: 0 }) : null, signed: false },
  ];

  return (
    <details className="trades-detail">
      <summary>
        📈 Trades — {strategy}{symbol ? ` · ${symbol}` : ' '}
        <span style={{ color: '#6ee7b7', fontWeight: 400, fontSize: 10 }}> {trades.length} entries</span>
        <span style={{ color: '#f87171', fontWeight: 400, fontSize: 10 }}> {closed.length} exits</span>
        {open.length > 0 && <span style={{ color: '#a78bfa', fontWeight: 400, fontSize: 10 }}> {open.length} open</span>}
      </summary>

      {/* Performance bar */}
      {perfItems.some((p) => p.val !== null) && (
        <div style={{ padding: '5px 12px', display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, fontFamily: 'monospace', borderBottom: '1px solid #2a2a00' }}>
          {perfItems.map(({ label, val, signed }) => {
            if (!val) return null;
            const n = parseFloat(val);
            const c = signed ? (n > 0 ? '#6ee7b7' : n < 0 ? '#f87171' : '#bbb') : '#bbb';
            return (
              <span key={label}>
                <span style={{ color: '#555' }}>{label}: </span>
                <span style={{ color: c }}>{val}</span>
              </span>
            );
          })}
        </div>
      )}

      {trades.length === 0 ? (
        <div style={{ padding: '8px 12px', fontSize: 11, color: '#555' }}>No trade records in result.</div>
      ) : (
        <>
          {/* Unified Trades table (closed + open, all columns) */}
          <table className="trades-table">
            <thead>
              <tr>
                <th className="tc-num">#</th>
                <th>Side</th>
                <th>Entry Date</th>
                <th>Exit Date</th>
                <th style={{ textAlign: 'right' }}>Entry $</th>
                <th style={{ textAlign: 'right' }}>Exit $</th>
                <th style={{ textAlign: 'right' }}>Shares</th>
                <th>Exit Reason</th>
                <th style={{ textAlign: 'right' }}>P&amp;L $</th>
                <th style={{ textAlign: 'right' }}>P&amp;L %</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 200).map((trade, i) => {
                const isClosed = trade.exit_date != null;
                const side = (trade.side ?? 'long').toUpperCase().slice(0, 5);
                const entryDate = fmtDate(trade.entry_date ?? trade.date ?? trade.timestamp);
                const exitDate = isClosed ? fmtDate(trade.exit_date) : '—';
                const ep = fmtPrice(trade.entry_price ?? trade.price);
                const xp = isClosed ? fmtPrice(trade.exit_price) : '—';
                const shares = fmtShares(trade);
                const reason = isClosed
                  ? String(trade.exit_reason ?? trade.reason ?? '—').replace(/_/g, ' ')
                  : '—';

                const pnlRaw = trade.pnl ?? trade.profit_loss ?? null;
                const pnlPctRaw = trade.pnl_pct ?? null;
                const pnlNum = pnlRaw !== null ? Number(pnlRaw) : null;
                const pnlPctNum = pnlPctRaw !== null ? Number(pnlPctRaw) : null;
                const pnlCls = pnlNum !== null ? (pnlNum >= 0 ? 'trade-pnl-pos' : 'trade-pnl-neg') : '';
                const pnlStr = pnlNum !== null
                  ? (pnlNum >= 0 ? '+$' : '-$') + Math.abs(pnlNum).toFixed(2)
                  : '—';
                const pnlPctStr = pnlPctNum !== null
                  ? (pnlPctNum >= 0 ? '+' : '') + pnlPctNum.toFixed(2) + '%'
                  : '—';

                return (
                  <tr key={i}>
                    <td className="tc-num">{i + 1}</td>
                    <td className={side === 'LONG' || side === 'BUY' ? 'trade-buy' : 'trade-sell'}>{side}</td>
                    <td>{entryDate}</td>
                    <td>{exitDate}</td>
                    <td style={{ textAlign: 'right', color: '#6ee7b7' }}>${ep}</td>
                    <td style={{ textAlign: 'right', color: isClosed ? '#f87171' : '#555' }}>{isClosed ? `$${xp}` : '—'}</td>
                    <td style={{ textAlign: 'right' }}>{shares}</td>
                    <td style={{ fontSize: 10, color: '#888' }}>{reason.slice(0, 18)}</td>
                    <td style={{ textAlign: 'right' }} className={pnlCls}>{pnlStr}</td>
                    <td style={{ textAlign: 'right' }} className={pnlCls}>{pnlPctStr}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {trades.length > 200 && (
            <div style={{ padding: '2px 8px 4px', fontSize: 10, color: '#555', fontFamily: 'monospace' }}>
              … {trades.length - 200} more trades not shown
            </div>
          )}
          {open.length > 0 && (
            <div className="trades-open-note">
              ⏳ {open.length} position{open.length !== 1 ? 's' : ''} still open at end of backtest
            </div>
          )}
        </>
      )}
    </details>
  );
}

interface Props { results: BacktestResult[] }

export default function TradesSection({ results }: Props) {
  if (!results.length) return null;
  return (
    <div className="trades-section">
      {results.map((r) => <SingleBacktest key={r.task_id} btRes={r} />)}
    </div>
  );
}
