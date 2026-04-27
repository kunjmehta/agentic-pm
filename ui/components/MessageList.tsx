'use client';

import { useEffect, useRef } from 'react';
import type { Message } from '@/types';
import AssistantBubble from './AssistantBubble';

const SUGGESTIONS = [
  'What are my current portfolio positions?',
  'Run a backtest on AAPL using a 50/200 MA crossover',
  'Analyze market sentiment for TSLA',
  'What is my portfolio health status?',
];

interface Props {
  messages: Message[];
  onApprove: (msgId: string) => void;
  onReject: (msgId: string) => void;
  onSuggestion: (text: string) => void;
  apiUrl: string;
  threadId: string;
  backtestMode: boolean;
}

export default function MessageList({ messages, onApprove, onReject, onSuggestion, apiUrl, threadId, backtestMode }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (!messages.length) {
    return (
      <div className="messages">
        <div className="empty-state">
          <h2>Portfolio Manager</h2>
          <p>Ask anything about your portfolio, run backtests, or get market analysis.</p>
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => onSuggestion(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
        <div ref={bottomRef} />
      </div>
    );
  }

  return (
    <div className="messages">
      {messages.map((msg) => (
        <div key={msg.id} className={`msg-row ${msg.role}`}>
          {msg.role === 'user' ? (
            <div className="bubble user">{msg.content.map((c) => (c.type === 'text' ? c.markdown : '')).join('')}</div>
          ) : (
            <div className="bubble assistant">
              <AssistantBubble message={msg} onApprove={onApprove} onReject={onReject} apiUrl={apiUrl} threadId={threadId} backtestMode={backtestMode} />
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
