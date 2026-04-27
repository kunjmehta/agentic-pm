export interface Position {
  symbol: string;
  qty: number;
  entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  side: 'long' | 'short';
}

export interface PortfolioData {
  timestamp: string;
  total_equity: number;
  cash: number;
  buying_power: number;
  total_pl: number;
  unrealized_pl: number;
  realized_pl: number;
  positions: Position[];
  is_connected: boolean;
}
