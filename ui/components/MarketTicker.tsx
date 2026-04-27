/**
 * MarketTicker component - Horizontal scrolling live price ticker
 *
 * Displays real-time prices for all watchlist symbols with color-coded
 * price changes. Auto-scrolls horizontally like a Bloomberg terminal ticker.
 */

'use client';

import { useState, useCallback } from 'react';
import { useMarketStream, MarketMessage } from '../hooks/useMarketStream';

interface TickerData {
  symbol: string;
  price: number;
  prev_close: number | null;
  pct_change: number | null;
  timestamp: string;
}

interface Props {
  apiUrl: string;
}

export default function MarketTicker({ apiUrl }: Props) {
  const [tickers, setTickers] = useState<Map<string, TickerData>>(new Map());

  const handleMessage = useCallback((msg: MarketMessage) => {
    if (msg.type === 'bar_update' && msg.symbol && msg.close !== undefined) {
      setTickers((prev) => {
        const newMap = new Map(prev);

        newMap.set(msg.symbol!, {
          symbol: msg.symbol!,
          price: msg.close!,
          prev_close: msg.prev_close ?? null,
          pct_change: msg.pct_change ?? null,
          timestamp: msg.timestamp || new Date().toISOString(),
        });

        return newMap;
      });
    }
  }, []);

  const { isConnected } = useMarketStream({
    apiUrl,
    onMessage: handleMessage,
    enabled: true,
  });

  const tickerArray = Array.from(tickers.values());

  // Duplicate array for seamless scrolling
  const scrollingTickers = [...tickerArray, ...tickerArray];

  return (
    <div className="bg-black border-b border-gray-800 overflow-hidden relative">
      <div className="flex items-center gap-2 px-4 py-2">
        {/* Connection status */}
        <div className="flex items-center gap-2 shrink-0">
          {isConnected ? (
            <span className="flex items-center gap-1 text-green-400 text-xs font-mono">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
              MARKET
            </span>
          ) : (
            <span className="flex items-center gap-1 text-red-400 text-xs font-mono">
              <span className="w-2 h-2 bg-red-400 rounded-full"></span>
              OFFLINE
            </span>
          )}
        </div>

        {/* Scrolling ticker */}
        <div className="flex-1 overflow-hidden relative">
          {scrollingTickers.length > 0 ? (
            <div className="flex gap-8 animate-scroll-left">
              {scrollingTickers.map((ticker, index) => {
                const pctChange = ticker.pct_change ?? 0;
                const changeColor =
                  pctChange > 0
                    ? 'text-green-400'
                    : pctChange < 0
                    ? 'text-red-400'
                    : 'text-gray-400';

                const arrow = pctChange > 0 ? '▲' : pctChange < 0 ? '▼' : '';

                return (
                  <div
                    key={`${ticker.symbol}-${index}`}
                    className="flex items-center gap-2 whitespace-nowrap font-mono text-sm"
                  >
                    <span className="text-white font-semibold">{ticker.symbol}</span>
                    <span className="text-orange-500">${ticker.price.toFixed(2)}</span>
                    {ticker.pct_change !== null && (
                      <span className={`${changeColor} text-xs`}>
                        {arrow} {Math.abs(pctChange).toFixed(2)}%
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-gray-600 text-sm font-mono">
              Waiting for market data...
            </div>
          )}
        </div>
      </div>

      {/* Add scrolling animation styles */}
      <style jsx>{`
        @keyframes scroll-left {
          from {
            transform: translateX(0);
          }
          to {
            transform: translateX(-50%);
          }
        }

        .animate-scroll-left {
          animation: scroll-left 60s linear infinite;
        }

        .animate-scroll-left:hover {
          animation-play-state: paused;
        }
      `}</style>
    </div>
  );
}
