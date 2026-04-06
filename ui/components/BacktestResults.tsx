/**
 * BacktestResults component - Historical backtest performance display
 *
 * Shows backtest results with filters for strategy, symbol, and date range.
 * Uses Bloomberg terminal styling with monospace fonts and orange accents.
 */

'use client';

import { useState, useMemo } from 'react';

interface BacktestTrade {
  id: string;
  strategy: string;
  symbol: string;
  side: 'buy' | 'sell';
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  pnl_pct: number;
}

interface BacktestSummary {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  total_pnl: number;
  avg_pnl: number;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown: number;
}

export default function BacktestResults() {
  const [trades] = useState<BacktestTrade[]>([
    // Mock data for demonstration
    {
      id: '1',
      strategy: 'mean-reversion',
      symbol: 'AAPL',
      side: 'buy',
      entry_date: '2024-01-15',
      exit_date: '2024-01-16',
      entry_price: 180.50,
      exit_price: 182.30,
      qty: 100,
      pnl: 180.00,
      pnl_pct: 1.0,
    },
  ]);

  // Filters
  const [strategyFilter, setStrategyFilter] = useState<string>('all');
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [dateRangeFilter, setDateRangeFilter] = useState<string>('30d');

  // Get unique strategies and symbols for filter dropdowns
  const strategies = useMemo(() => {
    const unique = new Set(trades.map((t) => t.strategy));
    return ['all', ...Array.from(unique)];
  }, [trades]);

  // Apply filters
  const filteredTrades = useMemo(() => {
    return trades.filter((trade) => {
      // Strategy filter
      if (strategyFilter !== 'all' && trade.strategy !== strategyFilter) {
        return false;
      }

      // Symbol filter
      if (symbolFilter && !trade.symbol.toLowerCase().includes(symbolFilter.toLowerCase())) {
        return false;
      }

      // Date range filter (simplified - implement proper date filtering)
      // For now, just return all trades
      return true;
    });
  }, [trades, strategyFilter, symbolFilter, dateRangeFilter]);

  // Calculate summary stats
  const summary: BacktestSummary = useMemo(() => {
    const winning = filteredTrades.filter((t) => t.pnl > 0);
    const losing = filteredTrades.filter((t) => t.pnl < 0);
    const totalPnl = filteredTrades.reduce((sum, t) => sum + t.pnl, 0);

    return {
      total_trades: filteredTrades.length,
      winning_trades: winning.length,
      losing_trades: losing.length,
      total_pnl: totalPnl,
      avg_pnl: filteredTrades.length > 0 ? totalPnl / filteredTrades.length : 0,
      win_rate: filteredTrades.length > 0 ? (winning.length / filteredTrades.length) * 100 : 0,
      sharpe_ratio: 1.5, // Mock value
      max_drawdown: -5.2, // Mock value
    };
  }, [filteredTrades]);

  return (
    <div className="bg-black border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-gray-900 px-4 py-2 border-b border-gray-800">
        <span className="text-orange-500 font-semibold text-sm font-mono">
          BACKTEST RESULTS
        </span>
      </div>

      {/* Filters */}
      <div className="bg-gray-950 px-4 py-3 border-b border-gray-800 flex gap-3 flex-wrap items-center">
        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">STRATEGY:</label>
          <select
            value={strategyFilter}
            onChange={(e) => setStrategyFilter(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded focus:outline-none focus:border-orange-500"
          >
            {strategies.map((s) => (
              <option key={s} value={s}>
                {s.toUpperCase()}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">SYMBOL:</label>
          <input
            type="text"
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value)}
            placeholder="Filter..."
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded w-24 focus:outline-none focus:border-orange-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">PERIOD:</label>
          <select
            value={dateRangeFilter}
            onChange={(e) => setDateRangeFilter(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded focus:outline-none focus:border-orange-500"
          >
            <option value="7d">7 DAYS</option>
            <option value="30d">30 DAYS</option>
            <option value="90d">90 DAYS</option>
            <option value="1y">1 YEAR</option>
            <option value="all">ALL TIME</option>
          </select>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="bg-gray-950 px-4 py-3 border-b border-gray-800 grid grid-cols-4 gap-4">
        <div className="text-center">
          <div className="text-gray-500 text-xs font-mono mb-1">TOTAL TRADES</div>
          <div className="text-white text-lg font-mono font-semibold">{summary.total_trades}</div>
        </div>
        <div className="text-center">
          <div className="text-gray-500 text-xs font-mono mb-1">WIN RATE</div>
          <div className="text-green-400 text-lg font-mono font-semibold">
            {summary.win_rate.toFixed(1)}%
          </div>
        </div>
        <div className="text-center">
          <div className="text-gray-500 text-xs font-mono mb-1">TOTAL P&L</div>
          <div className={`text-lg font-mono font-semibold ${summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${summary.total_pnl.toFixed(2)}
          </div>
        </div>
        <div className="text-center">
          <div className="text-gray-500 text-xs font-mono mb-1">SHARPE</div>
          <div className="text-orange-500 text-lg font-mono font-semibold">
            {summary.sharpe_ratio.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Trades Table */}
      <div className="overflow-auto max-h-96">
        {filteredTrades.length > 0 ? (
          <table className="w-full text-xs font-mono">
            <thead className="bg-gray-900 sticky top-0 z-10">
              <tr className="border-b border-gray-800">
                <th className="px-4 py-2 text-left text-gray-500">STRATEGY</th>
                <th className="px-4 py-2 text-left text-gray-500">SYMBOL</th>
                <th className="px-4 py-2 text-left text-gray-500">SIDE</th>
                <th className="px-4 py-2 text-right text-gray-500">ENTRY</th>
                <th className="px-4 py-2 text-right text-gray-500">EXIT</th>
                <th className="px-4 py-2 text-right text-gray-500">QTY</th>
                <th className="px-4 py-2 text-right text-gray-500">P&L</th>
                <th className="px-4 py-2 text-right text-gray-500">P&L %</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((trade) => (
                <tr
                  key={trade.id}
                  className="border-b border-gray-800 hover:bg-gray-900 transition-colors"
                >
                  <td className="px-4 py-2 text-gray-400">{trade.strategy}</td>
                  <td className="px-4 py-2 text-white font-semibold">{trade.symbol}</td>
                  <td className={`px-4 py-2 uppercase ${trade.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                    {trade.side}
                  </td>
                  <td className="px-4 py-2 text-right text-white">${trade.entry_price.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right text-white">${trade.exit_price.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right text-white">{trade.qty}</td>
                  <td className={`px-4 py-2 text-right font-semibold ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${trade.pnl.toFixed(2)}
                  </td>
                  <td className={`px-4 py-2 text-right font-semibold ${trade.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="h-64 flex items-center justify-center text-gray-600 text-sm font-mono">
            No backtest data available. Run a backtest to see results.
          </div>
        )}
      </div>
    </div>
  );
}
