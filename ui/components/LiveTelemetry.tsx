'use client';

import { useTelemetry, type TelemetryStep } from '@/hooks/useTelemetry';
import { useEffect, useState } from 'react';

interface Props {
  apiUrl: string;
  threadId: string;
  enabled?: boolean;
}

function StepIndicator({ step, isActive }: { step: TelemetryStep; isActive: boolean }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (step.status === 'active' && step.startTime) {
      const interval = setInterval(() => {
        setElapsed(Date.now() - step.startTime!);
      }, 100);
      return () => clearInterval(interval);
    } else if (step.elapsedMs) {
      setElapsed(step.elapsedMs);
    }
  }, [step.status, step.startTime, step.elapsedMs]);

  const statusColors = {
    pending: '#555',
    active: '#2f6fdb',
    completed: '#10b981',
    error: '#ef4444',
  };

  const statusBg = {
    pending: '#2a2a2a',
    active: '#1e3a5f',
    completed: '#0d3a2a',
    error: '#3a1a1a',
  };

  const statusIcon = {
    pending: '⏸',
    active: '▶',
    completed: '✓',
    error: '✗',
  };

  const formatTime = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div
      className="telemetry-step"
      style={{
        background: statusBg[step.status],
        borderColor: statusColors[step.status],
        opacity: isActive || step.status !== 'pending' ? 1 : 0.5,
      }}
    >
      <div className="step-icon" style={{ color: statusColors[step.status] }}>
        {statusIcon[step.status]}
      </div>
      <div className="step-content">
        <div className="step-label">{step.label}</div>
        {step.status === 'active' && elapsed > 0 && (
          <div className="step-time">{formatTime(elapsed)}</div>
        )}
        {step.status === 'completed' && step.elapsedMs && (
          <div className="step-time completed">{formatTime(step.elapsedMs)}</div>
        )}
      </div>
    </div>
  );
}

export default function LiveTelemetry({ apiUrl, threadId, enabled = true }: Props) {
  const { steps, currentStep, isConnected } = useTelemetry(apiUrl, threadId, enabled);

  if (!enabled || steps.length === 0) {
    return null;
  }

  return (
    <div className="live-telemetry">
      <div className="telemetry-header">
        <span className="telemetry-title">Workflow Progress</span>
        {isConnected && <span className="telemetry-status connected">● Live</span>}
        {!isConnected && steps.length > 0 && (
          <span className="telemetry-status disconnected">○ Completed</span>
        )}
      </div>
      <div className="telemetry-stepper">
        {steps.map((step, idx) => (
          <StepIndicator key={`${step.node}-${idx}`} step={step} isActive={idx === currentStep} />
        ))}
      </div>
    </div>
  );
}
