"""Tool functions for Quant Analyst DeepAgent.

Provides custom tools for the agent to access data:
- fetch_recent_bars: Get market data from AlpacaDAO
- get_fundamentals: Get company overview from AlphaVantageDAO
- save_eod_to_db: Save EOD summary to AnalystDAO

Note: 30-min summaries use deepagents' built-in file tools (write_file, read_file, ls).
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import subprocess
import concurrent.futures
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.tools import tool

from src.common.dao import AlpacaDAO, AlphaVantageDAO, AnalystDAO, StrategyDAO
from src.common.utils import get_logger

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

    USE WHEN: you need raw OHLCV price/volume data for custom calculations not
    covered by precomputed indicators.
    DO NOT USE WHEN: precomputed indicators are available (use get_precomputed_indicators
    first — it's 5-10x faster and already includes derived signals).

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
def get_precomputed_indicators(symbol: str, minutes: int = 30) -> str:
    """Fetch pre-computed technical indicators from ETL pipeline.

    USE WHEN: ALWAYS call this first for any technical analysis request — it returns MACD,
    RSI, Bollinger Bands, OBV, Z-Score in one call. 5-10x faster than individual skill scripts.
    DO NOT USE WHEN: user explicitly requests a custom indicator period (e.g., RSI period=10)
    or if this returns "No precomputed indicators available" — then use run_quant_batch instead.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        minutes: Number of minutes of historical indicators (default 30)

    Returns:
        Markdown table with indicator values and signals, or error message
    """
    logger.info(f"[TOOL] Calling: get_precomputed_indicators")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'minutes': minutes}, indent=2)}")

    try:
        dao = get_alpaca_dao()
        end = datetime.now()
        start = end - timedelta(minutes=minutes)

        # Fetch precomputed indicators from database
        indicators = dao.get_computed_indicators(
            symbol=symbol,
            start=start,
            end=end,
            timeframe='1Min'
        )

        if indicators.empty:
            output = f"No precomputed indicators available for {symbol}. ETL may not have run yet or insufficient data (need 60+ bars)."
            logger.info(f"[TOOL] Output: {output}")
            return output

        # Get latest row for current signals
        latest = indicators.iloc[-1]

        # Format as Markdown table
        output = f"# Technical Indicators for {symbol}\n\n"
        output += f"**Timestamp:** {latest['timestamp']}\n"
        output += f"**Data Points:** {len(indicators)} bars ({minutes} minutes)\n\n"
        output += "| Indicator | Value | Signal |\n"
        output += "|-----------|-------|--------|\n"

        # MACD (Momentum)
        if pd.notna(latest.get('macd_value')):
            macd_val = latest['macd_value']
            macd_sig = latest.get('macd_signal', 0)
            signal = "🔼 Bullish" if macd_val > macd_sig else "🔽 Bearish"
            output += f"| MACD Value | {macd_val:.4f} | {signal} |\n"
            output += f"| MACD Signal | {macd_sig:.4f} | — |\n"
            output += f"| MACD Histogram | {latest.get('macd_histogram', 0):.4f} | — |\n"

        # RSI (Momentum)
        if pd.notna(latest.get('rsi')):
            rsi = latest['rsi']
            if rsi > 70:
                signal = "⚠️ Overbought"
            elif rsi < 30:
                signal = "📉 Oversold"
            else:
                signal = "✅ Neutral"
            output += f"| RSI | {rsi:.2f} | {signal} |\n"

        # Bollinger Bands (Volatility)
        if pd.notna(latest.get('bb_middle')):
            output += f"| BB Upper | {latest['bb_upper']:.2f} | Resistance |\n"
            output += f"| BB Middle (SMA) | {latest['bb_middle']:.2f} | Current Trend |\n"
            output += f"| BB Lower | {latest['bb_lower']:.2f} | Support |\n"
            bb_bandwidth = latest.get('bb_bandwidth', 0)
            bw_signal = "Wide (High Vol)" if bb_bandwidth > 2 else "Narrow (Low Vol)" if bb_bandwidth < 1 else "Normal"
            output += f"| BB Bandwidth | {bb_bandwidth:.2f}% | {bw_signal} |\n"

        # OBV (Volume)
        if pd.notna(latest.get('obv')):
            obv_trend = latest.get('volume_trend', 'N/A')
            trend_emoji = "📈" if obv_trend == "increasing" else "📉" if obv_trend == "decreasing" else "➡️"
            output += f"| OBV | {latest['obv']:,.0f} | {trend_emoji} {obv_trend.title()} |\n"

            # Volume comparison
            if pd.notna(latest.get('current_vs_avg')):
                vol_ratio = latest['current_vs_avg']
                vol_signal = "High Volume" if vol_ratio > 1.5 else "Low Volume" if vol_ratio < 0.5 else "Normal"
                output += f"| Volume vs Avg | {vol_ratio:.2f}x | {vol_signal} |\n"

        # Mean Reversion indicators
        if pd.notna(latest.get('z_score')):
            z_score = latest['z_score']
            if z_score > 2:
                z_signal = "Extremely Overbought"
            elif z_score > 1:
                z_signal = "Overbought"
            elif z_score < -2:
                z_signal = "Extremely Oversold"
            elif z_score < -1:
                z_signal = "Oversold"
            else:
                z_signal = "Normal Range"
            output += f"| Z-Score | {z_score:.2f} | {z_signal} |\n"

        if pd.notna(latest.get('percentile')):
            percentile = latest['percentile']
            perc_signal = "Top 20%" if percentile > 80 else "Bottom 20%" if percentile < 20 else "Mid Range"
            output += f"| Percentile | {percentile:.1f}% | {perc_signal} |\n"

        if pd.notna(latest.get('vwap')):
            output += f"| VWAP | {latest['vwap']:.2f} | Price Anchor |\n"

        output += "\n**Source:** Pre-computed ETL pipeline (fast lookup)\n"

        logger.info(f"[TOOL] Output: {len(indicators)} indicators formatted as Markdown ({len(output)} chars)")

        return output

    except Exception as e:
        error_msg = f"Error fetching precomputed indicators: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        return error_msg


@tool
def get_company_fundamentals(symbol: str) -> str:
    """Get company fundamentals for valuation.

    USE WHEN: user asks about P/E ratio, intrinsic value, sector, market cap, Graham
    valuation, or needs fundamental context for a buy/sell thesis.
    DO NOT USE WHEN: user wants price/volume technical analysis — use get_precomputed_indicators
    or run_quant_batch instead.

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

    USE WHEN: completing an end-of-day analysis session and need to persist the summary
    for historical tracking.
    DO NOT USE WHEN: this is an intraday or on-demand query — only save at EOD or when
    user explicitly requests saving.

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

    USE WHEN: after successfully running a strategy calculation (mean-reversion, momentum,
    etc.) and the user wants results persisted for historical analysis.
    DO NOT USE WHEN: strategy calculation has not yet completed — always save after,
    not before, getting results.

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


# =============================================================================
# Batch Execution Tool
# =============================================================================

# Skill name → relative script path from project root
_SKILL_SCRIPTS: Dict[str, str] = {
    "momentum": "src/agentic/agents/quant/skills/momentum-indicators/momentum.py",
    "volatility": "src/agentic/agents/quant/skills/volatility-indicators/volatility.py",
    "volume": "src/agentic/agents/quant/skills/volume-indicators/volume.py",
    "candlestick": "src/agentic/agents/quant/skills/candlestick-patterns/candles.py",
    "mean-reversion": "src/agentic/agents/quant/skills/mean-reversion-strategy/mean_reversion.py",
}


def _run_skill(skill_name: str, symbol: str, lookback: int) -> Dict:
    """Run a single quant skill script and return its JSON output.

    Args:
        skill_name: Key from _SKILL_SCRIPTS.
        symbol: Stock ticker.
        lookback: Lookback period in minutes.

    Returns:
        Dict with skill result or error key.
    """
    script = _SKILL_SCRIPTS.get(skill_name)
    if not script:
        return {"error": f"Unknown skill: {skill_name}"}

    root = Path(__file__).parent.parent.parent.parent
    script_path = root / script

    if not script_path.exists():
        return {"error": f"Skill script not found: {script_path}"}

    try:
        cmd = [
            "python", str(script_path),
            "--symbol", symbol,
            "--lookback", str(lookback)
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "Non-zero exit code"}
        return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"error": f"Skill '{skill_name}' timed out after 60s"}
    except json.JSONDecodeError as e:
        return {"error": f"Skill '{skill_name}' returned non-JSON output: {e}"}
    except Exception as e:
        return {"error": str(e)}


@tool
def run_quant_batch(symbol: str, skills: List[str], lookback: int = 30) -> str:
    """Run multiple quant indicator skills in parallel and return a combined analysis.

    USE WHEN: User wants comprehensive technical analysis or multiple indicators at once.
    Examples: "full analysis of AAPL", "run all indicators on TSLA",
    "compare momentum and volatility for MSFT", "give me a complete technical picture".

    DO NOT USE WHEN: User requests exactly one specific indicator — call that skill directly
    or use get_precomputed_indicators for a single-pass lookup.

    Skills run concurrently via ThreadPoolExecutor; each calls its own Python script
    internally, so this counts as 1 execution action toward the per-turn limit regardless
    of how many skills are requested.

    Args:
        symbol: Stock ticker (e.g., "AAPL").
        skills: List of skill names to run. Valid values:
            "momentum"        — MACD, RSI
            "volatility"      — Bollinger Bands, ATR
            "volume"          — OBV, volume flow
            "candlestick"     — Doji, hammer, engulfing patterns
            "mean-reversion"  — Z-score, mean reversion signals
            Use ["all"] to run all 5 skills.
        lookback: Minutes of historical data to analyse (default: 30).

    Returns:
        JSON string keyed by skill name. Each value is the skill's result dict,
        or {"error": "..."} if that skill failed.

    Example:
        run_quant_batch.invoke({"symbol": "AAPL", "skills": ["momentum", "volatility"]})
    """
    logger.info(f"[TOOL] Calling: run_quant_batch(symbol={symbol}, skills={skills}, lookback={lookback})")

    requested = list(_SKILL_SCRIPTS.keys()) if skills == ["all"] else skills
    unknown = [s for s in requested if s not in _SKILL_SCRIPTS]
    if unknown:
        return json.dumps({"error": f"Unknown skills: {unknown}. Valid: {list(_SKILL_SCRIPTS.keys())}"})

    results: Dict[str, Dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requested)) as pool:
        futures = {pool.submit(_run_skill, name, symbol, lookback): name for name in requested}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {"error": str(e)}

    output = json.dumps({"symbol": symbol, "lookback_minutes": lookback, "results": results}, indent=2, default=str)
    logger.info(f"[TOOL] run_quant_batch completed: {list(results.keys())} for {symbol}")
    return output


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
