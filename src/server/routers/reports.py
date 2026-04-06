"""Reports router — GET/POST /v1/reports/...

Provides three read endpoints for reporting and one trigger endpoint for the
daily evaluation job.

Endpoints:
    GET  /v1/reports/signal-performance           Per-signal was_taken + PnL
    GET  /v1/reports/hypothetical-vs-actual       Daily actual vs all-signals-taken
    GET  /v1/reports/strategy-breakdown           Aggregated strategy stats
    POST /v1/reports/run-daily                    Trigger daily evaluation job
"""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/reports", tags=["reports"])


def _dao():
    """Return a fresh ReportsDAO."""
    from src.common.dao.reports_dao import ReportsDAO
    return ReportsDAO()


# ── Read endpoints ─────────────────────────────────────────────────────────────


@router.get("/signal-performance")
async def signal_performance(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    symbol: Optional[str] = Query(None, description="Filter by ticker"),
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(default=200, ge=1, le=1000),
):
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
    try:
        dao = _dao()
        records = dao.get_signal_performance(
            strategy=strategy,
            symbol=symbol,
            start_date=start,
            end_date=end,
            limit=limit,
        )
        dao.close()
        return {
            "status": "success",
            "records": records,
            "count": len(records),
            "filters": {"strategy": strategy, "symbol": symbol, "start": start, "end": end},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[reports/signal-performance] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/hypothetical-vs-actual")
async def hypothetical_vs_actual(
    date_param: Optional[str] = Query(
        None,
        alias="date",
        description="Snapshot date (YYYY-MM-DD). Defaults to today.",
    ),
):
    """Compare actual portfolio vs hypothetical all-signals-taken scenario.

    Returns rows from ``hypothetical_portfolios`` for the given date.

    Args:
        date: Snapshot date (YYYY-MM-DD). Defaults to today.

    Returns:
        Dict with rows list and count.
    """
    target_date = date_param or str(date.today())
    try:
        dao = _dao()
        rows = dao.get_hypothetical_vs_actual(target_date)
        dao.close()
        return {
            "status": "success",
            "date": target_date,
            "rows": rows,
            "count": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[reports/hypothetical-vs-actual] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/strategy-breakdown")
async def strategy_breakdown(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    period: str = Query(
        default="all",
        description="Aggregation window: 'weekly', 'monthly', or 'all'",
    ),
):
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
    try:
        dao = _dao()
        rows = dao.get_strategy_breakdown(strategy=strategy, period=period)
        dao.close()
        return {
            "status": "success",
            "period": period,
            "strategy": strategy,
            "rows": rows,
            "count": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[reports/strategy-breakdown] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Daily evaluation job ──────────────────────────────────────────────────────


@router.post("/run-daily")
async def run_daily_reports():
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
    try:
        from src.common.dao.reports_dao import ReportsDAO
        from src.common.dao.orders_dao import OrdersDAO
        from src.common.dao.strategy_dao import StrategyDAO
        from src.common.dao import AlpacaDAO
        from datetime import timedelta

        reports_dao = ReportsDAO()
        orders_dao = OrdersDAO()
        s_dao = StrategyDAO()

        closed_count = 0
        hypothetical_count = 0

        # ── Step 1: Close open taken-signal rows that have a fill ──────────
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
                realized = fill - entry  # simplified per-share PnL; no qty available here
                reports_dao.close_tracking_row(
                    signal_id=int(r["signal_id"]),
                    exit_price=float(fill),
                    realized_pnl=float(realized),
                )
                closed_count += 1

        # ── Step 2: Compute hypothetical PnL for missed signals ────────────
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
            alpaca_dao = AlpacaDAO()
            now = datetime.now()
            for _, r in missed.iterrows():
                try:
                    sym = r["symbol"]
                    entry_price = r.get("entry_price") or 0.0
                    sig_ts = r["signal_timestamp"]
                    # Fetch the bar that covers the day after the signal
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
                except Exception as inner_exc:
                    logger.warning(f"[reports/run-daily] hypothetical calc failed for {r.get('symbol')}: {inner_exc}")
            alpaca_dao.close()

        reports_dao.close()
        orders_dao.close()
        s_dao.close()

        return {
            "status": "success",
            "closed_tracking_rows": closed_count,
            "hypotheticals_computed": hypothetical_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[reports/run-daily] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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
