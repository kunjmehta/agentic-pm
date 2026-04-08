'use client';

import { useCallback, useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
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
import SandboxTab from '@/components/SandboxTab';

const DEFAULT_API = 'http://localhost:8000/v1';
const STORED_API  = 'pm_apiUrl';

type Tab = 'dashboard' | 'backtest' | 'config' | 'sandbox';

function PageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state, send, newChat, handleApprove, handleReject } = useChat();
  const { messages, isStreaming, threadId } = state;

  const [apiUrl, setApiUrlState] = useState<string>(DEFAULT_API);
  const [backtestMode, setBacktestMode] = useState(false);

  // Derive active tab from URL; default to 'dashboard'
  const tabParam = searchParams.get('tab') as Tab | null;
  const activeTab: Tab = tabParam && ['dashboard', 'backtest', 'config', 'sandbox'].includes(tabParam)
    ? tabParam
    : 'dashboard';

  const setActiveTab = useCallback((tab: Tab) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('tab', tab);
    // Clear sandbox param when leaving sandbox tab
    if (tab !== 'sandbox') params.delete('sandbox');
    router.push(`?${params.toString()}`);
  }, [router, searchParams]);

  // Hydrate apiUrl from localStorage on client
  useEffect(() => {
    const stored = localStorage.getItem(STORED_API);
    if (stored) setApiUrlState(stored);
  }, []);

  // Ensure 'tab' param exists in URL on first load
  useEffect(() => {
    if (!searchParams.get('tab')) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('tab', 'dashboard');
      router.replace(`?${params.toString()}`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const isChatCollapsed = activeTab === 'config' || activeTab === 'backtest' || activeTab === 'sandbox';

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
        <button
          className={`nav-tab ${activeTab === 'sandbox' ? 'active' : ''}`}
          onClick={() => setActiveTab('sandbox')}
        >
          Sandbox
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
          ) : activeTab === 'sandbox' ? (
            <SandboxTab apiUrl={apiUrl} />
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

export default function Page() {
  return (
    <Suspense fallback={null}>
      <PageInner />
    </Suspense>
  );
}
