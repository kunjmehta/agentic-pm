'use client';

import { usePortfolio } from '@/hooks/usePortfolio';

interface Props {
  apiUrl: string;
  enabled?: boolean;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number) {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

export default function LivePortfolio({ apiUrl, enabled = true }: Props) {
  const { data, isConnected, error } = usePortfolio(apiUrl, enabled);

  if (!enabled) {
    return null;
  }

  if (error) {
    return (
      <div className="live-portfolio error">
        <div className="portfolio-header">
          <span className="portfolio-title">Portfolio</span>
          <span className="portfolio-status error">● {error}</span>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="live-portfolio">
        <div className="portfolio-header">
          <span className="portfolio-title">Portfolio</span>
          <span className="portfolio-status connecting">○ Connecting...</span>
        </div>
      </div>
    );
  }

  const totalPL = data.total_pl ?? 0;
  const unrealizedPL = data.unrealized_pl ?? 0;
  const realizedPL = data.realized_pl ?? 0;
  const cash = data.cash ?? 0;

  return (
    <div className="live-portfolio">
      <div className="portfolio-header">
        <span className="portfolio-title">Portfolio</span>
        {isConnected ? (
          <span className="portfolio-status connected">● Live</span>
        ) : (
          <span className="portfolio-status disconnected">○ Disconnected</span>
        )}
      </div>

      <div className="portfolio-summary">
        <div className="summary-card">
          <div className="summary-label">Total P&L</div>
          <div className={`summary-value ${totalPL >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(totalPL)}
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-label">Unrealized P&L</div>
          <div className={`summary-value ${unrealizedPL >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(unrealizedPL)}
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-label">Realized P&L</div>
          <div className={`summary-value ${realizedPL >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(realizedPL)}
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-label">Cash</div>
          <div className="summary-value">{formatCurrency(cash)}</div>
        </div>
      </div>

      {data.positions && data.positions.length > 0 && (
        <div className="positions-section">
          <div className="positions-header">Positions</div>
          <div className="positions-table-wrapper">
            <table className="positions-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Current</th>
                  <th>Value</th>
                  <th>P&L %</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((pos) => {
                  const plPct = pos.unrealized_pl_pct ?? 0;
                  const isPositive = plPct >= 0;

                  return (
                    <tr key={pos.symbol}>
                      <td className="symbol-col">{pos.symbol}</td>
                      <td className="qty-col">{pos.qty}</td>
                      <td>{formatCurrency(pos.entry_price)}</td>
                      <td>{formatCurrency(pos.current_price)}</td>
                      <td>{formatCurrency(pos.market_value)}</td>
                      <td className={isPositive ? 'pl-positive' : 'pl-negative'}>
                        {formatPercent(plPct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(!data.positions || data.positions.length === 0) && (
        <div className="positions-empty">No open positions</div>
      )}
    </div>
  );
}
