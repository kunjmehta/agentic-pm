"""Alpaca to Redis Stream ingestion service.

This module provides a standalone daemon that subscribes to Alpaca's
multi-ticker WebSocket feed and publishes all trade and bar data to
Redis Streams for downstream consumption.

Features:
- Multi-ticker subscription (loaded from config.json watchlist)
- Auto-retry with exponential backoff
- Graceful shutdown on SIGINT/SIGTERM
- Can run as systemd service/daemon
- Redis Stream publishing with msgpack serialization

Usage:
    python -m src.ingestion.alpaca_redis_ingestion

    # Or import and run programmatically:
    from src.ingestion import AlpacaRedisIngestion
    ingestion = AlpacaRedisIngestion()
    ingestion.run()
"""

import signal
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream

from src.common.cache.redis_stream_publisher import RedisStreamPublisher
from src.common.utils.config_loader import config, secrets
from src.common.utils.logger import get_logger

logger = get_logger(__name__)


class AlpacaRedisIngestion:
    """Real-time ingestion service for Alpaca market data to Redis Streams.

    Subscribes to Alpaca WebSocket for multiple tickers and publishes
    all trade/bar data to Redis Streams for downstream consumption.

    Example:
        >>> ingestion = AlpacaRedisIngestion()
        >>> ingestion.run()  # Runs until SIGINT/SIGTERM
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: str = "iex",
        max_retries: int = 5,
        base_retry_delay: int = 2,
        max_retry_delay: int = 60
    ):
        """Initialize Alpaca Redis ingestion service.

        Args:
            api_key: Alpaca API key (loads from secrets if not provided)
            secret_key: Alpaca secret key (loads from secrets if not provided)
            feed: Data feed to use ("iex" or "sip")
            max_retries: Maximum connection retry attempts
            base_retry_delay: Base delay for exponential backoff (seconds)
            max_retry_delay: Maximum retry delay cap (seconds)
        """
        # Load credentials
        self.api_key = api_key or secrets.get("alpaca.api_key")
        self.secret_key = secret_key or secrets.get("alpaca.secret_key")

        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials not found in secrets")

        # Configuration
        self.feed = DataFeed.IEX if feed.lower() == "iex" else DataFeed.SIP
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.max_retry_delay = max_retry_delay

        # Load watchlist from config
        self.symbols = self._load_watchlist_symbols()
        if not self.symbols:
            raise ValueError("No enabled symbols found in config.json watchlist")

        logger.info(f"Loaded {len(self.symbols)} symbols from watchlist: {self.symbols}")

        # Initialize Redis publisher
        self.publisher = RedisStreamPublisher()

        # State
        self.running = False
        self._shutdown_requested = False
        self.stream: Optional[StockDataStream] = None

        # Create initial stream
        self._create_stream()

    def _load_watchlist_symbols(self) -> List[str]:
        """Load enabled symbols from config.json watchlist.

        Returns:
            List[str]: List of enabled ticker symbols
        """
        watchlist = config.get("watchlist", default={})
        enabled_symbols = [
            symbol.upper()
            for symbol, settings in watchlist.items()
            if settings.get("enabled", False)
        ]
        return enabled_symbols

    def _create_stream(self) -> None:
        """Create a new StockDataStream instance."""
        self.stream = StockDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            feed=self.feed
        )

        # Subscribe to trades and bars for all symbols
        self.stream.subscribe_trades(self._on_trade, *self.symbols)
        self.stream.subscribe_bars(self._on_bar, *self.symbols)

        logger.info(f"Subscribed to trades and bars for {len(self.symbols)} symbols")

    async def _on_trade(self, trade) -> None:
        """Handle incoming trade data from Alpaca WebSocket.

        Converts Alpaca trade object to dictionary and publishes to Redis Stream.

        Args:
            trade: Alpaca trade object with attributes:
                - symbol: str
                - price: float
                - size: int
                - timestamp: datetime
                - conditions: list[str]
                - exchange: str
                - id: int
                - tape: str
        """
        try:
            # Convert trade to dictionary
            trade_data = {
                "price": float(trade.price),
                "size": int(trade.size),
                "timestamp": trade.timestamp.isoformat(),
                "conditions": trade.conditions if hasattr(trade, "conditions") else [],
                "exchange": trade.exchange if hasattr(trade, "exchange") else None,
                "id": trade.id if hasattr(trade, "id") else None,
                "tape": trade.tape if hasattr(trade, "tape") else None,
            }

            # Publish to Redis Stream
            entry_id = self.publisher.publish_trade(trade.symbol, trade_data)

            if entry_id:
                logger.debug(
                    f"Published trade: {trade.symbol} @ {trade.price} "
                    f"x {trade.size} (entry_id: {entry_id})"
                )
            else:
                logger.warning(f"Failed to publish trade for {trade.symbol}")

        except Exception as e:
            logger.error(f"Error handling trade for {trade.symbol}: {e}", exc_info=True)

    async def _on_bar(self, bar) -> None:
        """Handle incoming bar data from Alpaca WebSocket.

        Converts Alpaca bar object to dictionary and publishes to Redis Stream.

        Args:
            bar: Alpaca bar object with attributes:
                - symbol: str
                - timestamp: datetime
                - open: float
                - high: float
                - low: float
                - close: float
                - volume: int
                - vwap: float
                - trade_count: int
        """
        try:
            # Convert bar to dictionary
            bar_data = {
                "timestamp": bar.timestamp.isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
                "vwap": float(bar.vwap) if hasattr(bar, "vwap") and bar.vwap else None,
                "trade_count": int(bar.trade_count) if hasattr(bar, "trade_count") else None,
            }

            # Publish to Redis Stream
            entry_id = self.publisher.publish_bar(bar.symbol, bar_data)

            if entry_id:
                logger.debug(
                    f"Published bar: {bar.symbol} "
                    f"OHLC={bar.open}/{bar.high}/{bar.low}/{bar.close} "
                    f"V={bar.volume} (entry_id: {entry_id})"
                )
            else:
                logger.warning(f"Failed to publish bar for {bar.symbol}")

        except Exception as e:
            logger.error(f"Error handling bar for {bar.symbol}: {e}", exc_info=True)

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown.

        Registers handlers for SIGINT (Ctrl+C) and SIGTERM.
        Only works when called from main thread.
        """
        # Check if we're in the main thread
        if threading.current_thread() is not threading.main_thread():
            logger.debug("Skipping signal handler setup (not in main thread)")
            return

        def signal_handler(signum, frame):
            signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
            logger.info(f"Received {signal_name}. Initiating graceful shutdown...")
            self._shutdown_requested = True
            self.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("Signal handlers registered (SIGINT, SIGTERM)")

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """Calculate exponential backoff delay.

        Args:
            retry_count: Current retry attempt number (0-indexed)

        Returns:
            int: Delay in seconds (capped at max_retry_delay)
        """
        # Exponential backoff: base_delay * 2^retry_count
        delay = self.base_retry_delay * (2 ** retry_count)
        return min(delay, self.max_retry_delay)

    def run(self) -> None:
        """Run the ingestion service with retry logic and graceful shutdown.

        This method will:
        1. Setup signal handlers for graceful shutdown
        2. Connect to Alpaca WebSocket with exponential backoff retry
        3. Run until interrupted or max retries exceeded
        4. Gracefully shutdown on SIGINT/SIGTERM

        Raises:
            Exception: If all retry attempts fail
        """
        self._setup_signal_handlers()

        retry_count = 0

        logger.info("=" * 70)
        logger.info(f"Starting Alpaca Redis Ingestion Service")
        logger.info(f"Symbols: {self.symbols}")
        logger.info(f"Feed: {self.feed.value}")
        logger.info(f"Max retries: {self.max_retries}")
        logger.info("=" * 70)

        while retry_count < self.max_retries and not self._shutdown_requested:
            try:
                if retry_count > 0:
                    # Calculate exponential backoff delay
                    delay = self._calculate_retry_delay(retry_count - 1)
                    logger.info(
                        f"Retry attempt {retry_count}/{self.max_retries} "
                        f"(waiting {delay}s before reconnect)"
                    )
                    time.sleep(delay)

                    # Recreate stream on retry
                    logger.info("Recreating stream connection...")
                    self._create_stream()

                logger.info("Connecting to Alpaca WebSocket...")
                self.running = True

                # Run the stream (blocking call until error or stop())
                self.stream.run()

                # If we got here normally (not via exception), break retry loop
                logger.info("Stream ended normally")
                break

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self._shutdown_requested = True
                break

            except Exception as e:
                retry_count += 1
                logger.error(f"Stream error: {e}", exc_info=True)

                if retry_count >= self.max_retries:
                    logger.error(
                        f"Max retries ({self.max_retries}) reached. Giving up."
                    )
                    raise

                if not self._shutdown_requested:
                    logger.warning(f"Will retry connection...")

            finally:
                self.stop()

        logger.info("=" * 70)
        logger.info("Alpaca Redis Ingestion Service stopped")
        logger.info("=" * 70)

    def stop(self) -> None:
        """Stop the ingestion service gracefully."""
        if self.running:
            logger.info("Stopping ingestion service...")
            self.running = False

            try:
                if self.stream:
                    self.stream.stop()
                    logger.info("Alpaca WebSocket stream stopped")

            except Exception as e:
                logger.error(f"Error during shutdown: {e}", exc_info=True)

    def get_status(self) -> dict:
        """Get current status of the ingestion service.

        Returns:
            dict: Status information including symbols, running state, etc.
        """
        return {
            "running": self.running,
            "symbols": self.symbols,
            "feed": self.feed.value,
            "shutdown_requested": self._shutdown_requested,
            "publisher": str(self.publisher),
        }

    def __repr__(self) -> str:
        """String representation of ingestion service."""
        return (
            f"AlpacaRedisIngestion("
            f"symbols={self.symbols}, "
            f"feed={self.feed.value}, "
            f"running={self.running})"
        )


if __name__ == "__main__":
    """Run the ingestion service as a standalone daemon."""
    import sys

    print("=" * 70)
    print("Alpaca to Redis Stream Ingestion Service")
    print("=" * 70)
    print()

    try:
        # Initialize ingestion service
        logger.info("Initializing ingestion service...")
        ingestion = AlpacaRedisIngestion()

        logger.info(f"Service configuration: {ingestion}")
        logger.info("Press Ctrl+C to stop the service")
        print()

        # Run service (blocking call - will run until Ctrl+C or error)
        ingestion.run()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"\n✗ Configuration error: {e}")
        print("\nPlease check:")
        print("1. Alpaca API credentials in config/secret.json")
        print("2. Enabled symbols in config.json watchlist")
        print("3. Redis configuration in config.json")
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt - shutting down gracefully")
        print("\n\nShutting down gracefully...")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n✗ Fatal error: {e}")
        sys.exit(1)

    finally:
        print("\n" + "=" * 70)
        print("Service stopped")
        print("=" * 70)
