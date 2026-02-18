"""Top-level coordinator for multi-symbol data gathering and streaming.

This module provides comprehensive data coordination for the portfolio manager:
- Initializes watchlist symbols
- Fetches ALL historical market data (bars, trades)
- Fetches ALL fundamental data (overview, dividends, earnings, financials)
- Starts real-time streaming for all symbols
- Coordinates data persistence via DAOs
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import signal
import time
from typing import List
from datetime import datetime, timedelta
from src.skills.alpaca_skills import fetch_historical_bars, fetch_historical_trades
from src.skills.alpha_vantage_skills import (
    fetch_company_overview,
    fetch_dividend_history,
    fetch_earnings_history,
    fetch_income_statement,
    fetch_balance_sheet,
    fetch_cash_flow
)
from src.dao import AlpacaDAO, AlphaVantageDAO
from src.data_gatherer.alpaca_stream import AlpacaDataStreamer, default_trade_handler, default_bar_handler
from src.utils import get_logger, config


# Initialize logger
logger = get_logger(__name__)


class DataCoordinator:
    """Top-level coordinator for multi-symbol data gathering and streaming.

    Responsibilities:
    1. Initialize watchlist symbols
    2. Fetch ALL historical market data (bars, trades)
    3. Fetch ALL fundamental data (overview, dividends, earnings, financials)
    4. Start real-time streaming for all symbols
    5. Coordinate data persistence via DAOs
    """

    def __init__(self, symbols: List[str] = None):
        """Initialize coordinator.

        Args:
            symbols: List of symbols to track. If None, loads from config watchlist.
        """
        if symbols is None:
            symbols = config.get("watchlist", default=["AAPL"])

        self.symbols = [s.upper() for s in symbols]
        self.alpaca_dao = AlpacaDAO()
        self.av_dao = AlphaVantageDAO()
        self.streamers = {}  # symbol -> streamer mapping
        self.stream_tasks = []  # Track async tasks

        logger.info(f"DataCoordinator initialized with {len(self.symbols)} symbols: {self.symbols}")

    def fetch_historical_market_data(self, symbol: str, days_back: int = 30):
        """Fetch ALL historical market data for a symbol.

        Fetches:
        - Daily bars (last N days)
        - Intraday 1-hour bars (last 7 days)
        - Intraday 1-minute bars (last 2 days)
        - Historical trades (last 1 day)

        All data automatically saved to database.

        Args:
            symbol: Stock ticker
            days_back: Number of days of historical data to fetch
        """
        logger.info(f"Fetching historical market data for {symbol}...")

        end = datetime.now()
        start_daily = end - timedelta(days=days_back)
        start_minute = end - timedelta(days=days_back)
        start_trades = end - timedelta(days=days_back)

        try:
            # Daily bars
            logger.info(f"  Fetching daily bars ({days_back} days)...")
            daily_bars = fetch_historical_bars(
                symbol,
                start=start_daily.isoformat(),
                end=end.isoformat(),
                timeframe="1Day"
            )
            logger.info(f"  ✓ Fetched {len(daily_bars)} daily bars")

            # 1-minute bars
            logger.info(f"  Fetching 1-minute bars ({days_back} days)...")
            minute_bars = fetch_historical_bars(
                symbol,
                start=start_minute.isoformat(),
                end=end.isoformat(),
                timeframe="1Min"
            )
            logger.info(f"  ✓ Fetched {len(minute_bars)} 1-minute bars")

            # Historical trades
            logger.info(f"  Fetching historical trades ({days_back} days)...")
            trades = fetch_historical_trades(
                symbol,
                start=start_trades.isoformat(),
                end=end.isoformat(),
                limit=100000
            )
            logger.info(f"  ✓ Fetched {len(trades)} trades")

            logger.info(f"✓ Historical market data for {symbol} complete")

        except Exception as e:
            logger.error(f"Failed to fetch historical market data for {symbol}: {e}", exc_info=True)

    def fetch_all_fundamentals(self, symbol: str):
        """Fetch ALL fundamental data for a symbol.

        Fetches:
        - Company overview
        - Dividend history
        - Quarterly earnings
        - Annual earnings
        - Annual income statements
        - Quarterly income statements
        - Annual balance sheets
        - Quarterly balance sheets
        - Annual cash flows
        - Quarterly cash flows

        All data automatically saved to database.

        Args:
            symbol: Stock ticker
        """
        logger.info(f"Fetching ALL fundamental data for {symbol}...")

        try:
            # Company Overview
            logger.info(f"  Fetching company overview...")
            overview = fetch_company_overview(symbol)
            logger.info(f"  ✓ Company: {overview.get('Name', 'N/A')}")

            # Dividends
            logger.info(f"  Fetching dividend history...")
            dividends = fetch_dividend_history(symbol)
            logger.info(f"  ✓ Fetched {len(dividends)} dividend records")

            # Earnings - Annual
            logger.info(f"  Fetching annual earnings...")
            earnings_a = fetch_earnings_history(symbol, quarterly=False)
            logger.info(f"  ✓ Fetched {len(earnings_a)} annual earnings records")

            # Income Statements - Annual
            logger.info(f"  Fetching annual income statements...")
            income_a = fetch_income_statement(symbol, quarterly=False)
            logger.info(f"  ✓ Fetched {len(income_a)} annual income statements")

            # Balance Sheets - Annual
            logger.info(f"  Fetching annual balance sheets...")
            balance_a = fetch_balance_sheet(symbol, quarterly=False)
            logger.info(f"  ✓ Fetched {len(balance_a)} annual balance sheets")

            # Cash Flows - Annual
            logger.info(f"  Fetching annual cash flows...")
            cash_a = fetch_cash_flow(symbol, quarterly=False)
            logger.info(f"  ✓ Fetched {len(cash_a)} annual cash flows")

            logger.info(f"✓ ALL fundamental data for {symbol} complete")

        except Exception as e:
            logger.error(f"Failed to fetch fundamentals for {symbol}: {e}", exc_info=True)

    async def initialize_symbol(self, symbol: str, days_back: int = 30):
        """Initialize a symbol with ALL available data.

        Steps:
        1. Add to watchlist
        2. Fetch ALL historical market data
        3. Fetch ALL fundamental data
        4. Start real-time streaming

        Args:
            symbol: Stock ticker
        """
        logger.info("="*60)
        logger.info(f"Initializing {symbol}...")
        logger.info("="*60)

        # Add to watchlist
        self.alpaca_dao.add_to_watchlist(symbol, notes="Auto-added by DataCoordinator")

        # Fetch ALL historical market data
        self.fetch_historical_market_data(symbol, days_back=days_back)

        # Fetch ALL fundamental data
        self.fetch_all_fundamentals(symbol)

        logger.info(f"✓✓ {symbol} initialization complete ✓✓")

    async def start_streaming(self, symbol: str):
        """Start real-time streaming for a symbol.

        Args:
            symbol: Stock ticker
        """
        logger.info(f"Starting real-time stream for {symbol}...")

        streamer = AlpacaDataStreamer(symbol=symbol)
        # Use default handlers that auto-save to DB
        streamer.subscribe_trades(default_trade_handler)
        streamer.subscribe_bars(default_bar_handler)

        self.streamers[symbol] = streamer

        # Run streamer in background thread and store task
        task = asyncio.create_task(asyncio.to_thread(streamer.run))
        self.stream_tasks.append(task)
        logger.info(f"✓ Real-time stream started for {symbol}")

    async def run_all(self):
        """Initialize ALL symbols and start streaming for all.

        This is the main entry point to:
        1. Fetch ALL historical data for all symbols
        2. Fetch ALL fundamental data for all symbols
        3. Start real-time streaming for all symbols
        """
        logger.info("="*60)
        logger.info(f"DataCoordinator: Initializing {len(self.symbols)} symbols...")
        logger.info("="*60)

        # Initialize each symbol sequentially (to respect rate limits)
        for symbol in self.symbols:
            await self.initialize_symbol(symbol, days_back=30)

            # Small delay between symbols to respect API rate limits
            await asyncio.sleep(2)

        # Start streaming for all symbols
        logger.info("\n" + "="*60)
        logger.info("Starting real-time streaming for all symbols...")
        logger.info("="*60)

        for symbol in self.symbols:
            await self.start_streaming(symbol)

        logger.info("\n✓✓✓ DataCoordinator: All symbols initialized and streaming ✓✓✓\n")

    async def run_streaming_loop(self, shutdown_flag):
        """Keep the event loop running while streams are active.

        Args:
            shutdown_flag: List with single boolean value [False] for shutdown control
        """
        logger.info("Streaming loop started. Streams are now active...")

        try:
            # Keep running until shutdown requested
            while not shutdown_flag[0]:
                await asyncio.sleep(1)  # Check every second

                # Check if any stream tasks have failed
                for task in self.stream_tasks:
                    if task.done() and task.exception():
                        logger.error(f"Stream task failed: {task.exception()}")

        except asyncio.CancelledError:
            logger.info("Streaming loop cancelled")
        except Exception as e:
            logger.error(f"Error in streaming loop: {e}", exc_info=True)

    def stop_all_streaming(self):
        """Stop all active streams."""
        for symbol, streamer in self.streamers.items():
            logger.info(f"Stopping stream for {symbol}...")
            streamer.stop()

        logger.info("All streams stopped")


if __name__ == "__main__":
    """Run the coordinator."""
    import sys

    # Graceful shutdown flag (using list for mutability in nested function)
    shutdown_requested = [False]

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        shutdown_requested[0] = True

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Get symbols from command line or use config
    if len(sys.argv) > 1:
        symbols = sys.argv[1].split(',')
    else:
        symbols = config.get("watchlist", default=["IBM"])

    # Create coordinator
    coordinator = DataCoordinator(symbols=symbols)

    async def main():
        """Main async function to run coordinator."""
        try:
            # Initialize all symbols and start streaming
            await coordinator.run_all()

            # Keep the event loop running while streams are active
            await coordinator.run_streaming_loop(shutdown_requested)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Error in coordinator: {e}", exc_info=True)
        finally:
            logger.info("Shutting down...")
            coordinator.stop_all_streaming()
            logger.info("Coordinator stopped. Goodbye!")

    # Run the async main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown complete")
