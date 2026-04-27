"""Ingestion package — real-time streaming, trade caching, and ETL computation.

Unified public API for all data ingestion concerns:
- ``TradeCache`` / ``get_cache`` — in-memory trade buffering before DB flush
- ``AlpacaDataStreamer`` — WebSocket connection per symbol
- ``DataCoordinator`` — multi-symbol initialization and stream orchestration
- ``IndicatorsETL`` / ``get_indicators_etl`` — batch ETL and bar-triggered computation
- Stream handler functions — bar/trade persistence, WS broadcast, flush lifecycle
"""

from src.common.ingestion.trade_cache import get_cache, TradeCache
from src.common.ingestion.alpaca_stream import AlpacaDataStreamer
from src.common.ingestion.coordinator import DataCoordinator
from src.common.ingestion.pipeline import IndicatorsETL, get_indicators_etl
from src.common.ingestion.stream_handlers import (
    set_ws_broadcaster,
    save_trade_to_db,
    save_trade_to_cache,
    flush_cache_to_db,
    save_bar_to_db,
    broadcast_bar_to_ui,
    combined_trade_handler,
    combined_bar_handler,
    combined_trade_cache_handler,
    combined_trade_correction_handler,
    combined_trade_cancellation_handler,
    start_background_flush_task,
    stop_background_flush_task,
)

__all__ = [
    "get_cache", "TradeCache",
    "AlpacaDataStreamer",
    "DataCoordinator",
    "IndicatorsETL", "get_indicators_etl",
    "set_ws_broadcaster",
    "save_trade_to_db", "save_trade_to_cache", "flush_cache_to_db",
    "save_bar_to_db", "broadcast_bar_to_ui",
    "combined_trade_handler", "combined_bar_handler",
    "combined_trade_cache_handler",
    "combined_trade_correction_handler", "combined_trade_cancellation_handler",
    "start_background_flush_task", "stop_background_flush_task",
]
