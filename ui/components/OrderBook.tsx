/**
 * OrderBook component - Real-time order execution feed
 *
 * Displays the last 50 orders with status indicators and virtual scrolling
 * for performance. Uses Bloomberg terminal styling with monospace font.
 */

'use client';

import { useState, useCallback, memo, useMemo } from 'react';
import { FixedSizeList as List } from 'react-window';
import { useOrdersStream, OrderMessage } from '../hooks/useOrdersStream';

interface Order {
  order_id: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  status: 'submitted' | 'filled' | 'cancelled' | 'rejected';
  filled_price?: number;
  timestamp: string;
}

const OrderRow = memo(({ index, style, data }: any) => {
  const order: Order = data[index];

  // Status icon: ● filled, ○ submitted, ✕ cancelled/rejected
  const statusIcon =
    order.status === 'filled' ? '●' :
    order.status === 'submitted' ? '○' :
    '✕';

  const statusColor =
    order.status === 'filled' ? 'text-green-400' :
    order.status === 'submitted' ? 'text-amber-400' :
    'text-red-400';

  const sideColor = order.side === 'buy' ? 'text-green-400' : 'text-red-400';

  const time = new Date(order.timestamp).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <div
      style={style}
      className="flex items-center gap-3 px-4 border-b border-gray-800 hover:bg-gray-900 text-xs font-mono"
    >
      <span className={`w-4 ${statusColor}`}>{statusIcon}</span>
      <span className="w-20 text-gray-400">{time}</span>
      <span className="w-16 text-white font-semibold">{order.symbol}</span>
      <span className={`w-12 ${sideColor} uppercase`}>{order.side}</span>
      <span className="w-16 text-right text-white">{order.qty}</span>
      <span className="w-20 text-right text-white">
        {order.filled_price ? `$${order.filled_price.toFixed(2)}` : '—'}
      </span>
      <span className={`flex-1 text-right ${statusColor} uppercase text-xs`}>
        {order.status}
      </span>
    </div>
  );
});

OrderRow.displayName = 'OrderRow';

interface Props {
  apiUrl: string;
}

export default function OrderBook({ apiUrl }: Props) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [sideFilter, setSideFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const handleMessage = useCallback((msg: OrderMessage) => {
    if (msg.type === 'order_update' && msg.order_id) {
      setOrders((prev) => {
        // Check if order already exists (update scenario)
        const existingIndex = prev.findIndex((o) => o.order_id === msg.order_id!);

        if (existingIndex !== -1) {
          // Update existing order
          const updated = [...prev];
          updated[existingIndex] = {
            ...updated[existingIndex],
            status: msg.status || updated[existingIndex].status,
            filled_price: msg.filled_price || updated[existingIndex].filled_price,
          };
          return updated;
        } else {
          // New order - prepend and keep last 50
          const newOrder: Order = {
            order_id: msg.order_id!,
            symbol: msg.symbol || '',
            side: msg.side || 'buy',
            qty: msg.qty || 0,
            status: msg.status || 'submitted',
            filled_price: msg.filled_price,
            timestamp: msg.timestamp || new Date().toISOString(),
          };
          return [newOrder, ...prev].slice(0, 50);
        }
      });
    }
  }, []);

  const { isConnected, error } = useOrdersStream({
    apiUrl,
    onMessage: handleMessage,
    enabled: true,
  });

  // Apply filters
  const filteredOrders = useMemo(() => {
    return orders.filter((order) => {
      // Symbol filter
      if (symbolFilter && !order.symbol.toLowerCase().includes(symbolFilter.toLowerCase())) {
        return false;
      }

      // Side filter
      if (sideFilter !== 'all' && order.side !== sideFilter) {
        return false;
      }

      // Status filter
      if (statusFilter !== 'all' && order.status !== statusFilter) {
        return false;
      }

      return true;
    });
  }, [orders, symbolFilter, sideFilter, statusFilter]);

  return (
    <div className="bg-black border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-gray-900 px-4 py-2 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-orange-500 font-semibold text-sm font-mono">
            ORDER BOOK
          </span>
          <span className="text-gray-500 text-xs">Last 50</span>
        </div>
        <div className="flex items-center gap-2">
          {isConnected ? (
            <span className="flex items-center gap-1 text-green-400 text-xs">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
              LIVE
            </span>
          ) : (
            <span className="flex items-center gap-1 text-red-400 text-xs">
              <span className="w-2 h-2 bg-red-400 rounded-full"></span>
              DISCONNECTED
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-gray-950 px-4 py-2 border-b border-gray-800 flex gap-3 flex-wrap items-center">
        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">SYMBOL:</label>
          <input
            type="text"
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value)}
            placeholder="Filter..."
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded w-24 focus:outline-none focus:border-orange-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">SIDE:</label>
          <select
            value={sideFilter}
            onChange={(e) => setSideFilter(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded focus:outline-none focus:border-orange-500"
          >
            <option value="all">ALL</option>
            <option value="buy">BUY</option>
            <option value="sell">SELL</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-gray-500 text-xs font-mono">STATUS:</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-white text-xs font-mono px-2 py-1 rounded focus:outline-none focus:border-orange-500"
          >
            <option value="all">ALL</option>
            <option value="submitted">SUBMITTED</option>
            <option value="filled">FILLED</option>
            <option value="cancelled">CANCELLED</option>
            <option value="rejected">REJECTED</option>
          </select>
        </div>

        <div className="ml-auto text-gray-500 text-xs font-mono">
          {filteredOrders.length} / {orders.length} orders
        </div>
      </div>

      {/* Column Headers */}
      <div className="flex gap-3 px-4 py-2 bg-gray-950 border-b border-gray-800 text-xs font-mono text-gray-500 uppercase">
        <span className="w-4"></span>
        <span className="w-20">Time</span>
        <span className="w-16">Symbol</span>
        <span className="w-12">Side</span>
        <span className="w-16 text-right">Qty</span>
        <span className="w-20 text-right">Price</span>
        <span className="flex-1 text-right">Status</span>
      </div>

      {/* Order List with Virtual Scrolling */}
      {filteredOrders.length > 0 ? (
        <List
          height={400}
          itemCount={filteredOrders.length}
          itemSize={32}
          width="100%"
          itemData={filteredOrders}
          className="scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-gray-900"
        >
          {OrderRow}
        </List>
      ) : (
        <div className="h-[400px] flex items-center justify-center text-gray-600 text-sm font-mono">
          {error ? (
            <span className="text-red-400">Error: {error}</span>
          ) : orders.length > 0 ? (
            <span>No orders match the current filters</span>
          ) : (
            <span>No orders yet. Waiting for activity...</span>
          )}
        </div>
      )}
    </div>
  );
}
