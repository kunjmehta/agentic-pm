"""Database-backed stream handlers for Alpaca real-time data.

This module provides async handlers that save stream data (trades, bars) to
the database using DAOs. Handlers can be used standalone or combined with
print/logging for visibility.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from src.common.dao import AlpacaDAO
from src.common.data_gatherer.trade_cache import get_cache
from src.common.utils import get_logger, config, secrets


# Initialize logger
logger = get_logger(__name__)

# Lazy-loaded ws_manager (to avoid circular import issues)
_ws_manager = None

# IoC callbacks — injected by lifespan.py / etl_process.py after startup.
# When set, these take priority over the lazy-loaded fallbacks below.
_ws_broadcaster = None    # Callable[[dict], Awaitable[None]] | None
_strategy_registry = None  # strategy_registry module | None


def set_ws_broadcaster(fn) -> None:
    """Register the WebSocket broadcast callback (called from lifespan / ETL process).

    Args:
        fn: Async callable accepting a dict message, e.g. ``ws_manager.broadcast``.
    """
    global _ws_broadcaster
    _ws_broadcaster = fn
    logger.debug("[db_stream_handlers] WebSocket broadcaster registered")


def set_strategy_registry(registry_module) -> None:
    """Register the strategy registry module (called from lifespan / ETL process).

    Args:
        registry_module: The ``src.server.registry.strategy_registry`` module
            (or any object exposing ``list_by_timeframe``, ``get_metadata``,
            ``instantiate``).
    """
    global _strategy_registry
    _strategy_registry = registry_module
    logger.debug("[db_stream_handlers] Strategy registry registered")


def get_ws_manager():
    """Get or create WebSocket manager instance (fallback when IoC not used).

    Returns:
        PortfolioWSManager instance (singleton)
    """
    global _ws_manager
    if _ws_manager is None:
        try:
            from src.server.ws_manager import ws_manager
            _ws_manager = ws_manager
            logger.debug("WebSocket manager loaded for broadcasting")
        except ImportError:
            logger.warning("ws_manager not available - UI broadcasts disabled")
            _ws_manager = None
    return _ws_manager

# Module-level DAO instance (singleton)
_dao = None

# Background flush task handle
_flush_task = None


def get_dao() -> AlpacaDAO:
    """Get or create DAO instance.

    Returns:
        AlpacaDAO instance (singleton)
    """
    global _dao
    if _dao is None:
        _dao = AlpacaDAO()
        logger.info("AlpacaDAO instance created for stream handlers")
    return _dao


async def save_trade_to_db(trade):
    """Save trade data directly to database (no caching).

    Args:
        trade: Either Alpaca trade object OR dict with trade data.
               Dict must have keys: symbol, timestamp, trade_id, price, size
               Optional keys: exchange, conditions, tape

    Note: This bypasses the cache. Use save_trade_to_cache() for batched writes.
    """
    try:
        dao = get_dao()

        # Duck typing for backward compatibility: accept both dict and Alpaca object
        if isinstance(trade, dict):
            # Redis Stream dict payload
            symbol = trade['symbol']
            timestamp = trade['timestamp']
            trade_id = trade['trade_id']
            price = float(trade['price'])
            size = int(trade['size'])
            exchange = trade.get('exchange')
            conditions = trade.get('conditions', '')
            tape = trade.get('tape')
        else:
            # Legacy Alpaca trade object
            symbol = trade.symbol
            timestamp = trade.timestamp
            trade_id = trade.id
            price = float(trade.price)
            size = int(trade.size)
            exchange = trade.exchange if hasattr(trade, 'exchange') else None
            conditions = ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else ''
            tape = trade.tape if hasattr(trade, 'tape') else None

        # Convert to DataFrame
        df_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'trade_id': trade_id,
            'price': price,
            'size': size,
            'exchange': exchange,
            'conditions': conditions,
            'tape': tape
        }
        trade_df = pd.DataFrame([df_data])

        # Save to database
        dao.save_trades(trade_df)
        logger.debug(f"Saved trade to DB: {symbol} @ ${price:.2f}")

    except Exception as e:
        logger.error(f"Failed to save trade to DB: {e}", exc_info=True)


async def save_trade_to_cache(trade):
    """Save trade data to cache for batched database writes.

    This is the recommended handler for live WebSocket streams as it reduces
    database write frequency by batching trades in memory.

    Args:
        trade: Either Alpaca trade object OR dict with trade data.
               Dict must have keys: symbol, timestamp, trade_id, price, size
               Optional keys: exchange, conditions, tape
    """
    try:
        cache = get_cache()

        # Duck typing for backward compatibility: accept both dict and Alpaca object
        if isinstance(trade, dict):
            # Redis Stream dict payload
            symbol = trade['symbol']
            timestamp = trade['timestamp']
            trade_id = trade['trade_id']
            price = float(trade['price'])
            size = int(trade['size'])
            exchange = trade.get('exchange')
            conditions = trade.get('conditions', '')
            tape = trade.get('tape')
        else:
            # Legacy Alpaca trade object
            symbol = trade.symbol
            timestamp = trade.timestamp
            trade_id = trade.id
            price = float(trade.price)
            size = int(trade.size)
            exchange = trade.exchange if hasattr(trade, 'exchange') else None
            conditions = ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else ''
            tape = trade.tape if hasattr(trade, 'tape') else None

        # Normalize data for cache
        normalized_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'trade_id': trade_id,
            'price': price,
            'size': size,
            'exchange': exchange,
            'conditions': conditions,
            'tape': tape
        }

        # Add to cache
        should_flush = cache.add_trade(normalized_data)

        logger.debug(f"Added trade to cache: {symbol} @ ${price:.2f}")

        # Flush if threshold met
        if should_flush:
            await flush_cache_to_db()

    except Exception as e:
        logger.error(f"Failed to save trade to cache: {e}", exc_info=True)


async def handle_trade_correction(correction):
    """Handle trade correction from Alpaca stream.

    Reference: https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-corrections

    Args:
        correction: Alpaca trade correction object with original and corrected data
    """
    try:
        cache = get_cache()
        dao = get_dao()

        symbol = correction.symbol
        trade_id = correction.id  # Original trade ID
        corrected_price = float(correction.price)
        corrected_size = int(correction.size)

        # Build correction data
        correction_data = {
            'symbol': symbol,
            'trade_id': trade_id,
            'price': corrected_price,
            'size': corrected_size,
            'timestamp': correction.timestamp if hasattr(correction, 'timestamp') else None,
            'exchange': correction.exchange if hasattr(correction, 'exchange') else None,
            'conditions': ','.join(correction.conditions) if hasattr(correction, 'conditions') and correction.conditions else '',
            'tape': correction.tape if hasattr(correction, 'tape') else None
        }

        # Try to update in cache first
        updated_in_cache = cache.update_trade(correction_data)

        if updated_in_cache:
            logger.info(f"Trade correction applied in cache: {symbol} trade_id={trade_id}")
        else:
            # Trade not in cache — already flushed to live_trades staging table.
            # Upsert the corrected row there (primary key will overwrite).
            logger.info(f"Trade not in cache, updating in live_trades: {symbol} trade_id={trade_id}")

            correction_df = pd.DataFrame([correction_data])
            dao.save_live_trades(correction_df)
            logger.info(f"Trade correction applied in live_trades: {symbol} trade_id={trade_id}")

    except Exception as e:
        logger.error(f"Failed to handle trade correction: {e}", exc_info=True)


async def handle_trade_cancellation(cancellation):
    """Handle trade cancellation/error from Alpaca stream.

    Reference: https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-cancelserrors

    Args:
        cancellation: Alpaca trade cancellation object with trade ID to cancel
    """
    try:
        cache = get_cache()
        dao = get_dao()

        symbol = cancellation.symbol
        trade_id = cancellation.id  # Trade ID to cancel

        # Try to cancel in cache first
        cancelled_in_cache = cache.cancel_trade(symbol, trade_id)

        if cancelled_in_cache:
            logger.info(f"Trade cancelled in cache: {symbol} trade_id={trade_id}")
        else:
            # Trade not in cache — already flushed to live_trades staging table.
            # Delete from live_trades first, then from historical_trades as a safety net
            # (trade might have been archived already).
            logger.info(f"Trade not in cache, deleting from live_trades: {symbol} trade_id={trade_id}")
            dao.execute(
                "DELETE FROM live_trades WHERE symbol = ? AND trade_id = ?",
                (symbol, trade_id),
            )
            dao.execute(
                "DELETE FROM historical_trades WHERE symbol = ? AND trade_id = ?",
                (symbol, trade_id),
            )
            logger.info(f"Trade cancellation applied to live_trades and historical_trades: {symbol} trade_id={trade_id}")

    except Exception as e:
        logger.error(f"Failed to handle trade cancellation: {e}", exc_info=True)


async def flush_cache_to_db():
    """Flush cached trades to live_trades table in database.

    This function is called automatically when cache thresholds are met,
    or can be called manually to force a flush.
    """
    try:
        cache = get_cache()
        dao = get_dao()

        # Get all cached trades
        df = cache.flush()

        if df.empty:
            logger.debug("No trades to flush from cache")
            return

        # Save to live_trades (staging table).  Historical archival happens
        # separately via AlpacaDAO.archive_live_trades() from the API endpoint.
        rows = dao.save_live_trades(df)

        logger.info(f"Flushed {len(df):,} trades to live_trades ({rows} rows affected)")

    except Exception as e:
        logger.error(f"Failed to flush cache to DB: {e}", exc_info=True)


def _get_previous_close_from_alpaca(symbol: str) -> Optional[float]:
    """Helper to fetch previous day close from Alpaca API (synchronous for thread pool).

    Searches back up to 5 days to find the most recent trading day's closing price.
    This is used for calculating % change in real-time bar updates.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Previous close price as float, or None if not available
    """
    try:
        api_key = secrets.get("alpaca.api_key")
        api_secret = secrets.get("alpaca.secret_key")
        client = StockHistoricalDataClient(api_key, api_secret)

        # Search back up to 5 days for last trading day
        for days_back in range(1, 6):
            end_date = datetime.now() - timedelta(days=days_back)
            start_date = end_date - timedelta(days=1)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
            )

            bars = client.get_stock_bars(request)
            if symbol in bars and len(bars[symbol]) > 0:
                close_price = float(bars[symbol][-1].close)
                logger.debug(f"Previous close for {symbol}: ${close_price:.2f} ({days_back} days back)")
                return close_price

        logger.warning(f"No previous close data found for {symbol} in last 5 days")
        return None

    except Exception as exc:
        logger.warning(f"Failed to fetch previous close for {symbol} from Alpaca: {exc}")
        return None


async def broadcast_bar_to_ui(bar, timeframe: str = '1Min'):
    """Broadcast bar update to connected UI clients with % change from previous close.

    Args:
        bar: Either Alpaca bar object OR dict with bar data
             Dict must have keys: symbol, timestamp, open, high, low, close, volume
             Optional keys: vwap
        timeframe: Bar timeframe string (default: '1Min')
    """
    # Prefer injected broadcaster; fall back to lazy-loaded ws_manager.
    _broadcast = _ws_broadcaster or (getattr(get_ws_manager(), 'broadcast', None))
    if _broadcast is None:
        return

    try:
        # Duck typing: extract data from either dict or Alpaca object
        if isinstance(bar, dict):
            symbol = bar['symbol']
            timestamp = bar['timestamp']
            open_price = float(bar['open'])
            high_price = float(bar['high'])
            low_price = float(bar['low'])
            close_price = float(bar['close'])
            volume = int(bar['volume'])
            vwap = float(bar['vwap']) if bar.get('vwap') else None
        else:
            symbol = bar.symbol
            timestamp = bar.timestamp
            open_price = float(bar.open)
            high_price = float(bar.high)
            low_price = float(bar.low)
            close_price = float(bar.close)
            volume = int(bar.volume)
            vwap = float(bar.vwap) if hasattr(bar, 'vwap') and bar.vwap else None

        # Calculate % change from previous close via Alpaca API
        prev_close = await asyncio.to_thread(_get_previous_close_from_alpaca, symbol)

        pct_change = None
        if prev_close:
            pct_change = ((close_price - prev_close) / prev_close) * 100

        # Handle timestamp - could be string or datetime
        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.isoformat()

        message = {
            "type": "bar_update",
            "symbol": symbol,
            "timestamp": timestamp_str,
            "timeframe": timeframe,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "vwap": vwap,
            "prev_close": prev_close,
            "pct_change": round(pct_change, 2) if pct_change else None
        }
        await _broadcast(message)
    except Exception as exc:
        logger.debug(f"Failed to broadcast bar to UI: {exc}")


async def save_bar_to_db(bar, timeframe: str = '1Min'):
    """Save bar data to database and automatically compute indicators.

    This function implements the auto-run ETL pipeline:
    1. Save bar to database
    2. Fetch recent bars (lookback window)
    3. Compute indicators
    4. Save computed indicators

    Args:
        bar: Either Alpaca bar object OR dict with bar data.
             Dict must have keys: symbol, timestamp, open, high, low, close, volume
             Optional keys: trade_count, vwap
        timeframe: Bar timeframe string (default: '1Min')
    """
    try:
        dao = get_dao()

        # Duck typing for backward compatibility: accept both dict and Alpaca object
        if isinstance(bar, dict):
            # Redis Stream dict payload
            symbol = bar['symbol']
            timestamp = bar['timestamp']
            open_price = float(bar['open'])
            high_price = float(bar['high'])
            low_price = float(bar['low'])
            close_price = float(bar['close'])
            volume = int(bar['volume'])
            trade_count = int(bar.get('trade_count')) if bar.get('trade_count') else None
            vwap = float(bar.get('vwap')) if bar.get('vwap') else None
        else:
            # Legacy Alpaca bar object
            symbol = bar.symbol
            timestamp = bar.timestamp
            open_price = float(bar.open)
            high_price = float(bar.high)
            low_price = float(bar.low)
            close_price = float(bar.close)
            volume = int(bar.volume)
            trade_count = int(bar.trade_count) if hasattr(bar, 'trade_count') else None
            vwap = float(bar.vwap) if hasattr(bar, 'vwap') else None

        # Convert to DataFrame
        df_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'trade_count': trade_count,
            'vwap': vwap
        }
        bar_df = pd.DataFrame([df_data])

        # Save bar to database
        dao.save_bars(bar_df, timeframe=timeframe)
        logger.debug(f"Saved bar to DB: {symbol} @ {timestamp}")

        # Broadcast to UI
        await broadcast_bar_to_ui(bar, timeframe)

        # Auto-compute indicators if enabled
        etl_enabled = config.get("etl.enabled", default=True)
        if etl_enabled:
            logger.debug(f"Auto-computing indicators for {symbol} {timeframe}")
            await _compute_and_save_indicators(symbol, timeframe, dao)
        else:
            logger.warning(f"ETL disabled - skipping indicator computation for {symbol}")

    except Exception as e:
        logger.error(f"Failed to save bar to DB: {e}", exc_info=True)


def _build_indicator_row(symbol: str, timestamp, timeframe: str, result: dict) -> dict:
    """Flatten a single ``IndicatorsEngine.calc_all`` result into a DB-ready dict.

    Args:
        symbol: Stock ticker.
        timestamp: Bar timestamp value.
        timeframe: Bar timeframe string.
        result: Dict returned by ``IndicatorsEngine.calc_all``.

    Returns:
        Flat dict matching the ``computed_indicators`` table schema.
    """
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "timeframe": timeframe,
        # Momentum
        "macd_value": result["momentum"]["macd"]["value"],
        "macd_signal": result["momentum"]["macd"]["signal"],
        "macd_histogram": result["momentum"]["macd"]["histogram"],
        "rsi": result["momentum"]["rsi"],
        # Volatility
        "bb_upper": result["volatility"]["upper"],
        "bb_middle": result["volatility"]["middle"],
        "bb_lower": result["volatility"]["lower"],
        "bb_bandwidth": result["volatility"]["bandwidth"],
        # Volume
        "obv": result["volume"]["obv"],
        "volume_trend": result["volume"]["volume_trend"],
        "avg_volume_10d": result["volume"]["avg_volume_10d"],
        "current_vs_avg": result["volume"]["current_vs_avg"],
        # Mean reversion
        "z_score": result["mean_reversion"]["z_score"],
        "percentile": result["mean_reversion"]["percentile"],
        "vwap": result["mean_reversion"].get("vwap"),
    }


async def _compute_and_save_indicators(symbol: str, timeframe: str, dao: AlpacaDAO):
    """Compute indicators for the most recent bar and save to database.

    Uses two modes to avoid O(n²) recomputation on every bar tick:

    * **Seed mode** — first time (no existing rows for this symbol+timeframe in
      the last 24 h): runs the full rolling window back-fill so all historical
      indicator rows are populated.
    * **Live mode** — subsequent bar events: computes indicators only for the
      latest bar (O(1)), since everything before it is already persisted.

    Args:
        symbol: Stock symbol
        timeframe: Bar timeframe
        dao: AlpacaDAO instance
    """
    try:
        from src.common.etl.indicators_engine import IndicatorsEngine
        from datetime import datetime, timedelta

        lookback_days = config.get("etl.lookback_days", default=60)
        # Use the strategy lookback as the minimum bar count so both steps stay in sync.
        min_bars: int = int(config.get("strategy.mean_reversion.lookback", default=120))

        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        bars = dao.get_bars(symbol=symbol, start=start_date, end=end_date, timeframe=timeframe)

        if bars.empty or len(bars) < min_bars:
            logger.info(
                f"⏳ Insufficient data for {symbol} {timeframe} — "
                f"have {len(bars)} bars, need {min_bars}+"
            )
            return

        engine = IndicatorsEngine()

        # ── Detect seed vs live mode ───────────────────────────────────────────
        # Check for ANY indicator rows written in the last 24 hours.
        recent_check = dao.get_computed_indicators(
            symbol, end_date - timedelta(hours=24), end_date, timeframe
        )
        is_live_mode = not recent_check.empty

        if is_live_mode:
            # Live (incremental): compute only for the single latest bar.
            result = engine.calc_all(bars)
            timestamp = bars.iloc[-1]["timestamp"]
            indicator_rows = [_build_indicator_row(symbol, timestamp, timeframe, result)]
            mode_label = "live/incremental"
        else:
            # Seed: back-fill the full rolling window (runs once per symbol).
            indicator_rows = []
            for i in range(min_bars, len(bars) + 1):
                window = bars.iloc[:i].copy()
                result = engine.calc_all(window)
                indicator_rows.append(
                    _build_indicator_row(symbol, window.iloc[-1]["timestamp"], timeframe, result)
                )
            mode_label = f"seed ({len(indicator_rows)} rows)"

        indicators_df = pd.DataFrame(indicator_rows)

        if hasattr(dao, "save_computed_indicators"):
            rows = dao.save_computed_indicators(indicators_df)
            logger.info(
                f"✓ Indicators [{mode_label}] saved {rows} rows for {symbol} {timeframe}"
            )
        else:
            logger.error("❌ AlpacaDAO.save_computed_indicators() method missing — cannot save indicators")

        # Generate and persist strategy signals from the same bars.
        strategy_enabled = config.get("strategy.enabled", default=True)
        if strategy_enabled:
            await _run_all_strategy_signals(symbol, timeframe, bars, config)

    except Exception as e:
        logger.error(f"❌ Failed to compute/save indicators for {symbol} {timeframe}: {e}", exc_info=True)
        logger.error(f"   Context: {len(bars) if 'bars' in locals() else 'unknown'} bars fetched")


async def _save_flat_signal(
    symbol: str,
    timeframe: str,
    strategy_name: str,
    result: dict,
    s_dao,
) -> None:
    """Persist any flat-result strategy signal dict to StrategyDAO.

    Handles two result shapes:
    - **Flat** (all 8 new strategies): result keys are directly action/
      confidence/entry_price/stop_loss/take_profit/reason/current_price.
    - **Nested mean-reversion** shape: pulls action/confidence/etc. from
      ``trade_recommendation`` and statistics/signals from their sub-dicts.

    Args:
        symbol: Stock ticker (already upper-cased).
        timeframe: Bar timeframe string.
        strategy_name: Canonical strategy name stored in DB.
        result: Dict returned by the skill's ``analyze_bars`` or
            ``generate_signals`` method.
        s_dao: Open StrategyDAO instance managed by the caller.
    """
    # Mean-reversion nested shape
    if "trade_recommendation" in result:
        rec = result.get("trade_recommendation", {})
        signals = result.get("signals", {})
        s_dao.save_strategy_result(
            symbol=symbol,
            strategy_name=strategy_name,
            current_price=result.get("current_price", 0.0),
            statistics=result.get("statistics", {}),
            indicators={
                "moving_averages": result.get("moving_averages", {}),
                "levels": result.get("levels", {}),
            },
            signals=signals,
            action=rec.get("action", "hold"),
            confidence=float(rec.get("confidence", 0.0)),
            reason=rec.get("reason", ""),
            entry_price=rec.get("entry_price"),
            stop_loss=rec.get("stop_loss"),
            take_profit=rec.get("take_profit"),
            support_level=result.get("levels", {}).get("support"),
            resistance_level=result.get("levels", {}).get("resistance"),
            current_state=signals.get("current_state"),
            parameters=result.get("parameters", {}),
            timeframe=timeframe,
            model_used="rule-based",
        )
        logger.info(
            f"✓ [{strategy_name}] {symbol}/{timeframe}: "
            f"action={rec.get('action','hold')}  "
            f"confidence={rec.get('confidence', 0.0):.2f}  "
            f"state={signals.get('current_state', '?')}"
        )
    else:
        # Flat shape — all 8 new strategy wrappers
        action = result.get("action", "hold")
        confidence = float(result.get("confidence", 0.0))
        s_dao.save_strategy_result(
            symbol=symbol,
            strategy_name=strategy_name,
            current_price=float(result.get("current_price", 0.0)),
            statistics={},
            indicators={},
            signals={"overall_signal": action},
            action=action,
            confidence=confidence,
            reason=result.get("reason", ""),
            entry_price=result.get("entry_price"),
            stop_loss=result.get("stop_loss"),
            take_profit=result.get("take_profit"),
            current_state=action if action != "hold" else "neutral",
            parameters={
                k: v for k, v in result.items()
                if k not in {"action", "confidence", "reason", "entry_price",
                             "stop_loss", "take_profit", "current_price",
                             "symbol", "timeframe", "timestamp", "error"}
            },
            timeframe=timeframe,
            model_used="rule-based",
        )
        logger.info(
            f"✓ [{strategy_name}] {symbol}/{timeframe}: "
            f"action={action}  confidence={confidence:.2f}"
        )


async def _run_intraday_strategies(
    symbol: str,
    timeframe: str,
    bars: "pd.DataFrame",
    cfg,
    s_dao,
) -> None:
    """Run all intraday strategies on the pre-fetched bar DataFrame.

    Uses the strategy registry to dynamically discover and execute all strategies
    that support the given timeframe. Each strategy is skipped if bars < min_bars
    without failing the others.

    Args:
        symbol: Stock ticker (upper-case).
        timeframe: Intraday timeframe string.
        bars: Full bar history DataFrame available at this point.
        cfg: Config accessor.
        s_dao: Open StrategyDAO instance managed by the caller.
    """
    if _strategy_registry is not None:
        registry = _strategy_registry.get_registry()
    else:
        from src.common.registry.strategy_registry import get_registry
        from src.server.registry.register_strategies import ensure_strategies_registered
        ensure_strategies_registered()
        registry = get_registry()

    # Get registry and filter for this timeframe
    strategy_names = registry.list_by_timeframe(timeframe)

    n = len(bars)
    logger.debug(f"Running {len(strategy_names)} strategies for {symbol} {timeframe} ({n} bars)")

    # Run each registered strategy
    for strategy_name in strategy_names:
        metadata = registry.get_metadata(strategy_name)

        # Skip if not enough bars
        if n < metadata.min_bars:
            logger.debug(
                f"Skipping [{strategy_name}] {symbol}: need {metadata.min_bars} bars, have {n}"
            )
            continue

        try:
            # Instantiate strategy
            strategy = registry.instantiate(strategy_name)
            if strategy is None:
                logger.warning(f"Failed to instantiate [{strategy_name}]")
                continue

            # Build parameters from config using metadata
            params = {}
            config_prefix = metadata.config_prefix or f"strategy.{strategy_name.replace('-', '_')}"

            for param_name, param_meta in metadata.parameters.items():
                default_value = param_meta.get("default")
                config_key = f"{config_prefix}.{param_name}"

                # Get value from config, with type conversion
                param_type = param_meta.get("type", "float")
                if param_type == "int":
                    params[param_name] = int(cfg.get(config_key, default=default_value))
                elif param_type == "float":
                    params[param_name] = float(cfg.get(config_key, default=default_value))
                else:
                    params[param_name] = cfg.get(config_key, default=default_value)

            # Execute strategy
            result = strategy.analyze_bars(bars, **params)

            # Save signal if valid
            if "error" not in result:
                result.setdefault("symbol", symbol)
                await _save_flat_signal(symbol, timeframe, strategy_name, result, s_dao)
            else:
                logger.debug(f"[{strategy_name}] {symbol}: {result.get('error')}")

        except Exception as exc:
            logger.warning(f"[{strategy_name}] {symbol}: {exc}", exc_info=True)


async def _run_daily_strategies(
    symbol: str,
    timeframe: str,
    bars: "pd.DataFrame",
    cfg,
    s_dao,
) -> None:
    """Run all swing / daily strategies on the pre-fetched daily bar DataFrame.

    Uses the strategy registry to dynamically discover and execute all strategies
    that support the given timeframe (1Day). Each strategy is skipped if bars < min_bars
    without failing the others.

    Args:
        symbol: Stock ticker (upper-case).
        timeframe: ``"1Day"`` timeframe string.
        bars: Full daily bar history DataFrame.
        cfg: Config accessor.
        s_dao: Open StrategyDAO instance managed by the caller.
    """
    if _strategy_registry is not None:
        registry = _strategy_registry.get_registry()
    else:
        from src.common.registry.strategy_registry import get_registry
        from src.server.registry.register_strategies import ensure_strategies_registered
        ensure_strategies_registered()
        registry = get_registry()

    # Get registry and filter for this timeframe
    strategy_names = registry.list_by_timeframe(timeframe)

    n = len(bars)
    logger.debug(f"Running {len(strategy_names)} daily strategies for {symbol} {timeframe} ({n} bars)")

    # Run each registered strategy
    for strategy_name in strategy_names:
        metadata = registry.get_metadata(strategy_name)

        # Skip if not enough bars
        if n < metadata.min_bars:
            logger.debug(
                f"Skipping [{strategy_name}] {symbol}: need {metadata.min_bars} bars, have {n}"
            )
            continue

        try:
            # Instantiate strategy
            strategy = registry.instantiate(strategy_name)
            if strategy is None:
                logger.warning(f"Failed to instantiate [{strategy_name}]")
                continue

            # Build parameters from config using metadata
            params = {}
            config_prefix = metadata.config_prefix or f"strategy.{strategy_name.replace('-', '_')}"

            for param_name, param_meta in metadata.parameters.items():
                default_value = param_meta.get("default")
                config_key = f"{config_prefix}.{param_name}"

                # Get value from config, with type conversion
                param_type = param_meta.get("type", "float")
                if param_type == "int":
                    params[param_name] = int(cfg.get(config_key, default=default_value))
                elif param_type == "float":
                    params[param_name] = float(cfg.get(config_key, default=default_value))
                else:
                    params[param_name] = cfg.get(config_key, default=default_value)

            # Execute strategy
            result = strategy.analyze_bars(bars, **params)

            # Save signal if valid
            if "error" not in result:
                result.setdefault("symbol", symbol)
                await _save_flat_signal(symbol, timeframe, strategy_name, result, s_dao)
            else:
                logger.debug(f"[{strategy_name}] {symbol}: {result.get('error')}")

        except Exception as exc:
            logger.warning(f"[{strategy_name}] {symbol}: {exc}", exc_info=True)


async def _run_all_strategy_signals(
    symbol: str,
    timeframe: str,
    bars: "pd.DataFrame",
    cfg,
) -> None:
    """Run all applicable strategies for *timeframe* and persist signals to DB.

    Dispatches to two groups based on timeframe:

    **Intraday** (``1Min``, ``5Min``, ``15Min``, ``1Hour``):
        - mean-reversion (requires 120 bars by default)
        - vwap-reversion  (requires 26 bars)
        - opening-range-breakout (requires range_bars + 5, default 20)
        - rsi-divergence  (requires 20 bars)
        - momentum-burst  (requires 10 bars)

    **Daily** (``1Day``):
        - mean-reversion-daily (requires 20 bars)
        - golden-cross  (requires 200 bars)
        - breakout-52w  (requires 252 bars)
        - earnings-drift (requires 10 bars)

    All strategies share a single open StrategyDAO instance for the duration
    of the call, avoiding repeated connection overhead.

    Args:
        symbol: Stock ticker symbol (upper-case).
        timeframe: AlpacaDAO canonical timeframe string.
        bars: Full bar history DataFrame fetched by the caller.
        cfg: Config accessor (the module-level ``config`` object).
    """
    try:
        from src.common.dao.strategy_dao import StrategyDAO
        s_dao = StrategyDAO()
        try:
            if timeframe in ("1Min", "5Min", "15Min", "1Hour"):
                await _run_intraday_strategies(symbol, timeframe, bars, cfg, s_dao)
            elif timeframe == "1Day":
                await _run_daily_strategies(symbol, timeframe, bars, cfg, s_dao)
            else:
                logger.debug(f"[strategy] No strategy group for timeframe={timeframe}")
        finally:
            s_dao.close()
    except Exception as exc:
        logger.error(
            f"❌ _run_all_strategy_signals failed for {symbol} {timeframe}: {exc}",
            exc_info=True,
        )


async def combined_trade_handler(trade):
    """Combined handler: print AND save to database (direct, no cache).

    Args:
        trade: Either Alpaca trade object OR dict with trade data

    Note: This bypasses cache. Use combined_trade_cache_handler() for batched writes.
    """
    # Duck typing: extract data for logging
    if isinstance(trade, dict):
        symbol = trade['symbol']
        price = trade['price']
        size = trade['size']
        exchange = trade.get('exchange', 'N/A')
        timestamp = trade['timestamp']
    else:
        symbol = trade.symbol
        price = trade.price
        size = trade.size
        exchange = trade.exchange if hasattr(trade, 'exchange') else 'N/A'
        timestamp = trade.timestamp

    # Log for visibility
    logger.info(f"[TRADE] {symbol} @ ${price:.2f} x {size} | "
          f"Exchange: {exchange} | {timestamp}")

    # Save to database (save_trade_to_db handles both formats)
    await save_trade_to_db(trade)


async def broadcast_trade_to_ui(trade):
    """Broadcast trade update to connected UI clients.

    Args:
        trade: Either Alpaca trade object OR dict with trade data
    """
    _broadcast = _ws_broadcaster or getattr(get_ws_manager(), "broadcast", None)
    if _broadcast is None:
        return

    try:
        # Duck typing: extract data from either dict or Alpaca object
        if isinstance(trade, dict):
            symbol = trade['symbol']
            price = float(trade['price'])
            size = int(trade['size'])
            timestamp = trade['timestamp']
            exchange = trade.get('exchange')
        else:
            symbol = trade.symbol
            price = float(trade.price)
            size = int(trade.size)
            timestamp = trade.timestamp
            exchange = trade.exchange if hasattr(trade, 'exchange') else None

        # Handle timestamp - could be string or datetime
        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.isoformat()

        message = {
            "type": "trade_update",
            "symbol": symbol,
            "price": price,
            "size": size,
            "timestamp": timestamp_str,
            "exchange": exchange,
        }
        await _broadcast(message)
    except Exception as exc:
        logger.debug(f"Failed to broadcast trade to UI: {exc}")


async def combined_trade_cache_handler(trade):
    """Combined handler: print AND save to cache for batched writes.

    This is the recommended handler for live WebSocket streams.

    Args:
        trade: Either Alpaca trade object OR dict with trade data
    """
    # Duck typing: extract data for logging
    if isinstance(trade, dict):
        symbol = trade['symbol']
        price = trade['price']
        size = trade['size']
        exchange = trade.get('exchange', 'N/A')
        timestamp = trade['timestamp']
    else:
        symbol = trade.symbol
        price = trade.price
        size = trade.size
        exchange = trade.exchange if hasattr(trade, 'exchange') else 'N/A'
        timestamp = trade.timestamp

    # Print for visibility
    print(f"[TRADE] {symbol} @ ${price:.2f} x {size} | "
          f"Exchange: {exchange} | {timestamp}")

    # Save to cache (save_trade_to_cache handles both formats)
    await save_trade_to_cache(trade)

    # Broadcast to UI (broadcast_trade_to_ui handles both formats)
    await broadcast_trade_to_ui(trade)


async def combined_bar_handler(bar, timeframe: str = '1Min'):
    """Combined handler: print AND save to database.

    Args:
        bar: Either Alpaca bar object OR dict with bar data
        timeframe: Bar timeframe string (default: '1Min')
    """
    # Duck typing: extract data for logging
    if isinstance(bar, dict):
        symbol = bar['symbol']
        open_price = bar['open']
        high_price = bar['high']
        low_price = bar['low']
        close_price = bar['close']
        volume = bar['volume']
        timestamp = bar['timestamp']
    else:
        symbol = bar.symbol
        open_price = bar.open
        high_price = bar.high
        low_price = bar.low
        close_price = bar.close
        volume = bar.volume
        timestamp = bar.timestamp

    # Print for visibility
    print(f"[BAR] {symbol} | O: ${open_price:.2f} H: ${high_price:.2f} "
          f"L: ${low_price:.2f} C: ${close_price:.2f} | "
          f"Vol: {volume:,} | {timestamp}")

    # Save to database (save_bar_to_db handles both formats)
    await save_bar_to_db(bar, timeframe=timeframe)


async def combined_trade_correction_handler(correction):
    """Combined handler: print AND handle trade correction.

    Args:
        correction: Alpaca trade correction object
    """
    # Print for visibility
    print(f"[CORRECTION] {correction.symbol} trade_id={correction.id} | "
          f"New price: ${correction.price:.2f} | Size: {correction.size}")

    # Handle correction (cache or database)
    await handle_trade_correction(correction)


async def combined_trade_cancellation_handler(cancellation):
    """Combined handler: print AND handle trade cancellation.

    Args:
        cancellation: Alpaca trade cancellation object
    """
    # Print for visibility
    print(f"[CANCEL] {cancellation.symbol} trade_id={cancellation.id} | Trade cancelled/error")

    # Handle cancellation (cache or database)
    await handle_trade_cancellation(cancellation)


async def _background_flush_task():
    """Background task that periodically flushes cache to database.

    This task runs in the background and checks the cache every minute.
    If the cache needs flushing (based on time or size thresholds),
    it flushes to the database.

    This task runs indefinitely until cancelled.
    """
    check_interval = 60  # Check every minute

    logger.info("Background flush task started")

    try:
        while True:
            await asyncio.sleep(check_interval)

            cache = get_cache()
            stats = cache.get_stats()

            # Check if flush is needed
            if stats['current_size'] > 0:
                time_threshold = stats['batch_interval_seconds']
                time_elapsed = stats['time_since_flush_seconds']

                if time_elapsed >= time_threshold:
                    logger.info(
                        f"Background flush triggered: {stats['current_size']:,} trades, "
                        f"{time_elapsed:.0f}s since last flush"
                    )
                    await flush_cache_to_db()

    except asyncio.CancelledError:
        logger.info("Background flush task cancelled")
        # Flush remaining trades before exiting
        await flush_cache_to_db()
        raise
    except Exception as e:
        logger.error(f"Background flush task error: {e}", exc_info=True)


def start_background_flush_task():
    """Start the background flush task.

    Returns:
        asyncio.Task: The background task handle

    Note: Call this once when starting the WebSocket stream.
    """
    global _flush_task

    if _flush_task is not None and not _flush_task.done():
        logger.warning("Background flush task already running")
        return _flush_task

    _flush_task = asyncio.create_task(_background_flush_task())
    logger.info("Background flush task created")

    return _flush_task


async def stop_background_flush_task():
    """Stop the background flush task gracefully.

    This will cancel the task and flush any remaining cached trades.

    Note: Call this when shutting down the WebSocket stream.
    """
    global _flush_task

    if _flush_task is None:
        logger.warning("No background flush task to stop")
        return

    if not _flush_task.done():
        logger.info("Stopping background flush task...")
        _flush_task.cancel()

        try:
            await _flush_task
        except asyncio.CancelledError:
            logger.info("Background flush task stopped")

    _flush_task = None


if __name__ == "__main__":
    """Test the DB handlers."""
    import asyncio
    from datetime import datetime

    # Mock trade object for testing
    class MockTrade:
        def __init__(self):
            self.symbol = "TEST"
            self.timestamp = datetime.now()
            self.id = 123456789
            self.price = 150.50
            self.size = 100
            self.exchange = "Q"
            self.conditions = ["@"]
            self.tape = "C"

    # Mock bar object for testing
    class MockBar:
        def __init__(self):
            self.symbol = "TEST"
            self.timestamp = datetime.now()
            self.open = 150.00
            self.high = 151.50
            self.low = 149.50
            self.close = 150.50
            self.volume = 1000000
            self.trade_count = 500
            self.vwap = 150.25

    async def test_handlers():
        """Test the handlers with mock data."""
        print("="*60)
        print("Testing DB Stream Handlers")
        print("="*60)

        # Test trade handler
        print("\n1. Testing save_trade_to_db()...")
        mock_trade = MockTrade()
        await save_trade_to_db(mock_trade)
        print("   [OK] Trade saved")

        # Test bar handler
        print("\n2. Testing save_bar_to_db()...")
        mock_bar = MockBar()
        await save_bar_to_db(mock_bar, timeframe='1Min')
        print("   [OK] Bar saved")

        # Test combined handlers
        print("\n3. Testing combined_trade_handler()...")
        await combined_trade_handler(mock_trade)
        print("   [OK] Combined trade handler")

        print("\n4. Testing combined_bar_handler()...")
        await combined_bar_handler(mock_bar, timeframe='1Min')
        print("   [OK] Combined bar handler")

        # Verify data was saved
        print("\n5. Verifying saved data...")
        dao = get_dao()

        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(minutes=5)

        trades = dao.get_trades("TEST", start=start, end=end)
        bars = dao.get_bars("TEST", start=start, end=end, timeframe='1Min')

        print(f"   [OK] Retrieved {len(trades)} trades from DB")
        print(f"   [OK] Retrieved {len(bars)} bars from DB")

        # Cleanup
        print("\n6. Cleaning up test data...")
        dao.execute("DELETE FROM historical_trades WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM market_bars WHERE symbol = 'TEST'")
        dao.close()
        print("   [OK] Test complete")

        print("\n" + "="*60)

    # Run test
    asyncio.run(test_handlers())
