'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message, MessageContent } from '@/types';
import ThinkingSection from './ThinkingSection';
import ToolBadge from './ToolBadge';
import TaskPreview from './TaskPreview';
import HealthSection from './HealthSection';
import StatsSection from './StatsSection';
import TradesSection from './TradesSection';
import TelemetryPanel from './TelemetryPanel';
import ExecSummary from './ExecSummary';

interface Props {
  message: Message;
  onApprove?: (msgId: string) => void;
  onReject?: (msgId: string) => void;
  apiUrl: string;
  threadId: string;
  backtestMode: boolean;
}

function renderBlock(block: MessageContent, idx: number, msg: Message, onApprove?: Props['onApprove'], onReject?: Props['onReject'], apiUrl?: string, threadId?: string, backtestMode?: boolean) {
  switch (block.type) {
    case 'thinking':
      return <ThinkingSection key={`thinking-${block.block.agent}-${idx}`} block={block.block} />;

    case 'tool_badge':
      return <ToolBadge key={`tool-${block.name}-${idx}`} name={block.name} />;

    case 'text':
      return (
        <div className="text-content" key={`text-${idx}`}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.markdown}</ReactMarkdown>
        </div>
      );

    case 'error':
      return <div className="error-block" key={`error-${idx}`}>⚠ {block.msg}</div>;

    case 'task_preview':
      if (!onApprove || !onReject || !apiUrl || !threadId || backtestMode === undefined) return null;
      return (
        <TaskPreview
          key={`preview-${idx}`}
          data={block.data}
          onApprove={() => onApprove(msg.id)}
          onReject={() => onReject(msg.id)}
          apiUrl={apiUrl}
          threadId={threadId}
          backtestMode={backtestMode}
        />
      );

    case 'health':
      return <HealthSection key={`health-${idx}`} result={block.result} />;

    case 'portfolio_stats':
      return <StatsSection key={`stats-${idx}`} result={block.result} />;

    case 'trades':
      return <TradesSection key={`trades-${idx}`} results={block.results} />;

    case 'telemetry':
      return <TelemetryPanel key={`telemetry-${idx}`} results={block.results} />;

    case 'exec_summary':
      return <ExecSummary key={`exec-${idx}`} results={block.results} />;

    case 'pending_notice':
      return (
        <p key={`pending-${idx}`} style={{ color: '#555', fontFamily: "'Courier New', monospace", fontSize: 10, margin: '3px 0' }}>
          Awaiting approval...
        </p>
      );

    default:
      return null;
  }
}

export default function AssistantBubble({ message, onApprove, onReject, apiUrl, threadId, backtestMode }: Props) {
  const isEmpty = message.content.length === 0;
  return (
    <>
      {isEmpty && message.isStreaming ? (
        <span className="spinner" />
      ) : (
        message.content.map((block, i) => renderBlock(block, i, message, onApprove, onReject, apiUrl, threadId, backtestMode))
      )}
    </>
  );
}
