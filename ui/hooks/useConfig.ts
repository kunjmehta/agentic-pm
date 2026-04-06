'use client';

import { useCallback, useEffect, useState } from 'react';

export interface StrategyConfig {
  name: string;
  timeframes: string[];
  params: Record<string, unknown>;
}

export interface WatchlistItem {
  ticker: string;
  strategies: string[];
  enabled: boolean;
}

export interface Config {
  watchlist: WatchlistItem[];
  strategies: StrategyConfig[];
  auto_compute_metrics: boolean;
}

export interface ConfigState {
  config: Config | null;
  isLoading: boolean;
  error: string | null;
  isSaving: boolean;
}

export function useConfig(apiUrl: string) {
  const [state, setState] = useState<ConfigState>({
    config: null,
    isLoading: true,
    error: null,
    isSaving: false,
  });

  const fetchConfig = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const res = await fetch(`${apiUrl}/config/ui`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const config = (await res.json()) as Config;
      setState({ config, isLoading: false, error: null, isSaving: false });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to load config';
      setState((prev) => ({ ...prev, isLoading: false, error: errorMsg }));
    }
  }, [apiUrl]);

  const saveConfig = useCallback(
    async (config: Config) => {
      setState((prev) => ({ ...prev, isSaving: true, error: null }));

      try {
        const res = await fetch(`${apiUrl}/config/ui`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });

        if (!res.ok) {
          const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
          throw new Error(errorData.detail || `HTTP ${res.status}: ${res.statusText}`);
        }

        const updatedConfig = (await res.json()) as Config;
        setState({ config: updatedConfig, isLoading: false, error: null, isSaving: false });
        return true;
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Failed to save config';
        setState((prev) => ({ ...prev, isSaving: false, error: errorMsg }));
        return false;
      }
    },
    [apiUrl]
  );

  const updateConfig = useCallback((config: Config) => {
    setState((prev) => ({ ...prev, config }));
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return {
    ...state,
    fetchConfig,
    saveConfig,
    updateConfig,
  };
}
