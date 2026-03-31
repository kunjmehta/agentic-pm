"""Performance metric calculations for backtesting.

Pure mathematical functions for calculating industry-standard risk and return metrics.
Follows ai-hedge-fund reference architecture.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import date

try:
    from src.agentic.agents.backtester.core.bt_types import TradeRecord, PerformanceMetrics
except ModuleNotFoundError:
    from bt_types import TradeRecord, PerformanceMetrics


# =============================================================================
# Constants
# =============================================================================

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.0434  # 4.34% annual


# =============================================================================
# Return Metrics
# =============================================================================

def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
) -> float:
    """Calculate annualized Sharpe ratio from daily returns.

    Sharpe Ratio = (Annual Return - Risk Free Rate) / Annual Volatility

    Args:
        returns: Series of daily returns (as decimals, e.g., 0.01 for 1%)
        risk_free_rate: Annual risk-free rate (default: 4.34%)

    Returns:
        Annualized Sharpe ratio

    Examples:
        >>> returns = pd.Series([0.01, -0.005, 0.02, 0.015, -0.01])
        >>> sharpe = calculate_sharpe_ratio(returns)
    """
    if len(returns) == 0:
        return 0.0

    # Calculate annualized return and volatility
    mean_daily_return = returns.mean()
    std_daily_return = returns.std()

    if std_daily_return == 0:
        return 0.0

    # Annualize
    annual_return = mean_daily_return * TRADING_DAYS_PER_YEAR
    annual_volatility = std_daily_return * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe ratio
    excess_return = annual_return - risk_free_rate
    sharpe = excess_return / annual_volatility

    return float(sharpe)


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
) -> float:
    """Calculate Sortino ratio (downside risk-adjusted return).

    Sortino Ratio = (Annual Return - Risk Free Rate) / Downside Deviation
    Only considers negative returns in volatility calculation.

    Args:
        returns: Series of daily returns (as decimals)
        risk_free_rate: Annual risk-free rate

    Returns:
        Annualized Sortino ratio
    """
    if len(returns) == 0:
        return 0.0

    mean_daily_return = returns.mean()

    # Calculate downside deviation (only negative returns)
    negative_returns = returns[returns < 0]
    if len(negative_returns) == 0:
        return 0.0

    downside_std = negative_returns.std()
    if downside_std == 0:
        return 0.0

    # Annualize
    annual_return = mean_daily_return * TRADING_DAYS_PER_YEAR
    annual_downside_deviation = downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Sortino ratio
    excess_return = annual_return - risk_free_rate
    sortino = excess_return / annual_downside_deviation

    return float(sortino)


# =============================================================================
# Drawdown Metrics
# =============================================================================

def calculate_max_drawdown(equity_curve: pd.Series) -> Tuple[float, Optional[date], Optional[date]]:
    """Calculate maximum drawdown percentage and dates.

    Drawdown = (Trough - Peak) / Peak

    Args:
        equity_curve: Series of portfolio equity values over time

    Returns:
        Tuple of (max_drawdown_pct, peak_date, trough_date)

    Examples:
        >>> equity = pd.Series([100000, 105000, 103000, 108000, 102000])
        >>> drawdown, peak_date, trough_date = calculate_max_drawdown(equity)
    """
    if len(equity_curve) == 0:
        return 0.0, None, None

    # Calculate running maximum
    running_max = equity_curve.expanding().max()

    # Calculate drawdown at each point
    drawdown = (equity_curve - running_max) / running_max * 100

    # Find maximum drawdown
    max_dd = drawdown.min()

    # Find the dates
    trough_idx = drawdown.idxmin()
    if isinstance(equity_curve.index, pd.DatetimeIndex):
        trough_date = equity_curve.index[trough_idx].date() if trough_idx is not None else None
        # Peak is the last maximum before the trough
        peak_idx = running_max[:trough_idx].idxmax() if trough_idx is not None else None
        peak_date = equity_curve.index[peak_idx].date() if peak_idx is not None else None
    else:
        peak_date = None
        trough_date = None

    return float(max_dd), peak_date, trough_date


# =============================================================================
# Trade-Based Metrics
# =============================================================================

def calculate_win_rate(trades: List[TradeRecord]) -> float:
    """Calculate percentage of profitable trades.

    Args:
        trades: List of trade records

    Returns:
        Win rate as decimal (0-1)

    Examples:
        >>> trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}]
        >>> win_rate = calculate_win_rate(trades)
        >>> win_rate
        0.6666666666666666
    """
    if not trades:
        return 0.0

    closed_trades = [t for t in trades if t.get("pnl") is not None]
    if not closed_trades:
        return 0.0

    winning_trades = sum(1 for t in closed_trades if t.get("pnl", 0) > 0)
    win_rate = winning_trades / len(closed_trades)

    return float(win_rate)


def calculate_profit_factor(trades: List[TradeRecord]) -> float:
    """Calculate profit factor (gross profit / gross loss).

    Args:
        trades: List of trade records

    Returns:
        Profit factor (> 1.0 is profitable)

    Examples:
        >>> trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}]
        >>> pf = calculate_profit_factor(trades)
        >>> pf
        6.0
    """
    if not trades:
        return 0.0

    closed_trades = [t for t in trades if t.get("pnl") is not None]
    if not closed_trades:
        return 0.0

    gross_profit = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) < 0))

    if gross_loss == 0:
        # No losing trades — perfect result; return a large finite cap so the
        # value can be stored in DECIMAL columns without a ConversionException.
        return 99.0 if gross_profit > 0 else 0.0

    profit_factor = gross_profit / gross_loss

    return float(profit_factor)


def calculate_trade_statistics(trades: List[TradeRecord]) -> Dict[str, float]:
    """Calculate comprehensive trade statistics.

    Args:
        trades: List of trade records

    Returns:
        Dict with total_trades, winning_trades, losing_trades, avg_win, avg_loss, etc.
    """
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_trade": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0
        }

    closed_trades = [t for t in trades if t.get("pnl") is not None]

    if not closed_trades:
        return {
            "total_trades": len(trades),
            "winning_trades": 0,
            "losing_trades": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_trade": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0
        }

    wins = [t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) < 0]
    all_pnl = [t.get("pnl", 0) for t in closed_trades]

    return {
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "avg_trade": float(np.mean(all_pnl)) if all_pnl else 0.0,
        "largest_win": float(max(wins)) if wins else 0.0,
        "largest_loss": float(min(losses)) if losses else 0.0
    }


# =============================================================================
# Comprehensive Metrics
# =============================================================================

def calculate_all_metrics(
    trades: List[TradeRecord],
    daily_equity: pd.Series,
    initial_capital: float,
    final_capital: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
) -> PerformanceMetrics:
    """Calculate complete performance metrics suite.

    Args:
        trades: List of all trade records
        daily_equity: Series of daily equity values
        initial_capital: Starting capital
        final_capital: Ending capital
        risk_free_rate: Annual risk-free rate

    Returns:
        PerformanceMetrics with all calculated metrics
    """
    # Return metrics
    total_return_dollars = final_capital - initial_capital
    total_return_pct = (total_return_dollars / initial_capital * 100) if initial_capital > 0 else 0.0

    # Calculate daily returns
    if len(daily_equity) > 1:
        daily_returns = daily_equity.pct_change().dropna()
    else:
        daily_returns = pd.Series([0.0])

    # Risk metrics
    sharpe = calculate_sharpe_ratio(daily_returns, risk_free_rate)
    sortino = calculate_sortino_ratio(daily_returns, risk_free_rate)
    max_dd_pct, _, _ = calculate_max_drawdown(daily_equity)
    max_dd_dollars = (max_dd_pct / 100) * initial_capital if initial_capital > 0 else 0.0

    # Trade metrics
    win_rate = calculate_win_rate(trades)
    profit_factor = calculate_profit_factor(trades)
    trade_stats = calculate_trade_statistics(trades)

    return {
        "total_return_pct": float(total_return_pct),
        "total_return_dollars": float(total_return_dollars),
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sortino),
        "max_drawdown_pct": float(max_dd_pct),
        "max_drawdown_dollars": float(max_dd_dollars),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "total_trades": trade_stats["total_trades"],
        "winning_trades": trade_stats["winning_trades"],
        "losing_trades": trade_stats["losing_trades"],
        "avg_win": float(trade_stats["avg_win"]),
        "avg_loss": float(trade_stats["avg_loss"]),
        "avg_trade": float(trade_stats["avg_trade"]),
        "largest_win": float(trade_stats["largest_win"]),
        "largest_loss": float(trade_stats["largest_loss"])
    }


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test metrics functions."""
    print("=" * 60)
    print("Backtester Metrics Functions")
    print("=" * 60)

    # Test 1: Sharpe Ratio
    print("\n1. calculate_sharpe_ratio():")
    returns = pd.Series([0.01, -0.005, 0.02, 0.015, -0.01, 0.008, 0.012, -0.003])
    sharpe = calculate_sharpe_ratio(returns)
    print(f"   Daily Returns: {len(returns)} days")
    print(f"   Mean Return: {returns.mean():.4f}")
    print(f"   Std Dev: {returns.std():.4f}")
    print(f"   Sharpe Ratio: {sharpe:.2f}")

    # Test 2: Sortino Ratio
    print("\n2. calculate_sortino_ratio():")
    sortino = calculate_sortino_ratio(returns)
    print(f"   Sortino Ratio: {sortino:.2f}")

    # Test 3: Max Drawdown
    print("\n3. calculate_max_drawdown():")
    equity = pd.Series([100000, 105000, 103000, 108000, 102000, 106000, 99000, 104000])
    max_dd, peak_date, trough_date = calculate_max_drawdown(equity)
    print(f"   Equity Curve: {len(equity)} days")
    print(f"   Max Drawdown: {max_dd:.2f}%")
    print(f"   Peak: {peak_date}, Trough: {trough_date}")

    # Test 4: Win Rate
    print("\n4. calculate_win_rate():")
    trades: List[TradeRecord] = [
        {"pnl": 150.0, "symbol": "AAPL"},  # type: ignore
        {"pnl": -50.0, "symbol": "AAPL"},  # type: ignore
        {"pnl": 200.0, "symbol": "TSLA"},  # type: ignore
        {"pnl": -30.0, "symbol": "TSLA"},  # type: ignore
        {"pnl": 100.0, "symbol": "AAPL"},  # type: ignore
    ]
    win_rate = calculate_win_rate(trades)
    print(f"   Total Trades: {len(trades)}")
    print(f"   Win Rate: {win_rate*100:.1f}%")

    # Test 5: Profit Factor
    print("\n5. calculate_profit_factor():")
    profit_factor = calculate_profit_factor(trades)
    print(f"   Profit Factor: {profit_factor:.2f}")

    # Test 6: Trade Statistics
    print("\n6. calculate_trade_statistics():")
    trade_stats = calculate_trade_statistics(trades)
    print(f"   Total Trades: {trade_stats['total_trades']}")
    print(f"   Winning Trades: {trade_stats['winning_trades']}")
    print(f"   Losing Trades: {trade_stats['losing_trades']}")
    print(f"   Avg Win: ${trade_stats['avg_win']:.2f}")
    print(f"   Avg Loss: ${trade_stats['avg_loss']:.2f}")
    print(f"   Largest Win: ${trade_stats['largest_win']:.2f}")
    print(f"   Largest Loss: ${trade_stats['largest_loss']:.2f}")

    # Test 7: All Metrics
    print("\n7. calculate_all_metrics():")
    initial_capital = 100000.0
    final_capital = 104000.0
    metrics = calculate_all_metrics(
        trades=trades,
        daily_equity=equity,
        initial_capital=initial_capital,
        final_capital=final_capital
    )
    print(f"   Total Return: {metrics['total_return_pct']:.2f}%")
    print(f"   Return $: ${metrics['total_return_dollars']:,.2f}")
    print(f"   Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"   Sortino Ratio: {metrics['sortino_ratio']:.2f}")
    print(f"   Max Drawdown: {metrics['max_drawdown_pct']:.2f}%")
    print(f"   Win Rate: {metrics['win_rate']*100:.1f}%")
    print(f"   Profit Factor: {metrics['profit_factor']:.2f}")

    # Test 8: Edge Cases
    print("\n8. Edge Cases:")
    empty_trades: List[TradeRecord] = []
    empty_equity = pd.Series([100000])

    print("   Empty trades:")
    wr = calculate_win_rate(empty_trades)
    pf = calculate_profit_factor(empty_trades)
    print(f"     Win Rate: {wr}")
    print(f"     Profit Factor: {pf}")

    print("   Single equity point:")
    max_dd, _, _ = calculate_max_drawdown(empty_equity)
    print(f"     Max Drawdown: {max_dd:.2f}%")

    print("\n" + "=" * 60)
    print("All metrics functions validated successfully!")
    print("=" * 60)
