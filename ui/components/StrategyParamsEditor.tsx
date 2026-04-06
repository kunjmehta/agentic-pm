'use client';

import type { StrategyConfig } from '@/hooks/useConfig';

interface Props {
  strategies: StrategyConfig[];
  onChange: (strategies: StrategyConfig[]) => void;
}

const TIMEFRAME_OPTIONS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];

export default function StrategyParamsEditor({ strategies, onChange }: Props) {
  // Guard against undefined strategies
  const safeStrategies = strategies ?? [];

  const updateTimeframes = (strategyName: string, timeframes: string[]) => {
    onChange(
      safeStrategies.map((s) =>
        s.name === strategyName ? { ...s, timeframes } : s
      )
    );
  };

  const toggleTimeframe = (strategyName: string, timeframe: string) => {
    const strategy = safeStrategies.find((s) => s.name === strategyName);
    if (!strategy) return;

    const timeframes = strategy.timeframes.includes(timeframe)
      ? strategy.timeframes.filter((tf) => tf !== timeframe)
      : [...strategy.timeframes, timeframe];

    updateTimeframes(strategyName, timeframes);
  };

  const updateParam = (strategyName: string, paramKey: string, value: unknown) => {
    onChange(
      safeStrategies.map((s) =>
        s.name === strategyName
          ? { ...s, params: { ...s.params, [paramKey]: value } }
          : s
      )
    );
  };

  return (
    <div className="bg-gray-950 border border-gray-800 rounded p-2">
      <h3 className="text-orange-500 font-mono text-xs font-semibold uppercase mb-1.5">Strategy Parameters</h3>

      {safeStrategies.length === 0 ? (
        <div className="text-gray-600 text-[10px] py-1">No strategies configured</div>
      ) : (
        <div className="space-y-px">
          {safeStrategies.map((strategy) => (
            <details key={strategy.name} className="bg-gray-900 border border-gray-800 rounded group">
              <summary className="px-2 py-1 text-white text-[10px] font-mono font-semibold cursor-pointer select-none flex items-center gap-1.5">
                <span className="text-gray-500 group-open:rotate-90 transition-transform inline-block">▶</span>
                {strategy.name}
                <span className="ml-auto text-gray-600 font-normal">
                  {strategy.timeframes.join(', ') || 'no timeframes'}
                </span>
              </summary>

              <div className="px-2 pb-1.5 pt-1 border-t border-gray-800">
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-gray-500 text-[9px] font-mono w-16 shrink-0">Timeframes:</span>
                  <div className="flex flex-wrap gap-0.5">
                    {TIMEFRAME_OPTIONS.map((tf) => {
                      const isSelected = strategy.timeframes.includes(tf);
                      return (
                        <button
                          key={tf}
                          className={`text-[9px] font-mono px-1 py-px rounded transition-colors ${
                            isSelected
                              ? 'bg-orange-500 text-black font-semibold'
                              : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                          }`}
                          onClick={() => toggleTimeframe(strategy.name, tf)}
                        >
                          {tf}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {Object.keys(strategy.params).length > 0 && (
                  <div className="flex items-start gap-1">
                    <span className="text-gray-500 text-[9px] font-mono w-16 shrink-0 pt-0.5">Params:</span>
                    <div className="grid grid-cols-4 gap-1 flex-1">
                      {Object.entries(strategy.params).map(([key, value]) => (
                        <div key={key} className="flex flex-col gap-px">
                          <label className="text-gray-500 text-[9px] font-mono truncate" title={key}>{key}</label>
                          <input
                            type={typeof value === 'number' ? 'number' : 'text'}
                            className="bg-gray-800 border border-gray-700 text-white text-[9px] font-mono px-1 py-px rounded focus:outline-none focus:border-orange-500 w-full"
                            value={String(value)}
                            onChange={(e) => {
                              const newValue =
                                typeof value === 'number'
                                  ? parseFloat(e.target.value) || 0
                                  : e.target.value;
                              updateParam(strategy.name, key, newValue);
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
