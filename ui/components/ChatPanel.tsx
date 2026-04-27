'use client';

import { useState } from 'react';
import MessageList from './MessageList';
import InputBar from './InputBar';
import type { Message } from '@/types';

interface Props {
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onApprove: (msgId: string) => void;
  onReject: (msgId: string) => void;
  isCollapsed?: boolean;
  apiUrl: string;
  threadId: string;
  backtestMode: boolean;
}

export default function ChatPanel({
  messages,
  isStreaming,
  onSend,
  onApprove,
  onReject,
  isCollapsed = false,
  apiUrl,
  threadId,
  backtestMode,
}: Props) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (isCollapsed) {
    return null;
  }

  return (
    <div className={`chat-panel ${isExpanded ? 'expanded' : ''}`}>
      <div className="chat-header">
        <span className="chat-title">Agent Chat</span>
        <button
          className="chat-expand-btn"
          onClick={() => setIsExpanded(!isExpanded)}
          aria-label={isExpanded ? 'Collapse chat' : 'Expand chat'}
        >
          {isExpanded ? '←' : '→'}
        </button>
      </div>
      <MessageList
        messages={messages}
        onApprove={onApprove}
        onReject={onReject}
        onSuggestion={onSend}
        apiUrl={apiUrl}
        threadId={threadId}
        backtestMode={backtestMode}
      />
      <InputBar onSend={onSend} disabled={isStreaming} />
    </div>
  );
}
