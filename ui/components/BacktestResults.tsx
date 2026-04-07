/**
 * BacktestResults component - Historical backtest performance display with scheduled backtests
 *
 * Shows:
 * 1. Scheduled post-EOD backtests (editable)
 * 2. Historical backtest results from backtest.duckdb
 *
 * Uses Bloomberg terminal styling with monospace fonts and orange accents.
 */

'use client';

import { useState, useEffect, useMemo } from 'react';
import { BacktestEditor } from './BacktestEditor';

interface ScheduledBacktest {
  name: string;
  description: string;
  strategy: string;
  workflow_type: string;
  prompt: string;
  timeframe: string;
  lookback_days: number;
  parameters: Record<string, any>;
}

interface BacktestRun {
  run_id: string;
  strategy_name: string;
  symbol?: string;
  start_date: string;
  end_date: string;
  total_return_pct?: number;
  sharpe_ratio?: number;
  max_drawdown_pct?: number;
  win_rate?: number;
  total_trades?: number;
}

interface Props {
  apiUrl: string;
}

export default function BacktestResults({ apiUrl }: Props) {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [scheduledBacktests, setScheduledBacktests] = useState<ScheduledBacktest[]>([]);
  const [editingBacktest, setEditingBacktest] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load data on mount
  useEffect(() => {
    loadData();
  }, [apiUrl]);

  const loadData = async () => {
    setLoading(true);
    try {
      // Load scheduled backtest configs
      const configRes = await fetch(`${apiUrl}/config/scheduled_backtests`);
      if (configRes.ok) {
        const configData = await configRes.json();
        const backtests = configData.config?.default_backtests || configData.default_backtests || [];
        setScheduledBacktests(backtests);
      }

      // Load backtest runs from /backtest/runs API
      const runsRes = await fetch(`${apiUrl}/backtest/runs?limit=50`);
      if (runsRes.ok) {
        const runsData = await runsRes.json();
        setRuns(runsData.runs || []);
      }
    } catch (error) {
      console.error('Failed to load backtest data:', error);
    } finally {
      setLoading(false);
    }
  };

  const updateBacktest = async (name: string, updates: Partial<ScheduledBacktest>) => {
    try {
      // Fetch current config section
      const getRes = await fetch(`${apiUrl}/config/scheduled_backtests`);
      if (!getRes.ok) {
        throw new Error('Failed to fetch current config');
      }

      const currentData = await getRes.json();
      const config = currentData.config || currentData;

      // Find and update the backtest
      const backtests = config.default_backtests || [];
      const idx = backtests.findIndex((bt: ScheduledBacktest) => bt.name === name);

      if (idx === -1) {
        throw new Error(`Backtest ${name} not found`);
      }

      backtests[idx] = { ...backtests[idx], ...updates };

      // Update the entire section
      const putRes = await fetch(`${apiUrl}/config/scheduled_backtests`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: { ...config, default_backtests: backtests } })
      });

      if (putRes.ok) {
        // Reload configs
        await loadData();
        setEditingBacktest(null);
      } else {
        const errorData = await putRes.json().catch(() => ({}));
        console.error('Failed to update backtest:', errorData);
        alert(`Failed to update backtest: ${errorData.detail || putRes.statusText}`);
      }
    } catch (error) {
      console.error('Failed to update backtest:', error);
      alert(`Failed to update backtest: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const getWorkflowIcon = (workflow_type: string) => {
    switch (workflow_type) {
      case 'A': return '🛡️';
      case 'B': return '⚡';
      case 'C': return '📈';
      default: return '📊';
    }
  };

  if (loading) {
    return (
      <div className="bg-black border border-gray-800 rounded-lg overflow-hidden p-8 text-center">
        <div className="text-gray-500 font-mono text-sm">Loading backtest data...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Scheduled Backtests Section */}
      <div className="bg-black border border-gray-800 rounded-lg overflow-hidden">
        <div className="bg-gray-900 px-4 py-2 border-b border-gray-800">
          <span className="text-orange-500 font-semibold text-sm font-mono">
            SCHEDULED POST-EOD BACKTESTS
          </span>
        </div>

        <div className="p-4">
          <p className="text-sm text-gray-400 mb-4 font-mono">
            These backtests run automatically after market close (4 PM ET) every trading day.
          </p>

          <div className="space-y-4">
            {scheduledBacktests.map((bt) => (
              <div key={bt.name} className="bg-gray-900 border border-gray-700 rounded p-3">
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <h3 className="font-semibold text-white font-mono text-sm">
                      {getWorkflowIcon(bt.workflow_type)} {bt.name}
                    </h3>
                    <p className="text-xs text-gray-400 font-mono mt-1">{bt.description}</p>
                  </div>
                  <button
                    onClick={() => setEditingBacktest(bt.name === editingBacktest ? null : bt.name)}
                    className="text-blue-400 text-xs font-mono hover:underline"
                  >
                    {bt.name === editingBacktest ? 'Cancel' : 'Edit'}
                  </button>
                </div>

                {bt.name === editingBacktest ? (
                  <BacktestEditor
                    backtest={bt}
                    onSave={(updates) => updateBacktest(bt.name, updates)}
                    onCancel={() => setEditingBacktest(null)}
                  />
                ) : (
                  <div className="text-xs text-gray-300 font-mono space-y-1">
                    <div><span className="text-gray-500">Strategy:</span> {bt.strategy}</div>
                    <div><span className="text-gray-500">Timeframe:</span> {bt.timeframe}</div>
                    <div><span className="text-gray-500">Lookback:</span> {bt.lookback_days} days</div>
                    <div className="mt-2 bg-black p-2 rounded font-mono text-xs text-gray-400 border border-gray-800">
                      {bt.prompt}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Backtest Results */}
      <div className="bg-black border border-gray-800 rounded-lg overflow-hidden">
        <div className="bg-gray-900 px-4 py-2 border-b border-gray-800">
          <span className="text-orange-500 font-semibold text-sm font-mono">
            RECENT BACKTEST RESULTS
          </span>
        </div>

        <div className="overflow-x-auto">
          {runs.length > 0 ? (
            <table className="w-full text-xs font-mono">
              <thead className="text-gray-400 bg-gray-950 sticky top-0">
                <tr className="border-b border-gray-800">
                  <th className="text-left p-2">RUN ID</th>
                  <th className="text-left p-2">STRATEGY</th>
                  <th className="text-left p-2">SYMBOL</th>
                  <th className="text-left p-2">PERIOD</th>
                  <th className="text-right p-2">RETURN</th>
                  <th className="text-right p-2">SHARPE</th>
                  <th className="text-right p-2">MAX DD</th>
                  <th className="text-right p-2">WIN RATE</th>
                </tr>
              </thead>
              <tbody className="text-white">
                {runs.map((run) => (
                  <tr key={run.run_id} className="border-b border-gray-800 hover:bg-gray-900">
                    <td className="p-2 font-mono text-xs">{run.run_id.slice(0, 8)}</td>
                    <td className="p-2">{run.strategy_name}</td>
                    <td className="p-2">{run.symbol || 'Multi'}</td>
                    <td className="p-2 text-xs">
                      {run.start_date} to {run.end_date}
                    </td>
                    <td className={`p-2 text-right ${run.total_return_pct && run.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {run.total_return_pct?.toFixed(2)}%
                    </td>
                    <td className="p-2 text-right">{run.sharpe_ratio?.toFixed(2)}</td>
                    <td className="p-2 text-right text-red-400">{run.max_drawdown_pct?.toFixed(2)}%</td>
                    <td className="p-2 text-right">{run.win_rate?.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-600 text-sm font-mono">
              No backtest results yet. Backtests will appear here after running.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
