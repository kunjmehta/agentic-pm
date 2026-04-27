'use client';

import { useState } from 'react';
import { API_PRESETS, type ApiPreset } from '@/types';

interface Props {
  threadId: string;
  apiUrl: string;
  backtestMode: boolean;
  onApiChange: (url: string) => void;
  onBacktestToggle: (v: boolean) => void;
  onNewChat: () => void;
}

export default function Header({
  threadId,
  apiUrl,
  backtestMode,
  onApiChange,
  onBacktestToggle,
  onNewChat,
}: Props) {
  const [inputUrl, setInputUrl] = useState(apiUrl);

  const active = (Object.entries(API_PRESETS) as [ApiPreset, string][]).find(
    ([, v]) => v === inputUrl,
  )?.[0];

  function selectPreset(preset: ApiPreset) {
    const url = API_PRESETS[preset];
    setInputUrl(url);
    onApiChange(url);
  }

  function handleUrlChange(url: string) {
    setInputUrl(url);
    onApiChange(url);
  }

  return (
    <header className="header">
      <span className="header-title text-orange-500 font-mono">█ BLOOMBERG TERMINAL</span>
      <div className="header-right">
        {(['semiAuto'] as ApiPreset[]).map((p) => {
          const labels: Record<ApiPreset, string> = {
            langgraph: 'Graph',
            agentic: 'Agentic',
            semiAuto: 'Live Trading',
            custom: 'Custom',
          };
          return (
            <button
              key={p}
              className={`btn-api${active === p ? ' active' : ''}`}
              onClick={() => selectPreset(p)}
            >
              {labels[p]}
            </button>
          );
        })}
        <input
          className="api-url-input"
          value={inputUrl}
          placeholder="http://localhost:8001/v1"
          onChange={(e) => handleUrlChange(e.target.value)}
        />
        <label className="backtest-toggle" title="Bypass market-hours guard">
          <input
            type="checkbox"
            checked={backtestMode}
            onChange={(e) => onBacktestToggle(e.target.checked)}
          />
          backtest mode
        </label>
        <span className="thread-label" title={threadId}>
          {threadId.slice(0, 8)}…
        </span>
        <button className="btn-new" onClick={onNewChat}>
          + New Chat
        </button>
      </div>
    </header>
  );
}
