'use client';

import { useState, useEffect } from 'react';
import { useConfig, type Config } from '@/hooks/useConfig';
import WatchlistEditor from './WatchlistEditor';
import StrategyParamsEditor from './StrategyParamsEditor';

interface Props {
  apiUrl: string;
}

export default function ConfigPanel({ apiUrl }: Props) {
  const { config, isLoading, error, isSaving, saveConfig, updateConfig, fetchConfig } =
    useConfig(apiUrl);

  const [draftConfig, setDraftConfig] = useState<Config | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    if (config) {
      setDraftConfig(JSON.parse(JSON.stringify(config)));
      setHasChanges(false);
    }
  }, [config]);

  const handleSave = async () => {
    if (!draftConfig) return;

    // Validation
    const hasEmptyStrategies = draftConfig.watchlist.some(
      (item) => item.enabled && item.strategies.length === 0
    );

    if (hasEmptyStrategies) {
      alert('Some enabled tickers have no strategies assigned. Please assign strategies or disable those tickers.');
      return;
    }

    const success = await saveConfig(draftConfig);
    if (success) {
      setHasChanges(false);
    }
  };

  const handleReset = () => {
    if (!hasChanges || confirm('Discard all changes and reset to saved configuration?')) {
      fetchConfig();
    }
  };

  const updateDraftConfig = (updates: Partial<Config>) => {
    if (!draftConfig) return;
    const updated = { ...draftConfig, ...updates };
    setDraftConfig(updated);
    setHasChanges(JSON.stringify(updated) !== JSON.stringify(config));
  };

  if (isLoading) {
    return (
      <div className="config-panel">
        <div className="config-loading">Loading configuration...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="config-panel">
        <div className="config-error">
          <strong>Error:</strong> {error}
          <button className="btn-retry" onClick={fetchConfig}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!draftConfig) {
    return null;
  }

  const availableStrategies = draftConfig.strategies?.map((s) => s.name) ?? [];

  return (
    <div className="config-panel bg-black">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800 bg-gray-950">
        <h2 className="text-orange-500 font-mono text-xs font-semibold uppercase tracking-wider">█ Configuration</h2>
        <div className="flex items-center gap-3">
          {hasChanges && <span className="text-amber-400 text-[10px] font-mono">● Unsaved</span>}
          <button
            className="bg-gray-800 hover:bg-gray-700 text-white text-[10px] font-mono px-2 py-0.5 rounded border border-gray-700"
            onClick={handleReset}
            disabled={!hasChanges || isSaving}
          >
            Reset
          </button>
          <button
            className="bg-orange-500 hover:bg-orange-600 text-black text-[10px] font-mono px-2 py-0.5 rounded font-semibold"
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      <div className="p-2 space-y-2 overflow-auto max-h-[calc(100vh-120px)]">
        <WatchlistEditor
          items={draftConfig.watchlist}
          availableStrategies={availableStrategies}
          onChange={(watchlist) => updateDraftConfig({ watchlist })}
        />

        <StrategyParamsEditor
          strategies={draftConfig.strategies}
          onChange={(strategies) => updateDraftConfig({ strategies })}
        />

        <div className="bg-gray-950 border border-gray-800 rounded p-2">
          <h3 className="text-orange-500 font-mono text-xs font-semibold uppercase mb-2">Settings</h3>
          <label className="flex items-center gap-2 cursor-pointer text-white text-xs">
            <input
              type="checkbox"
              checked={draftConfig.auto_compute_metrics}
              onChange={(e) =>
                updateDraftConfig({ auto_compute_metrics: e.target.checked })
              }
              className="accent-orange-500"
            />
            <span className="font-mono text-xs">Auto-compute metrics</span>
          </label>
        </div>
      </div>
    </div>
  );
}
