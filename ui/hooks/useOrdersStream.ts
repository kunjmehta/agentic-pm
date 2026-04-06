/**
 * WebSocket hook for real-time order updates streaming.
 *
 * Connects to /v1/orders/ws and receives:
 * - order_update: Order status changes (submitted, filled, cancelled, rejected)
 *
 * Auto-reconnects on disconnect with exponential backoff.
 */

import { useEffect, useState, useRef, useCallback } from 'react';

export interface OrderMessage {
  type: 'order_update' | 'connection' | 'error';
  order_id?: string;
  broker_order_id?: string;
  symbol?: string;
  side?: 'buy' | 'sell';
  qty?: number;
  status?: 'submitted' | 'filled' | 'cancelled' | 'rejected';
  filled_price?: number;
  filled_at?: string;
  timestamp?: string;
  message?: string;
}

interface UseOrdersStreamOptions {
  apiUrl: string;
  onMessage: (msg: OrderMessage) => void;
  enabled?: boolean;
}

export function useOrdersStream({
  apiUrl,
  onMessage,
  enabled = true,
}: UseOrdersStreamOptions) {
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

    const wsUrl = apiUrl.replace(/^http/, 'ws') + '/orders/ws';

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
          const msg: OrderMessage = JSON.parse(event.data);
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
