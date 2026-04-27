'use client';

import { useEffect, useState } from 'react';

export interface TelemetryStep {
  node: string;
  label: string;
  status: 'pending' | 'active' | 'completed' | 'error';
  startTime?: number;
  endTime?: number;
  elapsedMs?: number;
}

export interface TelemetryState {
  steps: TelemetryStep[];
  currentStep: number;
  isConnected: boolean;
}

const NODE_LABELS: Record<string, string> = {
  portfolio_agent_node: 'Portfolio Agent',
  quant_router: 'Quant Router',
  backtester_router: 'Backtester',
  result_aggregator: 'Aggregator',
  synthesizer: 'Synthesizer',
  classify_intent: 'Intent Classifier',
  market_hours_guard: 'Market Hours',
  portfolio_guard: 'Portfolio Guard',
  data_availability_node: 'Data Availability',
  pm_decision_node: 'PM Decision',
  executor_node: 'Executor',
  order_node: 'Order Manager',
};

export function useTelemetry(apiUrl: string, threadId: string, enabled = true) {
  const [state, setState] = useState<TelemetryState>({
    steps: [],
    currentStep: -1,
    isConnected: false,
  });

  useEffect(() => {
    if (!enabled || !threadId) return;

    const controller = new AbortController();
    const url = `${apiUrl}/telemetry/stream/${threadId}`;

    async function connect() {
      try {
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) {
          console.error('Failed to connect to telemetry stream:', res.status);
          return;
        }

        setState((prev) => ({ ...prev, isConnected: true }));

        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;

            try {
              const event = JSON.parse(line.slice(6)) as Record<string, unknown>;

              if (event.type === 'node' && event.data && typeof event.data === 'object') {
                const data = event.data as { node: string; label?: string; status: 'started' | 'done' };
                const nodeName = data.node;
                const label = data.label ?? NODE_LABELS[nodeName] ?? nodeName;

                setState((prev) => {
                  const steps = [...prev.steps];
                  const existingIdx = steps.findIndex((s) => s.node === nodeName);

                  if (data.status === 'started') {
                    if (existingIdx >= 0) {
                      steps[existingIdx] = {
                        ...steps[existingIdx],
                        status: 'active',
                        startTime: Date.now(),
                      };
                    } else {
                      steps.push({
                        node: nodeName,
                        label,
                        status: 'active',
                        startTime: Date.now(),
                      });
                    }
                    return { ...prev, steps, currentStep: steps.length - 1 };
                  } else if (data.status === 'done' && existingIdx >= 0) {
                    const endTime = Date.now();
                    steps[existingIdx] = {
                      ...steps[existingIdx],
                      status: 'completed',
                      endTime,
                      elapsedMs: steps[existingIdx].startTime
                        ? endTime - steps[existingIdx].startTime!
                        : undefined,
                    };
                    return { ...prev, steps };
                  }

                  return prev;
                });
              } else if (event.type === 'error') {
                setState((prev) => {
                  if (prev.currentStep >= 0 && prev.currentStep < prev.steps.length) {
                    const steps = [...prev.steps];
                    steps[prev.currentStep] = {
                      ...steps[prev.currentStep],
                      status: 'error',
                      endTime: Date.now(),
                    };
                    return { ...prev, steps };
                  }
                  return prev;
                });
              } else if (event.type === 'done') {
                setState((prev) => ({ ...prev, isConnected: false }));
                break;
              }
            } catch (err) {
              console.warn('Failed to parse telemetry event:', err);
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Telemetry connection error:', err);
        }
      } finally {
        setState((prev) => ({ ...prev, isConnected: false }));
      }
    }

    connect();

    return () => {
      controller.abort();
    };
  }, [apiUrl, threadId, enabled]);

  return state;
}
