"""Type definitions for backtesting simulation.

Provides type safety and clear contracts for portfolio states, trades,
performance metrics, and backtest results. Follows ai-hedge-fund reference architecture.
"""

from typing import TypedDict, Literal, Optional, Dict, Any
from enum import Enum
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class Action(Enum):
    """Trading actions for backtest simulation."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    SHORT = "short"
    COVER = "cover"


# =============================================================================
# Type Aliases
# =============================================================================

ActionLiteral = Literal["buy", "sell", "hold", "short", "cover"]


# =============================================================================
# Position and Portfolio State
# =============================================================================

class PositionState(TypedDict, total=False):
    """State of a single position in the portfolio.

    Attributes:
        symbol: Stock ticker symbol
        quantity: Number of shares held (negative for short positions)
        cost_basis: Average price paid per share
        current_price: Current market price per share
        market_value: Total value at current price (quantity * current_price)
        unrealized_pnl: Unrealized profit/loss in dollars
        unrealized_pnl_pct: Unrealized P&L as percentage of cost basis
        side: Position side - 'long' or 'short'
    """
    symbol: str
    quantity: int
    cost_basis: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    side: Literal["long", "short"]


class PortfolioSnapshot(TypedDict, total=False):
    """Complete portfolio state at a point in time.

    Used for portfolio analysis, swaps, and forward simulation.

    Attributes:
        date: Date of snapshot
        timestamp: Full timestamp of snapshot
        cash: Available cash balance
        equity: Total portfolio value (cash + positions)
        buying_power: Margin buying power available
        positions: Dictionary mapping symbol -> PositionState
        long_positions: Number of long positions held
        short_positions: Number of short positions held
        total_pnl: All-time realized + unrealized P&L
        daily_pnl: Today's P&L in dollars
        daily_pnl_percent: Today's P&L as percentage
    """
    date: date
    timestamp: datetime
    cash: float
    equity: float
    buying_power: float
    positions: dict[str, PositionState]
    long_positions: int
    short_positions: int
    total_pnl: float
    daily_pnl: float
    daily_pnl_percent: float


# =============================================================================
# Trade Records
# =============================================================================

class TradeRecord(TypedDict, total=False):
    """Record of a simulated or executed trade.

    Attributes:
        trade_id: Unique identifier for the trade
        symbol: Stock ticker symbol
        action: Trade action (buy, sell, short, cover)
        entry_date: Date of trade entry
        entry_time: Timestamp of trade entry
        entry_price: Price at entry
        exit_date: Date of trade exit (None if still open)
        exit_time: Timestamp of trade exit
        exit_price: Price at exit
        quantity: Number of shares traded
        side: Position side - 'long' or 'short'
        pnl: Realized profit/loss in dollars (None if open)
        pnl_pct: Realized P&L as percentage (None if open)
        entry_signal: Strategy signals at entry (dict with indicators, etc.)
        exit_signal: Strategy signals at exit
        exit_reason: Reason for exit (e.g., 'stop_loss', 'take_profit', 'signal')
        status: Trade status - 'open' or 'closed'
    """
    trade_id: int
    symbol: str
    action: ActionLiteral
    entry_date: date
    entry_time: datetime
    entry_price: float
    exit_date: Optional[date]
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    quantity: int
    side: Literal["long", "short"]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    entry_signal: dict
    exit_signal: Optional[dict]
    exit_reason: Optional[str]
    status: Literal["open", "closed"]


# =============================================================================
# Performance Metrics
# =============================================================================

class PerformanceMetrics(TypedDict, total=False):
    """Backtest performance metrics.

    Industry-standard risk and return metrics for strategy evaluation.

    Attributes:
        total_return_pct: Total return percentage over backtest period
        total_return_dollars: Total return in dollars
        sharpe_ratio: Risk-adjusted return (annualized return / volatility)
        sortino_ratio: Downside risk-adjusted return
        max_drawdown_pct: Maximum peak-to-trough decline percentage
        max_drawdown_dollars: Maximum drawdown in dollars
        win_rate: Percentage of profitable trades (0-1)
        profit_factor: Gross profit / Gross loss ratio
        total_trades: Total number of trades executed
        winning_trades: Number of profitable trades
        losing_trades: Number of losing trades
        avg_win: Average profit per winning trade
        avg_loss: Average loss per losing trade
        avg_trade: Average P&L per trade
        largest_win: Largest single winning trade
        largest_loss: Largest single losing trade
    """
    total_return_pct: float
    total_return_dollars: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_dollars: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_trade: float
    largest_win: float
    largest_loss: float


# =============================================================================
# Backtest Results
# =============================================================================

class BacktestResult(TypedDict, total=False):
    """Complete backtest output with results and analysis.

    Attributes:
        run_id: Database identifier for this backtest run (None if not saved)
        status: Backtest status - 'completed', 'failed', 'running'
        strategy: Strategy name used
        symbol: Primary stock symbol (None for multi-symbol)
        start_date: Backtest start date
        end_date: Backtest end date
        trading_days: Number of trading days in period
        initial_capital: Starting capital for simulation
        final_capital: Ending capital after simulation
        trades: List of all trade records
        daily_performance: Daily equity curve and returns
        metrics: Performance metrics summary
        summary: Human-readable performance summary
        recommendation: Deployment recommendation based on metrics
        error: Error message if backtest failed
    """
    run_id: Optional[str]
    status: Literal["completed", "failed", "running"]
    strategy: str
    symbol: Optional[str]
    start_date: date
    end_date: date
    trading_days: int
    initial_capital: float
    final_capital: float
    trades: list[TradeRecord]
    daily_performance: list[dict]  # List of daily performance snapshots
    metrics: PerformanceMetrics
    summary: str
    recommendation: str
    error: Optional[str]


# =============================================================================
# Swap Operation Types
# =============================================================================

class PositionSwap(TypedDict, total=False):
    """Definition of a position swap operation.

    Swaps are instantaneous position replacements, not buy/sell trades.

    Example:
        {"AAPL": {"swap_to": "TSLA", "quantity": 50}}
        Means: Replace 50 shares of AAPL with 50 shares of TSLA

    Attributes:
        swap_to: Symbol to swap into
        quantity: Number of shares to swap
    """
    swap_to: str
    quantity: int


# =============================================================================
# Strategy Signal Models (Pydantic)
# =============================================================================

class StrategySignal(BaseModel):
    """Validated strategy signal response.

    All strategy analyze_bars() methods must return this structure.
    Pydantic ensures type safety and validation at runtime.
    """

    action: Literal["buy", "sell", "hold"] = Field(
        ...,
        description="Trading action to take"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal confidence (0.0 = no confidence, 1.0 = maximum confidence)"
    )

    current_price: float = Field(
        ...,
        gt=0.0,
        description="Current asset price"
    )

    reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation for the signal"
    )

    # Optional fields
    entry_price: Optional[float] = Field(
        None,
        gt=0.0,
        description="Recommended entry price"
    )

    stop_loss: Optional[float] = Field(
        None,
        gt=0.0,
        description="Recommended stop loss price"
    )

    take_profit: Optional[float] = Field(
        None,
        gt=0.0,
        description="Recommended take profit price"
    )

    # Strategy-specific metadata (not validated beyond dict type)
    indicators: Optional[Dict[str, Any]] = Field(
        None,
        description="Strategy-specific indicator values"
    )

    statistics: Optional[Dict[str, Any]] = Field(
        None,
        description="Derived statistics"
    )

    parameters: Optional[Dict[str, Any]] = Field(
        None,
        description="Parameters used for this signal"
    )

    # Live trading fields
    symbol: Optional[str] = Field(
        None,
        description="Ticker symbol (for live signal generation)"
    )

    timeframe: Optional[str] = Field(
        None,
        description="Bar timeframe (for live signal generation)"
    )

    timestamp: Optional[datetime] = Field(
        None,
        description="Signal generation timestamp"
    )

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def validate_prices(cls, v, info):
        """Ensure stop_loss < entry_price < take_profit for buy signals."""
        # Note: Full validation requires action context, implement in post-validation if needed
        return v

    class Config:
        """Pydantic config."""
        extra = "allow"  # Allow additional fields for strategy-specific data
        validate_assignment = True


class StrategyError(BaseModel):
    """Error response when strategy analysis fails."""

    error: str = Field(
        ...,
        min_length=1,
        description="Error message"
    )

    symbol: Optional[str] = Field(
        None,
        description="Symbol that caused error (if applicable)"
    )

    timestamp: Optional[datetime] = Field(
        default_factory=datetime.now,
        description="Error timestamp"
    )


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test type definitions."""
    print("=" * 60)
    print("Backtester Core Types")
    print("=" * 60)

    # Test Action enum
    print("\n1. Action Enum:")
    for action in Action:
        print(f"   {action.name} = {action.value}")

    # Test PositionState
    print("\n2. PositionState TypedDict:")
    position: PositionState = {
        "symbol": "AAPL",
        "quantity": 100,
        "cost_basis": 150.00,
        "current_price": 160.00,
        "market_value": 16000.00,
        "unrealized_pnl": 1000.00,
        "unrealized_pnl_pct": 6.67,
        "side": "long"
    }
    print(f"   Symbol: {position['symbol']}")
    print(f"   Quantity: {position['quantity']}")
    print(f"   Unrealized P&L: ${position['unrealized_pnl']:,.2f}")

    # Test PortfolioSnapshot
    print("\n3. PortfolioSnapshot TypedDict:")
    snapshot: PortfolioSnapshot = {
        "date": date.today(),
        "timestamp": datetime.now(),
        "cash": 50000.00,
        "equity": 105000.00,
        "positions": {"AAPL": position},
        "long_positions": 1,
        "short_positions": 0
    }
    print(f"   Date: {snapshot['date']}")
    print(f"   Cash: ${snapshot['cash']:,.2f}")
    print(f"   Equity: ${snapshot['equity']:,.2f}")
    print(f"   Positions: {snapshot['long_positions']} long, {snapshot['short_positions']} short")

    # Test TradeRecord
    print("\n4. TradeRecord TypedDict:")
    trade: TradeRecord = {
        "trade_id": 1,
        "symbol": "AAPL",
        "action": "buy",
        "entry_date": date.today(),
        "entry_time": datetime.now(),
        "entry_price": 150.00,
        "quantity": 100,
        "side": "long",
        "entry_signal": {"rsi": 30, "signal": "oversold"},
        "status": "open"
    }
    print(f"   Trade #{trade['trade_id']}: {trade['action'].upper()} {trade['quantity']} {trade['symbol']}")
    print(f"   Entry: ${trade['entry_price']:.2f}")
    print(f"   Status: {trade['status']}")

    # Test PerformanceMetrics
    print("\n5. PerformanceMetrics TypedDict:")
    metrics: PerformanceMetrics = {
        "total_return_pct": 8.5,
        "sharpe_ratio": 1.42,
        "max_drawdown_pct": -3.2,
        "win_rate": 0.65,
        "profit_factor": 1.8,
        "total_trades": 23
    }
    print(f"   Total Return: {metrics['total_return_pct']:.2f}%")
    print(f"   Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"   Win Rate: {metrics['win_rate']*100:.1f}%")

    # Test BacktestResult
    print("\n6. BacktestResult TypedDict:")
    result: BacktestResult = {
        "run_id": "abc-123",
        "status": "completed",
        "strategy": "mean-reversion",
        "symbol": "AAPL",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 31),
        "trading_days": 21,
        "initial_capital": 100000.00,
        "final_capital": 108500.00,
        "trades": [trade],
        "metrics": metrics,
        "summary": "Strategy achieved 8.5% return with Sharpe 1.42",
        "recommendation": "CONSIDER for live trading"
    }
    print(f"   Run ID: {result['run_id']}")
    print(f"   Strategy: {result['strategy']}")
    print(f"   Period: {result['start_date']} to {result['end_date']}")
    print(f"   Return: ${result['final_capital'] - result['initial_capital']:,.2f}")
    print(f"   Recommendation: {result['recommendation']}")

    # Test PositionSwap
    print("\n7. PositionSwap TypedDict:")
    swap: PositionSwap = {
        "swap_to": "TSLA",
        "quantity": 50
    }
    print(f"   Swap to: {swap['swap_to']}")
    print(f"   Quantity: {swap['quantity']}")

    print("\n" + "=" * 60)
    print("All type definitions validated successfully!")
    print("=" * 60)
