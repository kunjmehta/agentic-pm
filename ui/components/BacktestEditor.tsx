/**
 * BacktestEditor component - Edit scheduled backtest configurations
 *
 * Allows users to modify backtest prompts and parameters for
 * scheduled post-EOD backtesting.
 */

'use client';

import { useState } from 'react';

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

interface BacktestEditorProps {
  backtest: ScheduledBacktest;
  onSave: (updates: Partial<ScheduledBacktest>) => void;
  onCancel: () => void;
}

export function BacktestEditor({ backtest, onSave, onCancel }: BacktestEditorProps) {
  const [prompt, setPrompt] = useState(backtest.prompt);
  const [lookbackDays, setLookbackDays] = useState(backtest.lookback_days);

  const handleSave = () => {
    onSave({
      prompt,
      lookback_days: lookbackDays
    });
  };

  return (
    <div className="space-y-3 mt-3 bg-gray-950 border border-gray-700 rounded p-4">
      <div>
        <label className="block text-sm text-gray-300 mb-2 font-mono uppercase tracking-wide">
          Backtest Prompt:
        </label>
        <textarea
          className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-orange-500"
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <p className="text-xs text-gray-500 mt-1 font-mono">
          Define the backtest strategy and parameters. Use {'{symbol}'} as a placeholder for the ticker.
        </p>
      </div>

      <div>
        <label className="block text-sm text-gray-300 mb-2 font-mono uppercase tracking-wide">
          Lookback Days:
        </label>
        <input
          type="number"
          min="1"
          max="365"
          className="w-32 bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-orange-500"
          value={lookbackDays}
          onChange={(e) => setLookbackDays(parseInt(e.target.value) || 1)}
        />
        <p className="text-xs text-gray-500 mt-1 font-mono">
          Number of days of historical data to analyze (1-365)
        </p>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={handleSave}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 font-mono text-sm uppercase tracking-wide transition-colors"
        >
          Save Changes
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600 font-mono text-sm uppercase tracking-wide transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
