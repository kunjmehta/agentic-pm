'use client';

import { useEffect, useState } from 'react';
import type { PortfolioData } from '@/types/config';

export interface PortfolioState {
  data: PortfolioData | null;
  isConnected: boolean;
  error: string | null;
}

/** Map the raw portfolio_update payload from the backend to the frontend PortfolioData type. */
function mapPortfolioPayload(raw: Record<string, unknown>): PortfolioData {
  const parse = (v: unknown) => parseFloat(String(v)) || 0;

  const unrealizedPl = parse(raw.unrealized_pl);
  const realizedPl = parse(raw.realized_pl);

  const rawPositions = Array.isArray(raw.positions) ? raw.positions : [];
  const positions = rawPositions.map((p: Record<string, unknown>) => ({
    symbol: String(p.symbol ?? ''),
    qty: parse(p.qty),
    entry_price: parse(p.avg_entry_price),
    current_price: parse(p.current_price),
    market_value: parse(p.market_value),
    unrealized_pl: parse(p.unrealized_pl),
    // unrealized_plpc is a decimal fraction (0.05 = 5%) — convert to percent
    unrealized_pl_pct: parse(p.unrealized_plpc) * 100,
    side: (p.side === 'short' ? 'short' : 'long') as 'long' | 'short',
  }));

  return {
    timestamp: String(raw.timestamp ?? new Date().toISOString()),
    total_equity: parse(raw.equity),
    cash: parse(raw.cash),
    buying_power: parse(raw.buying_power),
    unrealized_pl: unrealizedPl,
    realized_pl: realizedPl,
    total_pl: unrealizedPl + realizedPl,
    positions,
    is_connected: true,
  };
}

export function usePortfolio(apiUrl: string, enabled = true) {
  const [state, setState] = useState<PortfolioState>({
    data: null,
    isConnected: false,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;

    let ws: WebSocket | null = null;
    let reconnectTimer: NodeJS.Timeout | null = null;
    let refreshTimer: NodeJS.Timeout | null = null;
    let shouldReconnect = true;
    let reconnectAttempts = 0;

    function sendRefresh() {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'refresh' }));
      }
    }

    function connect() {
      // Close any lingering connection before opening a new one
      if (ws) {
        ws.close();
        ws = null;
      }

      try {
        const wsUrl = apiUrl.replace(/^http/, 'ws') + '/portfolio/ws';
        // Use a local reference so onclose can guard against being superseded
        const socket = new WebSocket(wsUrl);
        ws = socket;

        socket.onopen = () => {
          setState((prev) => ({ ...prev, isConnected: true, error: null }));
          reconnectAttempts = 0;
          socket.send(JSON.stringify({ type: 'subscribe' }));
        };

        socket.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data) as Record<string, unknown>;

            if (msg.type === 'portfolio_update' && msg.data) {
              const portfolioData = mapPortfolioPayload(msg.data as Record<string, unknown>);
              setState((prev) => ({ ...prev, data: portfolioData, isConnected: true }));

            } else if (msg.type === 'subscribed') {
              // Server confirmed — fetch immediately, then poll every 10s
              sendRefresh();
              refreshTimer = setInterval(sendRefresh, 10_000);
            }
          } catch {
            // Malformed message — ignore
          }
        };

        socket.onerror = () => {
          // onclose fires immediately after and handles reconnect
        };

        socket.onclose = () => {
          // Guard: if this socket has already been superseded (connect() was called
          // again), ignore — the new socket owns the state and reconnect logic.
          if (ws !== socket) return;
          ws = null;
          setState((prev) => ({ ...prev, isConnected: false }));
          if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
          }

          if (shouldReconnect) {
            const backoff = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
            reconnectAttempts += 1;
            reconnectTimer = setTimeout(connect, backoff);
          }
        };
      } catch {
        setState((prev) => ({ ...prev, isConnected: false }));
        if (shouldReconnect) {
          const backoff = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
          reconnectAttempts += 1;
          reconnectTimer = setTimeout(connect, backoff);
        }
      }
    }

    connect();

    return () => {
      shouldReconnect = false;
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      if (ws) { ws.close(); ws = null; }
    };
  }, [apiUrl, enabled]);

  return state;
}
