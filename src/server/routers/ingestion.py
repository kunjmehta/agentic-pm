"""Ingestion router — GET /v1/ingestion/status, POST trigger-etl, POST flush-cache."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

import src.server.app_state as _state
from src.common.utils import get_logger, config as app_config
from src.server.models.endpoints import (
    FlushCacheResponse,
    IngestionStatusResponse,
    TriggerETLResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])


@router.get("/status", response_model=IngestionStatusResponse)
async def ingestion_status():
    """Real-time status of the data ingestion pipeline.

    Reports on:
    - DataCoordinator streaming task (running/stopped, symbols)
    - Trade cache (size, utilisation)
    - ETL configuration

    Returns:
        Dict with data_stream, cache, and etl sub-sections.
    """
    # ── Data stream ───────────────────────────────────────────────────────
    stream_running = _state._stream_task is not None and not _state._stream_task.done()
    symbols = _state._data_coordinator.symbols if _state._data_coordinator is not None else []
    data_stream_info: Dict[str, Any] = {
        "enabled": app_config.get("data_stream.enabled", default=False),
        "running": stream_running,
        "symbols": symbols,
        "task_name": _state._stream_task.get_name() if _state._stream_task is not None else None,
    }

    # ── Trade cache ───────────────────────────────────────────────────────
    try:
        from src.common.data_gatherer.trade_cache import get_cache
        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, "_cache") else 0
        cache_max = app_config.get("cache.max_size", default=100_000)
        cache_info: Dict[str, Any] = {
            "current_size": cache_size,
            "max_size": cache_max,
            "utilization_pct": round(cache_size / cache_max * 100, 2) if cache_max else 0,
            "batch_interval_minutes": app_config.get("cache.batch_interval_minutes", default=5),
        }
    except Exception as exc:
        cache_info = {"error": str(exc)}

    # ── ETL ───────────────────────────────────────────────────────────────
    etl_info: Dict[str, Any] = {
        "enabled": app_config.get("etl.enabled", default=True),
        "mode": "auto-run with bar ingestion",
        "timeframes": app_config.get("etl.timeframes", default=["1Min", "1Hour", "1Day"]),
        "lookback_days": app_config.get("etl.lookback_days", default=60),
    }

    return {
        "data_stream": data_stream_info,
        "cache": cache_info,
        "etl": etl_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/trigger-etl", response_model=TriggerETLResponse)
async def trigger_etl():
    """Manually trigger ETL pipeline to compute indicators for all watchlist symbols.

    Runs indicator computation across all configured timeframes.
    This may take several minutes depending on data volume.

    Returns:
        Dict with status, total_rows computed, and symbols processed.
    """
    try:
        from src.common.etl.pipeline import IndicatorsETL
        logger.info("[ingestion/trigger-etl] manual ETL triggered")
        etl = IndicatorsETL()
        result = etl.run_for_watchlist()
        etl.close()
        logger.info(f"[ingestion/trigger-etl] complete: {result.get('total_rows')} rows")
        return {
            "status": "success",
            "message": f"ETL completed for {len(result.get('symbols', []))} symbol(s)",
            "total_rows": result.get("total_rows"),
            "symbols": result.get("symbols"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[ingestion/trigger-etl] {exc}", exc_info=True)
        return {
            "status": "error",
            "message": "ETL execution failed",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/flush-cache", response_model=FlushCacheResponse)
async def flush_cache(
    archive_older_than_minutes: int = Query(
        default=60,
        ge=1,
        description="Archive live_trades rows older than this many minutes into historical_trades",
    ),
):
    """Flush the trade cache to live_trades, then archive aged rows to historical_trades.

    Two-phase operation:
    1. Force-flush TradeCache → live_trades (staging).
    2. Archive live_trades rows older than ``archive_older_than_minutes`` into
       historical_trades with source='stream', then delete from live_trades.

    Args:
        archive_older_than_minutes: Rows ingested before this threshold are moved
            to historical_trades. Default 60 minutes.

    Returns:
        Dict with trades_flushed (step 1) and trades_archived (step 2).
    """
    from src.common.data_gatherer.trade_cache import get_cache
    from src.common.data_gatherer.db_stream_handlers import flush_cache_to_db
    from src.common.dao.alpaca_dao import AlpacaDAO

    result: dict = {
        "status": "success",
        "trades_flushed": 0,
        "trades_archived": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 1: flush in-memory cache → live_trades ────────────────────────
    try:
        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, "_cache") else 0
        if cache_size > 0:
            logger.info(f"[ingestion/flush-cache] flushing {cache_size} trade(s) to live_trades")
            await flush_cache_to_db()
            result["trades_flushed"] = cache_size
        else:
            logger.info("[ingestion/flush-cache] cache empty, skipping flush step")
    except Exception as exc:
        logger.error(f"[ingestion/flush-cache] flush step failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "message": "Cache flush to live_trades failed",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── Step 2: archive aged live_trades → historical_trades ──────────────
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=archive_older_than_minutes)
        dao = AlpacaDAO()
        try:
            archived = dao.archive_live_trades(cutoff_time=cutoff)
            result["trades_archived"] = archived
            logger.info(f"[ingestion/flush-cache] archived {archived} trade(s) older than {cutoff.isoformat()}")
        finally:
            dao.close()
    except Exception as exc:
        logger.error(f"[ingestion/flush-cache] archive step failed: {exc}", exc_info=True)
        result["archive_warning"] = str(exc)

    result["message"] = (
        f"Flushed {result['trades_flushed']} trade(s) to live_trades; "
        f"archived {result['trades_archived']} trade(s) to historical_trades"
    )
    return result
