"""Tool functions for Quant Analyst DeepAgent.

Provides custom tools for the agent to access data:
- fetch_recent_bars: Get market data from AlpacaDAO
- get_fundamentals: Get company overview from AlphaVantageDAO
- save_eod_to_db: Save EOD summary to AnalystDAO

Note: 30-min summaries use deepagents' built-in file tools (write_file, read_file, ls).
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional

from langchain_core.tools import tool

from src.dao import AlpacaDAO, AlphaVantageDAO, AnalystDAO, StrategyDAO
from src.utils import get_logger

logger = get_logger(__name__)

# DAOs (singleton pattern)
_alpaca_dao = None
_av_dao = None
_analyst_dao = None
_strategy_dao = None


def get_alpaca_dao() -> AlpacaDAO:
    """Get or create AlpacaDAO instance."""
    global _alpaca_dao
    if _alpaca_dao is None:
        _alpaca_dao = AlpacaDAO()
    return _alpaca_dao


def get_av_dao() -> AlphaVantageDAO:
    """Get or create AlphaVantageDAO instance."""
    global _av_dao
    if _av_dao is None:
        _av_dao = AlphaVantageDAO()
    return _av_dao


def get_analyst_dao() -> AnalystDAO:
    """Get or create AnalystDAO instance."""
    global _analyst_dao
    if _analyst_dao is None:
        _analyst_dao = AnalystDAO()
    return _analyst_dao


@tool
def get_market_bars(symbol: str, minutes: int = 30) -> str:
    """Fetch recent market bars for analysis.

    Tool for agent to get latest market data from database.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        minutes: Number of minutes of 1-min bars to fetch (default 30)

    Returns:
        JSON string with OHLCV data or error message
    """
    # Log tool invocation
    logger.info(f"[TOOL] Calling: get_market_bars")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'minutes': minutes}, indent=2)}")

    try:
        dao = get_alpaca_dao()
        end = datetime.now()
        start = end - timedelta(minutes=minutes)

        bars = dao.get_bars(symbol, start=start, end=end, timeframe='1Min')
        logger.info(f"Fetched {len(bars)} bars for {symbol} (last {minutes} minutes)")

        if bars.empty:
            output = f"No data available for {symbol}"
            logger.info(f"[TOOL] Output: {output}")
            return output

        # Convert to JSON for agent
        result = {
            "symbol": symbol,
            "bars": len(bars),
            "data": bars.to_dict(orient="records"),
            "latest_close": float(bars['close'].iloc[-1]),
            "time_range": f"{bars.index[0]} to {bars.index[-1]}"
        }
        output = json.dumps(result, indent=2, default=str)

        # Log truncated output
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")

        return output
    except Exception as e:
        error_msg = f"Error fetching bars: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        return error_msg


@tool
def get_company_fundamentals(symbol: str) -> str:
    """Get company fundamentals for valuation.

    Tool for agent to access fundamental data from database.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')

    Returns:
        JSON string with company overview or error message
    """
    # Log tool invocation
    logger.info(f"[TOOL] Calling: get_company_fundamentals")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol}, indent=2)}")

    try:
        dao = get_av_dao()
        overview = dao.get_company_overview(symbol)

        if overview is None or not overview:
            output = f"No fundamental data available for {symbol}"
            logger.info(f"[TOOL] Output: {output}")
            return output

        logger.info(f"Retrieved fundamentals for {symbol}: {overview.get('name', 'N/A')}")

        output = json.dumps(overview, indent=2, default=str)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")

        return output
    except Exception as e:
        error_msg = f"Error fetching fundamentals: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        return error_msg


@tool
def save_eod_summary(
    symbol: str,
    indicators: str,
    summary_text: str,
    signals: str,
    thought_trace: str = "",
    model_used: str = "gpt-4"
) -> str:
    """Save end-of-day analysis summary to database.

    Tool for agent to persist EOD summary to AnalystDAO.

    Args:
        symbol: Stock ticker
        indicators: JSON string of calculated indicator values (MACD, RSI, Bollinger, etc.)
        summary_text: LLM-generated comprehensive daily analysis
        signals: JSON string of signals dict (momentum, volatility, volume_trend)
        thought_trace: Agent's reasoning and decision process
        model_used: LLM model identifier (default 'gpt-4')

    Returns:
        Success or error message
    """
    # Log tool invocation
    logger.info(f"[TOOL] Calling: save_eod_summary")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'model_used': model_used, 'summary_preview': summary_text[:100]}, indent=2, default=str)}")

    try:
        # Parse JSON strings
        indicators_dict = json.loads(indicators) if isinstance(indicators, str) else indicators
        signals_dict = json.loads(signals) if isinstance(signals, str) else signals

        dao = get_analyst_dao()
        timestamp = datetime.now()
        dao.save_eod_summary(
            symbol=symbol,
            timestamp=timestamp,
            indicators=indicators_dict,
            summary_text=summary_text,
            signals=signals_dict,
            thought_trace=thought_trace,
            model_used=model_used,
            token_count=None  # Will be filled by callback if available
        )
        logger.info(f"Saved EOD summary for {symbol} to database")

        output = "EOD summary saved successfully"
        logger.info(f"[TOOL] Output: {output}")
        return output
    except Exception as e:
        error_msg = f"Error saving EOD summary: {e}"
        logger.error(f"[TOOL] Error: {error_msg}", exc_info=True)
        return error_msg


def get_strategy_dao() -> StrategyDAO:
    """Get or create singleton StrategyDAO instance."""
    global _strategy_dao
    if _strategy_dao is None:
        _strategy_dao = StrategyDAO()
    return _strategy_dao


@tool
def save_strategy_result_tool(
    symbol: str,
    strategy_name: str,
    result_json: str,
    thought_trace: str = "",
    model_used: str = "gpt-4"
) -> str:
    """Save trading strategy result to database.

    Args:
        symbol: Stock ticker symbol
        strategy_name: Name of strategy (e.g., 'mean-reversion')
        result_json: JSON string of complete strategy result
        thought_trace: Agent's reasoning process
        model_used: LLM model identifier

    Returns:
        Success or error message
    """
    # Log tool invocation
    logger.info(f"[TOOL] Calling: save_strategy_result_tool")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'strategy_name': strategy_name, 'model_used': model_used}, indent=2)}")

    try:
        # Parse JSON string
        result_data = json.loads(result_json) if isinstance(result_json, str) else result_json

        dao = get_strategy_dao()
        # Extract data from result_data
        dao.save_strategy_result(
            symbol=symbol,
            strategy_name=strategy_name,
            current_price=result_data.get('current_price', 0),
            statistics=result_data.get('statistics', {}),
            indicators=result_data.get('moving_averages', {}),
            signals=result_data.get('signals', {}),
            action=result_data.get('trade_recommendation', {}).get('action', 'hold'),
            confidence=result_data.get('trade_recommendation', {}).get('confidence', 0.0),
            reason=result_data.get('trade_recommendation', {}).get('reason', ''),
            entry_price=result_data.get('trade_recommendation', {}).get('entry_price'),
            stop_loss=result_data.get('trade_recommendation', {}).get('stop_loss'),
            take_profit=result_data.get('trade_recommendation', {}).get('take_profit'),
            support_level=result_data.get('levels', {}).get('support'),
            resistance_level=result_data.get('levels', {}).get('resistance'),
            current_state=result_data.get('signals', {}).get('current_state'),
            thought_trace=thought_trace,
            model_used=model_used,
            parameters=result_data.get('parameters', {}),
            timeframe=result_data.get('parameters', {}).get('timeframe', '1Day')
        )
        logger.info(f"Saved {strategy_name} result for {symbol} to database")

        output = "Strategy result saved successfully"
        logger.info(f"[TOOL] Output: {output}")
        return output
    except Exception as e:
        error_msg = f"Error saving strategy result: {e}"
        logger.error(f"[TOOL] Error: {error_msg}", exc_info=True)
        return error_msg


if __name__ == "__main__":
    """Test tools with sample data."""
    print("="*60)
    print("Testing Quant Agent Tools")
    print("="*60)

    # Test 1: Fetch recent bars
    print("\n[1/3] Testing get_market_bars...")
    try:
        bars = get_market_bars("AAPL", minutes=30)
        print(f"OK: Fetched {len(bars)} bars")
        if not bars.empty:
            print(f"  Latest close: ${bars['close'].iloc[-1]:.2f}")
            print(f"  Time range: {bars.index[0]} to {bars.index[-1]}")
    except Exception as e:
        print(f"Note: {e} (This is expected if no data in database yet)")

    # Test 2: Get fundamentals
    print("\n[2/3] Testing get_company_fundamentals...")
    try:
        fundamentals = get_company_fundamentals("AAPL")
        if fundamentals:
            print(f"OK: Retrieved fundamentals")
            print(f"  Company: {fundamentals.get('name', 'N/A')}")
            print(f"  Sector: {fundamentals.get('sector', 'N/A')}")
            print(f"  Market Cap: {fundamentals.get('market_capitalization', 'N/A')}")
        else:
            print("Note: No fundamentals found (expected if not populated yet)")
    except Exception as e:
        print(f"Note: {e}")

    # Test 3: Save EOD to database
    print("\n[3/3] Testing save_eod_to_db...")
    test_indicators = {
        'rsi': 65.3,
        'macd': {'value': 0.52, 'signal': 0.48, 'histogram': 0.04}
    }
    test_signals = {
        'momentum': 'bullish',
        'volatility': 'normal'
    }

    success = save_eod_summary(
        symbol='TEST',
        indicators=test_indicators,
        summary_text='Test EOD summary for tool verification',
        signals=test_signals,
        thought_trace='Testing save_eod_summary tool'
    )

    if success:
        print("OK: EOD summary saved successfully")
    else:
        print("FAILED: Could not save EOD summary")

    print("\n" + "="*60)
    print("Tool tests complete!")
    print("="*60)

    # Cleanup
    if _alpaca_dao:
        _alpaca_dao.close()
    if _av_dao:
        _av_dao.close()
    if _analyst_dao:
        _analyst_dao.close()
