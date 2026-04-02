'use client';

import { useCallback, useEffect, useState } from 'react';
import { useChat } from '@/hooks/useChat';
import Header from '@/components/Header';
import MessageList from '@/components/MessageList';
import InputBar from '@/components/InputBar';

const DEFAULT_API = 'http://localhost:8001/v1';
const STORED_API  = 'pm_apiUrl';

export default function Page() {
  const { state, send, newChat, handleApprove, handleReject } = useChat();
  const { messages, isStreaming, threadId } = state;

  const [apiUrl, setApiUrlState] = useState<string>(DEFAULT_API);
  const [backtestMode, setBacktestMode] = useState(false);

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

  return (
    <>
      <Header
        apiUrl={apiUrl}
        onApiChange={setApiUrl}
        backtestMode={backtestMode}
        onBacktestToggle={setBacktestMode}
        threadId={threadId}
        onNewChat={newChat}
      />
      <MessageList
        messages={messages}
        onApprove={onApprove}
        onReject={onReject}
        onSuggestion={onSend}
      />
      <InputBar onSend={onSend} disabled={isStreaming} />
    </>
  );
}
