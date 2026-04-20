"""Reports router — GET/POST /v1/reports/...

Provides three read endpoints for reporting and one trigger endpoint for the
daily evaluation job.

Endpoints:
    GET  /v1/reports/signal-performance           Per-signal was_taken + PnL
    GET  /v1/reports/hypothetical-vs-actual       Daily actual vs all-signals-taken
    GET  /v1/reports/strategy-breakdown           Aggregated strategy stats
    POST /v1/reports/run-daily                    Trigger daily evaluation job
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.common.dao.reports_dao import ReportsDAO
from src.common.utils import get_logger
from src.server.routers._helpers import dao_context, handle_http_errors, run_in_thread

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/reports", tags=["reports"])


# ── Read endpoints ─────────────────────────────────────────────────────────────


@router.get("/signal-performance")
@handle_http_errors
async def signal_performance(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    symbol: Optional[str] = Query(None, description="Filter by ticker"),
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Per-signal performance — was each signal taken and what was the outcome.

    Returns records from ``signal_performance_tracking`` with optional filters.

    Args:
        strategy: Filter by strategy name (e.g. "mean-reversion").
        symbol: Filter by ticker symbol.
        start: Start date for signal_timestamp filter (YYYY-MM-DD).
        end: End date for signal_timestamp filter (YYYY-MM-DD).
        limit: Max rows to return. Default 200.

    Returns:
        Dict with records list and count.
    """
    def _fetch() -> List[Dict[str, Any]]:
        with dao_context(ReportsDAO) as dao:
            return dao.get_signal_performance(
                strategy=strategy,
                symbol=symbol,
                start_date=start,
                end_date=end,
                limit=limit,
            )

    records = await run_in_thread(_fetch)
    return {
        "status": "success",
        "records": records,
        "count": len(records),
        "filters": {"strategy": strategy, "symbol": symbol, "start": start, "end": end},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/hypothetical-vs-actual")
@handle_http_errors
async def hypothetical_vs_actual(
    date_param: Optional[str] = Query(
        None,
        alias="date",
        description="Snapshot date (YYYY-MM-DD). Defaults to today.",
    ),
) -> Dict[str, Any]:
    """Compare actual portfolio vs hypothetical all-signals-taken scenario.

    Returns rows from ``hypothetical_portfolios`` for the given date.

    Args:
        date_param: Snapshot date (YYYY-MM-DD). Defaults to today.

    Returns:
        Dict with rows list and count.
    """
    target_date = date_param or str(date.today())

    def _fetch() -> List[Dict[str, Any]]:
        with dao_context(ReportsDAO) as dao:
            return dao.get_hypothetical_vs_actual(target_date)

    rows = await run_in_thread(_fetch)
    return {
        "status": "success",
        "date": target_date,
        "rows": rows,
        "count": len(rows),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/strategy-breakdown")
@handle_http_errors
async def strategy_breakdown(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    period: str = Query(
        default="all",
        description="Aggregation window: 'weekly', 'monthly', or 'all'",
    ),
) -> Dict[str, Any]:
    """Aggregated performance stats per strategy and symbol.

    Args:
        strategy: Filter by strategy name.
        period: "weekly" (last 7 days), "monthly" (last 30 days), or "all".

    Returns:
        Dict with rows list and count.
    """
    if period not in ("weekly", "monthly", "all"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be 'weekly', 'monthly', or 'all'.",
        )

    def _fetch() -> List[Dict[str, Any]]:
        with dao_context(ReportsDAO) as dao:
            return dao.get_strategy_breakdown(strategy=strategy, period=period)

    rows = await run_in_thread(_fetch)
    return {
        "status": "success",
        "period": period,
        "strategy": strategy,
        "rows": rows,
        "count": len(rows),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Daily evaluation job ──────────────────────────────────────────────────────


def _run_daily_evaluation() -> Dict[str, Any]:
    """Execute the daily report evaluation job (sync, runs in thread pool).

    Performs two tasks:
    1. Closes open signal_performance_tracking rows for taken signals
       whose positions have been closed.
    2. Computes hypothetical P&L for missed signals.

    Returns:
        Dict summarising rows closed and hypotheticals computed.
    """
    from src.common.dao.orders_dao import OrdersDAO
    from src.common.dao.strategy_dao import StrategyDAO
    from src.common.dao import AlpacaDAO

    closed_count = 0
    hypothetical_count = 0
    now = datetime.now()

    with dao_context(ReportsDAO) as reports_dao, \
         dao_context(OrdersDAO) as orders_dao, \
         dao_context(StrategyDAO) as s_dao:

        # Step 1: Close open taken-signal rows that have a fill
        open_taken = reports_dao.fetch_df(
            "SELECT spt.id, spt.signal_id, spt.symbol, spt.entry_price, lo.filled_price "
            "FROM signal_performance_tracking spt "
            "JOIN live_orders lo ON lo.signal_id = spt.signal_id "
            "WHERE spt.was_taken = TRUE "
            "  AND spt.tracking_status = 'open' "
            "  AND lo.status = 'filled' "
            "  AND lo.filled_price IS NOT NULL",
            (),
        )
        if not open_taken.empty:
            for _, r in open_taken.iterrows():
                entry = r.get("entry_price") or 0.0
                fill = r.get("filled_price") or 0.0
                realized = fill - entry  # simplified per-share PnL
                reports_dao.close_tracking_row(
                    signal_id=int(r["signal_id"]),
                    exit_price=float(fill),
                    realized_pnl=float(realized),
                )
                closed_count += 1

        # Step 2: Compute hypothetical PnL for missed signals
        missed = reports_dao.fetch_df(
            "SELECT spt.id, spt.signal_id, spt.symbol, spt.signal_action, "
            "       spt.signal_timestamp, sr.entry_price "
            "FROM signal_performance_tracking spt "
            "JOIN strategy_results sr ON sr.id = spt.signal_id "
            "WHERE spt.was_taken = FALSE "
            "  AND spt.tracking_status = 'missed'",
            (),
        )
        if not missed.empty:
            with dao_context(AlpacaDAO) as alpaca_dao:
                for _, r in missed.iterrows():
                    try:
                        sym = r["symbol"]
                        entry_price = r.get("entry_price") or 0.0
                        sig_ts = r["signal_timestamp"]
                        start = sig_ts if hasattr(sig_ts, "date") else datetime.fromisoformat(str(sig_ts))
                        end = start + timedelta(days=7)
                        bars = alpaca_dao.get_bars(sym, start=start, end=min(end, now), timeframe="1Day")
                        if bars.empty or entry_price <= 0:
                            continue
                        later_price = float(bars["close"].iloc[-1])
                        hypo_pnl = later_price - float(entry_price)
                        if r["signal_action"] == "sell":
                            hypo_pnl = -hypo_pnl
                        reports_dao.set_hypothetical_pnl(
                            signal_id=int(r["signal_id"]),
                            hypothetical_pnl=hypo_pnl,
                        )
                        hypothetical_count += 1
                    except Exception as exc:
                        logger.warning(
                            f"[reports/run-daily] hypothetical calc failed for {r.get('symbol')}: {exc}"
                        )

    return {
        "closed_tracking_rows": closed_count,
        "hypotheticals_computed": hypothetical_count,
    }


@router.post("/run-daily")
@handle_http_errors
async def run_daily_reports() -> Dict[str, Any]:
    """Trigger the daily report evaluation job.

    Performs two tasks:
    1. Closes open ``signal_performance_tracking`` rows for taken signals
       whose positions have been closed (reads ``live_orders`` for filled
       orders and computes realized P&L).
    2. Computes hypothetical P&L for missed signals (was_taken=False) by
       looking up where the price moved to since the signal was generated.

    Designed to be called at or after market close (16:30 ET).

    Returns:
        Dict summarising rows closed and hypotheticals computed.
    """
    result = await run_in_thread(_run_daily_evaluation)
    return {
        "status": "success",
        **result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    """Smoke test: verify router routes are defined correctly."""
    print("=" * 60)
    print("routers/reports.py smoke test")
    print("=" * 60)

    routes = [r.path for r in router.routes]
    expected = [
        "/v1/reports/signal-performance",
        "/v1/reports/hypothetical-vs-actual",
        "/v1/reports/strategy-breakdown",
        "/v1/reports/run-daily",
    ]
    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK]  {path}")

    print("\n[ALL OK] routers/reports.py smoke test passed")
    print("=" * 60)
