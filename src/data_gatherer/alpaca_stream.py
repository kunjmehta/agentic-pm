"""Alpaca Data Streamer using alpaca-py SDK.

This module provides a wrapper around Alpaca's StockDataStream for real-time
market data streaming (trades, bars, trade status) with retry logic
and graceful shutdown.

Based on: https://alpaca.markets/sdks/python/api_reference/data/stock/live.html
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import signal
import time
import threading
from typing import Optional, Callable
from alpaca.data.live.stock import StockDataStream
from alpaca.data.enums import DataFeed
from src.utils import secrets, get_logger
from src.data_gatherer.db_stream_handlers import (
    combined_trade_handler,
    combined_bar_handler
)


# Initialize logger
logger = get_logger(__name__)


class AlpacaDataStreamer:
    """Real-time stock data streamer using Alpaca SDK.

    Wraps Alpaca's StockDataStream with simplified interface, retry logic,
    and graceful shutdown handling.

    Example:
        >>> async def on_trade(trade):
        ...     print(f"Trade: {trade.symbol} @ {trade.price}")
        >>>
        >>> streamer = AlpacaDataStreamer(symbol="AAPL")
        >>> streamer.subscribe_trades(on_trade)
        >>> streamer.run()
    """

    def __init__(
        self,
        symbol: str,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: str = "iex",
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        """Initialize the Alpaca data streamer for a single symbol.

        Args:
            symbol: Stock ticker to stream (e.g., "AAPL")
            api_key: Alpaca API key (loads from config/secret.json if not provided)
            secret_key: Alpaca secret key (loads from config/secret.json if not provided)
            feed: Data feed to use - "iex" (default: "iex")
            max_retries: Maximum connection retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 5)
        """
        # Load credentials
        if api_key is None or secret_key is None:
            self.api_key = secrets.get("alpaca.api_key")
            self.secret_key = secrets.get("alpaca.secret_key")
        else:
            self.api_key = api_key
            self.secret_key = secret_key

        # Configuration
        self.symbol = symbol.upper()
        self.feed = DataFeed.IEX
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Handlers
        self._trade_handler = None
        self._bar_handler = None
        self._status_handler = None

        # State
        self.running = False
        self._shutdown_requested = False

        # Initialize stream (will be recreated on each retry)
        self._create_stream()

    def _create_stream(self) -> None:
        """Create a new StockDataStream instance."""
        self.stream = StockDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            feed=self.feed
        )

    def subscribe_trades(self, handler: Callable) -> None:
        """Subscribe to trade data for the configured symbol.

        Args:
            handler: Async function to call with trade data
                    Signature: async def handler(trade) -> None
                    trade object has: symbol, price, size, timestamp, exchange, etc.
        """
        self._trade_handler = handler
        self.stream.subscribe_trades(handler, self.symbol)
        logger.info(f"Subscribed to trades for {self.symbol}")

    def subscribe_bars(self, handler: Callable) -> None:
        """Subscribe to bar data for the configured symbol.

        Args:
            handler: Async function to call with bar data
                    Signature: async def handler(bar) -> None
                    bar object has: symbol, open, high, low, close, volume, timestamp, etc.
        """
        self._bar_handler = handler
        self.stream.subscribe_bars(handler, self.symbol)
        logger.info(f"Subscribed to bars for {self.symbol}")

    def subscribe_statuses(self, handler: Callable) -> None:
        """Subscribe to trading status updates for the configured symbol.

        Args:
            handler: Async function to call with status data
                    Signature: async def handler(status) -> None
                    status object has: symbol, status_code, status_message, etc.
        """
        self._status_handler = handler
        self.stream.subscribe_trading_statuses(handler, self.symbol)
        logger.info(f"Subscribed to trade statuses for {self.symbol}")

    def unsubscribe_trades(self) -> None:
        """Unsubscribe from trade data."""
        self.stream.unsubscribe_trades(self.symbol)
        self._trade_handler = None
        logger.info(f"Unsubscribed from trades for {self.symbol}")

    def unsubscribe_bars(self) -> None:
        """Unsubscribe from bar data."""
        self.stream.unsubscribe_bars(self.symbol)
        self._bar_handler = None
        logger.info(f"Unsubscribed from bars for {self.symbol}")

    def unsubscribe_statuses(self) -> None:
        """Unsubscribe from status updates."""
        self.stream.unsubscribe_trading_statuses(self.symbol)
        self._status_handler = None
        logger.info(f"Unsubscribed from trade statuses for {self.symbol}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown.

        Note: Signal handlers can only be set up in the main thread.
        When running in a background thread (e.g., via asyncio.to_thread),
        this method will skip signal handler setup.
        """
        # Check if we're in the main thread
        if threading.current_thread() is not threading.main_thread():
            logger.debug("Skipping signal handler setup (not in main thread)")
            return

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
            self._shutdown_requested = True
            self.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run(self) -> None:
        """Run the stream with retry logic and graceful shutdown.

        This method will:
        1. Attempt to connect with retry logic
        2. Run the stream until interrupted or error (blocking)
        3. Gracefully shutdown on SIGINT/SIGTERM
        4. Retry on connection failures (up to max_retries)

        Raises:
            Exception: If all retry attempts fail
        """
        self._setup_signal_handlers()

        retry_count = 0
        while retry_count < self.max_retries and not self._shutdown_requested:
            try:
                logger.info("="*60)
                logger.info(f"Starting Alpaca stream for {self.symbol} (feed: {self.feed.value})")
                logger.info("="*60)

                if retry_count > 0:
                    logger.info(f"Retry attempt {retry_count}/{self.max_retries}")
                    # Recreate stream on retry
                    self._create_stream()
                    # Re-subscribe to channels
                    if self._trade_handler:
                        self.stream.subscribe_trades(self._trade_handler, self.symbol)
                    if self._bar_handler:
                        self.stream.subscribe_bars(self._bar_handler, self.symbol)
                    if self._status_handler:
                        self.stream.subscribe_trading_statuses(self._status_handler, self.symbol)

                self.running = True

                # Run the stream (blocking call until error or stop())
                self.stream.run()

                # If we got here normally, break the retry loop
                break

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self._shutdown_requested = True
                break

            except Exception as e:
                retry_count += 1
                logger.error(f"Stream error: {e}", exc_info=True)

                if retry_count < self.max_retries and not self._shutdown_requested:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                elif retry_count >= self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) reached. Exiting.")
                    raise

            finally:
                self.stop()

        logger.info("="*60)
        logger.info("Stream stopped")
        logger.info("="*60)

    def stop(self) -> None:
        """Stop the stream gracefully."""
        if self.running:
            logger.info("Stopping stream...")
            self.running = False

            try:
                # Stop the WebSocket (this is synchronous)
                self.stream.stop()
                logger.info("Stream stopped successfully")

            except Exception as e:
                logger.error(f"Error during shutdown: {e}", exc_info=True)


# Default handlers for demonstration (now with DB persistence)
async def default_trade_handler(trade):
    """Default handler that prints AND saves trade data to DB."""
    await combined_trade_handler(trade)


async def default_bar_handler(bar):
    """Default handler that prints AND saves bar data to DB."""
    await combined_bar_handler(bar, timeframe='1Min')


async def default_status_handler(status):
    """Default handler that prints status updates."""
    print(f"[STATUS] {status.symbol} | {status.status_message} "
          f"({status.status_code}) | {status.timestamp}")


if __name__ == "__main__":
    """Test the streamer with a real symbol."""
    import sys

    # Get symbol from command line or use default
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

    # Initialize streamer
    streamer = AlpacaDataStreamer(symbol=symbol)

    # Subscribe to all channels with default handlers
    streamer.subscribe_trades(default_trade_handler)
    streamer.subscribe_bars(default_bar_handler)
    streamer.subscribe_statuses(default_status_handler)

    # Run stream (blocking call - will run until Ctrl+C or error)
    print("Press Ctrl+C to stop the stream")
    try:
        streamer.run()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("\nStream ended")
