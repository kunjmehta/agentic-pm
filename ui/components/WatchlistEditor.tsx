'use client';

import { useState } from 'react';
import type { WatchlistItem } from '@/hooks/useConfig';

interface Props {
  items: WatchlistItem[];
  availableStrategies: string[];
  onChange: (items: WatchlistItem[]) => void;
}

export default function WatchlistEditor({ items, availableStrategies, onChange }: Props) {
  const [newTicker, setNewTicker] = useState('');

  const safeItems = items ?? [];

  const addTicker = () => {
    const ticker = newTicker.trim().toUpperCase();
    if (!ticker) return;
    if (safeItems.some((item) => item.ticker === ticker)) {
      alert(`${ticker} already in watchlist`);
      return;
    }
    onChange([...safeItems, { ticker, strategies: [], enabled: true }]);
    setNewTicker('');
  };

  const removeTicker = (ticker: string) => {
    if (!confirm(`Remove ${ticker}?`)) return;
    onChange(safeItems.filter((item) => item.ticker !== ticker));
  };

  const toggleEnabled = (ticker: string) => {
    onChange(safeItems.map((item) =>
      item.ticker === ticker ? { ...item, enabled: !item.enabled } : item
    ));
  };

  const toggleStrategy = (ticker: string, strategy: string) => {
    onChange(safeItems.map((item) => {
      if (item.ticker !== ticker) return item;
      const strategies = item.strategies.includes(strategy)
        ? item.strategies.filter((s) => s !== strategy)
        : [...item.strategies, strategy];
      return { ...item, strategies };
    }));
  };

  return (
    <div className="bg-gray-950 border border-gray-800 rounded p-2">
      <div className="flex items-center justify-between mb-1.5">
        <h3 className="text-orange-500 font-mono text-xs font-semibold uppercase">Watchlist</h3>
        <div className="flex gap-1">
          <input
            type="text"
            className="bg-gray-900 border border-gray-700 text-white text-[10px] font-mono px-1.5 py-0.5 rounded w-16 focus:outline-none focus:border-orange-500"
            placeholder="AAPL"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addTicker()}
          />
          <button
            className="bg-orange-500 hover:bg-orange-600 text-black text-[10px] font-mono px-1.5 py-0.5 rounded font-semibold"
            onClick={addTicker}
          >
            + Add
          </button>
        </div>
      </div>

      {safeItems.length === 0 ? (
        <div className="text-gray-600 text-[10px] py-1">No tickers. Add one above.</div>
      ) : (
        <div className="space-y-px">
          {/* Column headers */}
          <div className="grid grid-cols-[3rem_1fr_1.5rem] gap-2 px-1 pb-0.5 border-b border-gray-800">
            <span className="text-gray-600 text-[10px] font-mono">TICKER</span>
            <span className="text-gray-600 text-[10px] font-mono">STRATEGIES</span>
          </div>

          {safeItems.map((item) => (
            <div
              key={item.ticker}
              className={`grid grid-cols-[3rem_1fr_1.5rem] gap-2 items-start px-1 py-1 rounded ${
                item.enabled ? '' : 'opacity-50'
              }`}
            >
              {/* Ticker + enable toggle */}
              <label className="flex items-center gap-1 cursor-pointer min-w-0">
                <input
                  type="checkbox"
                  checked={item.enabled}
                  onChange={() => toggleEnabled(item.ticker)}
                  className="accent-orange-500 flex-shrink-0"
                />
                <span className="text-white font-mono text-[11px] font-semibold truncate">
                  {item.ticker}
                </span>
              </label>

              {/* Strategy chips */}
              <div className="flex flex-wrap gap-0.5">
                {availableStrategies.map((strategy) => {
                  const isSelected = item.strategies.includes(strategy);
                  return (
                    <button
                      key={strategy}
                      title={strategy}
                      className={`text-[9px] font-mono px-1 py-px rounded transition-colors ${
                        isSelected
                          ? 'bg-orange-500 text-black font-semibold'
                          : 'bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300'
                      }`}
                      onClick={() => toggleStrategy(item.ticker, strategy)}
                    >
                      {strategy.replace(/_/g, ' ')}
                    </button>
                  );
                })}
                {item.strategies.length === 0 && (
                  <span className="text-red-400 text-[9px] italic">none selected</span>
                )}
              </div>

              {/* Remove */}
              <button
                className="text-gray-600 hover:text-red-400 text-[10px] text-right"
                onClick={() => removeTicker(item.ticker)}
                aria-label={`Remove ${item.ticker}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
