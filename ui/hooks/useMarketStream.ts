/**
 * WebSocket hook for real-time market data streaming.
 *
 * Connects to /v1/market/ws and receives:
 * - trade_update: Real-time trade executions
 * - bar_update: Real-time 1-minute OHLCV bars
 *
 * Auto-reconnects on disconnect with exponential backoff.
 */

import { useEffect, useState, useRef, useCallback } from 'react';

export interface MarketMessage {
  type: 'trade_update' | 'bar_update' | 'connection' | 'error';
  symbol?: string;
  price?: number;
  size?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  vwap?: number | null;
  timestamp?: string;
  timeframe?: string;
  exchange?: string | null;
  message?: string;
}

interface UseMarketStreamOptions {
  apiUrl: string;
  onMessage: (msg: MarketMessage) => void;
  enabled?: boolean;
}

export function useMarketStream({
  apiUrl,
  onMessage,
  enabled = true,
}: UseMarketStreamOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(true);
  // Keep callback in a ref so changing it doesn't cause WS reconnection
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    const wsUrl = apiUrl.replace(/^http/, 'ws') + '/market/ws';

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const msg: MarketMessage = JSON.parse(event.data);
          if (msg.type === 'connection') {
            // silent
          } else if (msg.type === 'error') {
            setError(msg.message || 'Unknown error');
          } else {
            onMessageRef.current(msg);
          }
        } catch {
          setError('Failed to parse message');
        }
      };

      ws.onerror = () => {
        // onclose fires immediately after, which handles reconnect
      };

      ws.onclose = () => {
        // Guard: ignore close events from a WS that has already been superseded.
        // Without this, the old WS's onclose fires after connect() has assigned
        // a new WS to wsRef, clobbering the ref and scheduling a phantom reconnect.
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setIsConnected(false);

        if (shouldReconnectRef.current) {
          const backoffTime = Math.min(
            1000 * Math.pow(2, reconnectAttemptsRef.current),
            30000
          );
          reconnectAttemptsRef.current += 1;
          reconnectTimeoutRef.current = setTimeout(connect, backoffTime);
        }
      };
    } catch {
      setError('Failed to connect');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiUrl]);

  useEffect(() => {
    if (!enabled) return;

    shouldReconnectRef.current = true;
    connect();

    return () => {
      shouldReconnectRef.current = false;

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [apiUrl, enabled, connect]);

  return { isConnected, error };
}
