'use client';

import type { BacktestResult, Trade } from '@/types';
import CompactTable, { type CompactTableColumn } from './CompactTable';

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
          <CompactTable
            columns={[
              { key: 'num', label: '#', align: 'left' },
              { key: 'side', label: 'Side', render: (v) => {
                const side = String(v ?? 'LONG').toUpperCase().slice(0, 5);
                const cls = side === 'LONG' || side === 'BUY' ? 'trade-buy' : 'trade-sell';
                return <span className={cls}>{side}</span>;
              }},
              { key: 'entry_date', label: 'Entry Date', sortable: true },
              { key: 'exit_date', label: 'Exit Date', sortable: true },
              { key: 'entry_price', label: 'Entry $', align: 'right', render: (v) => <span style={{ color: '#6ee7b7' }}>${fmtPrice(v)}</span> },
              { key: 'exit_price', label: 'Exit $', align: 'right', render: (v, row) => {
                const isClosed = row.exit_date != null;
                const color = isClosed ? '#f87171' : '#555';
                const val = isClosed ? `$${fmtPrice(v)}` : '—';
                return <span style={{ color }}>{val}</span>;
              }},
              { key: 'shares', label: 'Shares', align: 'right' },
              { key: 'exit_reason', label: 'Exit Reason', render: (v) => <span style={{ fontSize: 10, color: '#888' }}>{String(v ?? '—').replace(/_/g, ' ').slice(0, 18)}</span> },
              { key: 'pnl', label: 'P&L $', align: 'right', sortable: true, render: (v) => {
                const pnlNum = v !== null && v !== undefined ? Number(v) : null;
                if (pnlNum === null) return '—';
                const cls = pnlNum >= 0 ? 'trade-pnl-pos' : 'trade-pnl-neg';
                const str = (pnlNum >= 0 ? '+$' : '-$') + Math.abs(pnlNum).toFixed(2);
                return <span className={cls}>{str}</span>;
              }},
              { key: 'pnl_pct', label: 'P&L %', align: 'right', sortable: true, render: (v) => {
                const pnlPctNum = v !== null && v !== undefined ? Number(v) : null;
                if (pnlPctNum === null) return '—';
                const cls = pnlPctNum >= 0 ? 'trade-pnl-pos' : 'trade-pnl-neg';
                const str = (pnlPctNum >= 0 ? '+' : '') + pnlPctNum.toFixed(2) + '%';
                return <span className={cls}>{str}</span>;
              }},
            ]}
            data={trades.map((trade, i) => ({
              num: i + 1,
              side: trade.side ?? 'long',
              entry_date: fmtDate(trade.entry_date ?? trade.date ?? trade.timestamp),
              exit_date: trade.exit_date != null ? fmtDate(trade.exit_date) : '—',
              entry_price: trade.entry_price ?? trade.price,
              exit_price: trade.exit_price,
              shares: fmtShares(trade),
              exit_reason: trade.exit_date != null ? (trade.exit_reason ?? trade.reason ?? '—') : '—',
              pnl: trade.pnl ?? trade.profit_loss ?? null,
              pnl_pct: trade.pnl_pct ?? null,
            }))}
            maxRows={50}
            maxHeight={400}
            showExport
          />
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
