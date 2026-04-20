"""Portfolio, backtester, and order registry functions.

Covers:
  - Portfolio core: status, positions, health, data availability
  - Backtester workflow: EOD snapshot, snapshot worth, position swap
  - Order execution: execute, close, scale, strategy signal
  - Raw Alpaca orders: market, limit, stop, stop-limit, cancel, cancel-all, close-all
"""

import sys
from pathlib import Path
from typing import Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger
from src.server.models.strategies import (
    DataAvailabilityInput,
    DataAvailabilityOutput,
    HealthCheckOutput,
    PortfolioStatusOutput,
    PositionsSummaryOutput,
    SnapshotSaveOutput,
    SnapshotWorthOutput,
    SwapPositionsOutput,
)
from src.server.skills.portfolio.skills import (
    get_portfolio_status_core,
    get_positions_summary_core,
    check_portfolio_health_core,
    check_data_availability_core,
    execute_order_core,
    close_position_core,
    scale_position_core,
    execute_strategy_signal_core,
)
from src.server.skills.backtester.snapshot import (
    save_eod_snapshot_core as _save_eod_snapshot_raw,
    snapshot_worth_core as _snapshot_worth_raw,
)
from src.server.skills.backtester.swap_positions import (
    swap_positions_core as _swap_positions_raw,
)
from src.server.registry._fn_helpers import _out

logger = get_logger(__name__)


# ── Portfolio core ─────────────────────────────────────────────────────────────


def _check_data_availability_wrapped(
    symbol: str = "",
    ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    timeframe: str = "1Min",
    **kwargs,
) -> Dict:
    """Wrapper that accepts both 'symbol' and 'ticker' parameter names.

    The LLM sometimes emits 'ticker' (matching backtest_strategy) for this
    function which expects 'symbol'. This wrapper normalises either form.

    Args:
        symbol: Stock ticker (canonical param name).
        ticker: Alias accepted for LLM compatibility — mapped to symbol.
        start_date: Start date "YYYY-MM-DD".
        end_date: End date "YYYY-MM-DD".
        timeframe: Bar timeframe (default "1Min").

    Returns:
        Result dict from check_data_availability_core, or error dict.
    """
    if check_data_availability_core is None:
        return {"error": "check_data_availability skill not available"}
    resolved_symbol = symbol or ticker
    if not resolved_symbol:
        return {"error": "check_data_availability: 'symbol' is required"}
    if ticker and not symbol:
        logger.info(f"[registry] check_data_availability: mapped 'ticker' → 'symbol' ({ticker})")
    try:
        inp = DataAvailabilityInput(
            symbol=resolved_symbol, start_date=start_date, end_date=end_date, timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(f"[registry] DataAvailabilityInput validation failed: {exc}")
        return {"error": f"Invalid parameters for check_data_availability: {exc}"}
    try:
        result = check_data_availability_core(
            symbol=inp.symbol,
            start_date=inp.start_date,
            end_date=inp.end_date,
            timeframe=inp.timeframe,
        )
        return _out(DataAvailabilityOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] check_data_availability failed for {inp.symbol}: {exc}")
        return _out(DataAvailabilityOutput, {"error": str(exc)})


def _get_portfolio_status_wrapped(**kwargs) -> Dict:
    """Wrap get_portfolio_status_core with PortfolioStatusOutput validation."""
    try:
        result = get_portfolio_status_core()
        return _out(PortfolioStatusOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] get_portfolio_status failed: {exc}")
        return _out(PortfolioStatusOutput, {"error": str(exc)})


def _get_positions_summary_wrapped(**kwargs) -> Dict:
    """Wrap get_positions_summary_core with PositionsSummaryOutput validation."""
    try:
        result = get_positions_summary_core()
        return _out(PositionsSummaryOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] get_positions_summary failed: {exc}")
        return _out(PositionsSummaryOutput, {"error": str(exc)})


def _check_portfolio_health_wrapped(
    portfolio_status: Optional[Dict] = None,
    positions_data: Optional[Dict] = None,
    **kwargs,
) -> Dict:
    """Wrap check_portfolio_health_core with HealthCheckOutput validation.

    Auto-fetches portfolio_status and positions_data if not provided.
    """
    try:
        if portfolio_status is None:
            portfolio_status = get_portfolio_status_core()
        if positions_data is None:
            positions_data = get_positions_summary_core()
        result = check_portfolio_health_core(
            portfolio_status=portfolio_status,
            positions_data=positions_data,
        )
        return _out(HealthCheckOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] check_portfolio_health failed: {exc}")
        return _out(HealthCheckOutput, {"error": str(exc)})


# ── Backtester workflow ────────────────────────────────────────────────────────


def _save_eod_snapshot_wrapped(
    timestamp: Optional[str] = None,
    equity: float = 0.0,
    cash: float = 0.0,
    buying_power: float = 0.0,
    positions: Optional[list] = None,
    daily_pnl: Optional[float] = None,
    total_pnl: Optional[float] = None,
    daily_pnl_percent: Optional[float] = None,
    snapshot_source: str = "manual",
    **kwargs,
) -> Dict:
    """Wrap save_eod_snapshot_core with SnapshotSaveOutput validation."""
    try:
        from datetime import datetime as _dt
        result = _save_eod_snapshot_raw(
            timestamp=timestamp or _dt.now().isoformat(),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=positions or [],
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            daily_pnl_percent=daily_pnl_percent,
            snapshot_source=snapshot_source,
        )
        return _out(SnapshotSaveOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] save_eod_snapshot failed: {exc}")
        return _out(SnapshotSaveOutput, {"status": "error", "error": str(exc)})


def _snapshot_worth_wrapped(
    snapshot_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **kwargs,
) -> Dict:
    """Wrap snapshot_worth_core with SnapshotWorthOutput validation."""
    if not snapshot_date or not end_date:
        return _out(SnapshotWorthOutput, {
            "error": "snapshot_worth requires 'snapshot_date' and 'end_date'"
        })
    try:
        result = _snapshot_worth_raw(snapshot_date=snapshot_date, end_date=end_date)
        return _out(SnapshotWorthOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] snapshot_worth failed: {exc}")
        return _out(SnapshotWorthOutput, {"error": str(exc)})


def _swap_positions_wrapped(
    snapshot_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tickers: Optional[Dict] = None,
    **kwargs,
) -> Dict:
    """Wrap swap_positions_core with SwapPositionsOutput validation."""
    if not snapshot_date or not end_date:
        return _out(SwapPositionsOutput, {
            "error": "swap_positions requires 'snapshot_date' and 'end_date'"
        })
    if not tickers:
        return _out(SwapPositionsOutput, {"error": "swap_positions requires 'tickers' mapping"})
    try:
        result = _swap_positions_raw(
            snapshot_date=snapshot_date, end_date=end_date, tickers=tickers
        )
        return _out(SwapPositionsOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] swap_positions failed: {exc}")
        return _out(SwapPositionsOutput, {"error": str(exc)})


# ── Order execution ────────────────────────────────────────────────────────────


def _execute_order_wrapped(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    **kwargs,
) -> Dict:
    """Wrap execute_order_core — place a market or limit order.

    Args:
        symbol: Stock ticker.
        qty: Number of shares (> 0).
        side: "buy" or "sell".
        order_type: "market" (default) or "limit".
        limit_price: Required for limit orders.

    Returns:
        Order result dict with id, symbol, qty, side, type, status.
    """
    try:
        return execute_order_core(
            symbol=symbol, qty=qty, side=side,
            order_type=order_type, limit_price=limit_price,
        )
    except Exception as exc:
        logger.warning(f"[registry] execute_order failed ({side} {qty} {symbol}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _close_position_wrapped(symbol: str, **kwargs) -> Dict:
    """Wrap close_position_core — liquidate a position at market price.

    Args:
        symbol: Stock ticker whose position to close.

    Returns:
        Closing market-order result dict.
    """
    try:
        return close_position_core(symbol=symbol)
    except Exception as exc:
        logger.warning(f"[registry] close_position failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _scale_position_wrapped(
    symbol: str,
    target_pct: float,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    **kwargs,
) -> Dict:
    """Wrap scale_position_core — resize position to a target % of equity.

    Args:
        symbol: Stock ticker.
        target_pct: Target position size as fraction of equity (e.g. 0.05 = 5%).
            Use 0.0 to fully close the position.
        order_type: "market" (default) or "limit".
        limit_price: Required for limit orders.

    Returns:
        Scale result dict with action, current_qty, target_qty, delta_qty, order details.
    """
    try:
        return scale_position_core(
            symbol=symbol, target_pct=target_pct,
            order_type=order_type, limit_price=limit_price,
        )
    except Exception as exc:
        logger.warning(f"[registry] scale_position failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _execute_strategy_signal_wrapped(
    symbol: str,
    signal: str,
    confidence: float = 1.0,
    base_position_pct: float = 0.05,
    order_type: str = "market",
    **kwargs,
) -> Dict:
    """Wrap execute_strategy_signal_core — translate a signal into a trade.

    Args:
        symbol: Stock ticker.
        signal: "buy" | "sell" | "hold" (case-insensitive).
        confidence: Conviction score 0–1. Multiplies base_position_pct.
        base_position_pct: Max allocation per position (default 5%).
        order_type: "market" (default) or "limit".

    Returns:
        Dict with action, order (or None for hold), target_pct, confidence.
    """
    try:
        return execute_strategy_signal_core(
            symbol=symbol, signal=signal, confidence=confidence,
            base_position_pct=base_position_pct, order_type=order_type,
        )
    except Exception as exc:
        logger.warning(f"[registry] execute_strategy_signal failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol, "signal": signal}


# ── Raw Alpaca order operations ────────────────────────────────────────────────


def _fetch_orders_wrapped(status: str = "all", limit: int = 100, **kwargs) -> Dict:
    """Fetch orders from Alpaca with optional status / limit filters.

    Args:
        status: ``'open'`` | ``'closed'`` | ``'all'`` (default ``'all'``).
        limit: Maximum number of orders to return (default 100).

    Returns:
        List of order dicts inside ``{"orders": [...], "count": int}``.
    """
    try:
        from src.common.external.alpaca_portfolio import fetch_orders as _fetch
        orders = _fetch(status=status, limit=limit)
        return {"orders": orders, "count": len(orders)}
    except Exception as exc:
        logger.warning(f"[registry] fetch_orders failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _place_market_order_wrapped(symbol: str, qty: float, side: str, **kwargs) -> Dict:
    """Place a market order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to buy or sell (> 0).
        side: ``'buy'`` or ``'sell'``.

    Returns:
        Order result dict with id, symbol, qty, side, type, status.
    """
    try:
        from src.common.external.alpaca_portfolio import place_market_order as _place
        return _place(symbol=symbol, qty=qty, side=side)
    except Exception as exc:
        logger.warning(f"[registry] place_market_order failed ({side} {qty} {symbol}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _place_limit_order_wrapped(
    symbol: str, qty: float, side: str, limit_price: float,
    time_in_force: str = "day", **kwargs,
) -> Dict:
    """Place a limit order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to buy or sell (> 0).
        side: ``'buy'`` or ``'sell'``.
        limit_price: Price cap (buy) or floor (sell).
        time_in_force: ``'day'`` | ``'gtc'`` | ``'ioc'`` | ``'fok'`` (default ``'day'``).

    Returns:
        Order result dict with id, symbol, qty, type, limit_price, status.
    """
    try:
        from src.common.external.alpaca_portfolio import place_limit_order as _place
        return _place(symbol=symbol, qty=qty, side=side,
                      limit_price=limit_price, time_in_force=time_in_force)
    except Exception as exc:
        logger.warning(f"[registry] place_limit_order failed ({side} {qty} {symbol} @ {limit_price}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _place_stop_order_wrapped(
    symbol: str, qty: float, side: str, stop_price: float,
    time_in_force: str = "day", **kwargs,
) -> Dict:
    """Place a stop (stop-market) order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to trade. Must be > 0.
        side: "buy" or "sell".
        stop_price: Trigger price. Must be > 0.
        time_in_force: "day" | "gtc" | "ioc" | "fok". Default "day".

    Returns:
        ``{"id": str, "symbol": str, "qty": float, "side": str,
           "type": "stop", "stop_price": float, "status": str, ...}``.
    """
    try:
        from src.common.external.alpaca_portfolio import place_stop_order as _place
        return _place(symbol=symbol, qty=qty, side=side,
                      stop_price=stop_price, time_in_force=time_in_force)
    except Exception as exc:
        logger.warning(f"[registry] place_stop_order failed ({side} {qty} {symbol} stop@{stop_price}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _place_stop_limit_order_wrapped(
    symbol: str, qty: float, side: str, stop_price: float, limit_price: float,
    time_in_force: str = "day", **kwargs,
) -> Dict:
    """Place a stop-limit order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to trade. Must be > 0.
        side: "buy" or "sell".
        stop_price: Price that activates the limit order. Must be > 0.
        limit_price: Execution cap (buy) or floor (sell). Must be > 0.
        time_in_force: "day" | "gtc" | "ioc" | "fok". Default "day".

    Returns:
        ``{"id": str, "symbol": str, "qty": float, "side": str,
           "type": "stop_limit", "stop_price": float, "limit_price": float, "status": str, ...}``.
    """
    try:
        from src.common.external.alpaca_portfolio import place_stop_limit_order as _place
        return _place(symbol=symbol, qty=qty, side=side,
                      stop_price=stop_price, limit_price=limit_price,
                      time_in_force=time_in_force)
    except Exception as exc:
        logger.warning(
            f"[registry] place_stop_limit_order failed "
            f"({side} {qty} {symbol} stop@{stop_price} limit@{limit_price}): {exc}"
        )
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _cancel_order_wrapped(order_id: str, **kwargs) -> Dict:
    """Cancel an open order by its UUID.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        ``{"order_id": str, "status": "cancelled", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import cancel_order as _cancel
        return _cancel(order_id=order_id)
    except Exception as exc:
        logger.warning(f"[registry] cancel_order failed ({order_id}): {exc}")
        return {"status": "error", "error": str(exc), "order_id": order_id}


def _cancel_all_orders_wrapped(**kwargs) -> Dict:
    """Cancel all open orders.

    Returns:
        ``{"cancelled_count": int, "status": "all_cancelled", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import cancel_all_orders as _cancel_all
        return _cancel_all()
    except Exception as exc:
        logger.warning(f"[registry] cancel_all_orders failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _close_all_positions_wrapped(cancel_orders_first: bool = True, **kwargs) -> Dict:
    """Liquidate all open positions at market price.

    Args:
        cancel_orders_first: Cancel open orders before closing positions
            (default ``True`` to avoid partial-fill conflicts).

    Returns:
        ``{"closed_count": int, "status": "all_closed", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import close_all_positions as _close_all
        return _close_all(cancel_orders_first=cancel_orders_first)
    except Exception as exc:
        logger.warning(f"[registry] close_all_positions failed: {exc}")
        return {"status": "error", "error": str(exc)}
