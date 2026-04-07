'use client';

import { useCallback, useEffect, useState } from 'react';
import { useChat } from '@/hooks/useChat';
import Header from '@/components/Header';
import Dashboard from '@/components/Dashboard';
import ChatPanel from '@/components/ChatPanel';
import ConfigPanel from '@/components/ConfigPanel';
import LiveTelemetry from '@/components/LiveTelemetry';
import LivePortfolio from '@/components/LivePortfolio';
import MarketTicker from '@/components/MarketTicker';
import OrderBook from '@/components/OrderBook';
import BacktestResults from '@/components/BacktestResults';

const DEFAULT_API = 'http://localhost:8000/v1';
const STORED_API  = 'pm_apiUrl';

type Tab = 'dashboard' | 'backtest' | 'config';

export default function Page() {
  const { state, send, newChat, handleApprove, handleReject } = useChat();
  const { messages, isStreaming, threadId } = state;

  const [apiUrl, setApiUrlState] = useState<string>(DEFAULT_API);
  const [backtestMode, setBacktestMode] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  // Hydrate apiUrl from localStorage on client
  useEffect(() => {
    const stored = localStorage.getItem(STORED_API);
    if (stored) setApiUrlState(stored);
  }, []);

  const setApiUrl = useCallback((url: string) => {
    localStorage.setItem(STORED_API, url);
    setApiUrlState(url);
  }, []);

  const onSend = useCallback(
    (text: string) => send(text, backtestMode, apiUrl),
    [send, backtestMode, apiUrl],
  );

  const onApprove = useCallback(
    (msgId: string) => handleApprove(msgId, threadId, apiUrl),
    [handleApprove, threadId, apiUrl],
  );

  const onReject = useCallback(
    (msgId: string) => handleReject(msgId, threadId, apiUrl),
    [handleReject, threadId, apiUrl],
  );

  const isChatCollapsed = activeTab === 'config' || activeTab === 'backtest';

  return (
    <div className="app-container">
      <Header
        apiUrl={apiUrl}
        onApiChange={setApiUrl}
        backtestMode={backtestMode}
        onBacktestToggle={setBacktestMode}
        threadId={threadId}
        onNewChat={newChat}
      />
      <nav className="nav-tabs">
        <button
          className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          Dashboard
        </button>
        <button
          className={`nav-tab ${activeTab === 'backtest' ? 'active' : ''}`}
          onClick={() => setActiveTab('backtest')}
        >
          Backtest
        </button>
        <button
          className={`nav-tab ${activeTab === 'config' ? 'active' : ''}`}
          onClick={() => setActiveTab('config')}
        >
          Config
        </button>
      </nav>
      <div className={`main-grid ${isChatCollapsed ? 'chat-collapsed' : ''}`}>
        <Dashboard>
          {activeTab === 'dashboard' ? (
            <>
              <MarketTicker apiUrl={apiUrl} />
              <LiveTelemetry apiUrl={apiUrl} threadId={threadId} enabled={isStreaming} />
              <LivePortfolio apiUrl={apiUrl} enabled />
              <OrderBook apiUrl={apiUrl} />
            </>
          ) : activeTab === 'backtest' ? (
            <>
              <BacktestResults apiUrl={apiUrl} />
            </>
          ) : (
            <ConfigPanel apiUrl={apiUrl} />
          )}
        </Dashboard>
        <ChatPanel
          messages={messages}
          isStreaming={isStreaming}
          onSend={onSend}
          onApprove={onApprove}
          onReject={onReject}
          isCollapsed={isChatCollapsed}
          apiUrl={apiUrl}
          threadId={threadId}
          backtestMode={backtestMode}
        />
      </div>
    </div>
  );
}
