"""Quant analysis node for the deterministic LangGraph agent.

Calls skill functions directly (no subprocess). Execution order:
  1. get_precomputed_indicators — ETL pipeline data (fastest)
  2. If empty → fetch bars once, then call each skill function:
       calc_momentum_package, calc_volatility_bands, calc_volume_flow,
       analyze_candle_structure, MeanReversionStrategy.analyze()
  3. Optional: get_company_fundamentals
  4. LLM synthesis → quant_analysis string

Sets state fields: quant_analysis, indicators.
"""

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# ── Precomputed indicators tool ───────────────────────────────────────────────
from src.agentic.agents.quant_tools import get_precomputed_indicators, get_company_fundamentals

from src.common.dao import AlpacaDAO
from src.common.utils import get_logger

# ── Skill modules loaded via importlib (folder names contain hyphens) ─────────
_SKILLS_DIR = project_root / "src" / "agentic" / "agents" / "quant" / "skills"


def _load_skill_module(folder: str, filename: str):
    """Load a skill module from a hyphenated folder name.

    Args:
        folder: Skill folder name (may contain hyphens).
        filename: Python file name inside the folder.

    Returns:
        Loaded module object.
    """
    module_path = _SKILLS_DIR / folder / filename
    spec = importlib.util.spec_from_file_location(
        f"skill_{folder.replace('-', '_')}", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Load skill modules once at import time
try:
    _momentum_mod = _load_skill_module("momentum-indicators", "momentum.py")
    calc_momentum_package = _momentum_mod.calc_momentum_package
except Exception as _e:
    logger.warning(f"[quant_node] momentum module load failed: {_e}")
    calc_momentum_package = None

try:
    _volatility_mod = _load_skill_module("volatility-indicators", "volatility.py")
    calc_volatility_bands = _volatility_mod.calc_volatility_bands
except Exception as _e:
    logger.warning(f"[quant_node] volatility module load failed: {_e}")
    calc_volatility_bands = None

try:
    _volume_mod = _load_skill_module("volume-indicators", "volume.py")
    calc_volume_flow = _volume_mod.calc_volume_flow
except Exception as _e:
    logger.warning(f"[quant_node] volume module load failed: {_e}")
    calc_volume_flow = None

try:
    _candles_mod = _load_skill_module("candlestick-patterns", "candles.py")
    analyze_candle_structure = _candles_mod.analyze_candle_structure
except Exception as _e:
    logger.warning(f"[quant_node] candlestick module load failed: {_e}")
    analyze_candle_structure = None

try:
    _mr_mod = _load_skill_module("mean-reversion-strategy", "mean_reversion.py")
    MeanReversionStrategy = _mr_mod.MeanReversionStrategy
except Exception as _e:
    logger.warning(f"[quant_node] mean-reversion module load failed: {_e}")
    MeanReversionStrategy = None

logger = get_logger(__name__)

logger = get_logger(__name__)


def _to_native(obj):
    """Recursively convert numpy/pandas types to Python native types for msgpack serialization."""
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    return obj


def _fetch_bars(symbol: str, lookback_minutes: int = 60) -> Optional[pd.DataFrame]:
    """Fetch recent OHLCV bars for a symbol from the database.

    Args:
        symbol: Stock ticker.
        lookback_minutes: Number of minutes of 1-min bars to fetch.

    Returns:
        DataFrame with OHLCV data or None if unavailable.
    """
    try:
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(minutes=lookback_minutes)
        df = dao.get_bars(symbol, start=start, end=end, timeframe="1Min")
        dao.close()
        if df.empty:
            logger.warning(f"[quant_node] no bars found for {symbol}")
            return None
        logger.info(f"[quant_node] fetched {len(df)} bars for {symbol}")
        return df
    except Exception as exc:
        logger.warning(f"[quant_node] bar fetch failed: {exc}")
        return None


def _run_skill_functions(symbol: str, df: pd.DataFrame) -> dict:
    """Call each quant skill function on the bar DataFrame.

    Args:
        symbol: Stock ticker.
        df: OHLCV DataFrame.

    Returns:
        Dict with results from each skill function.
    """
    results = {}

    # Momentum: MACD + RSI
    if calc_momentum_package:
        try:
            results["momentum"] = calc_momentum_package(df)
            logger.info("[quant_node] momentum calculated")
        except Exception as exc:
            logger.warning(f"[quant_node] momentum failed: {exc}")

    # Volatility: Bollinger Bands
    if calc_volatility_bands:
        try:
            results["volatility"] = calc_volatility_bands(df)
            logger.info("[quant_node] volatility calculated")
        except Exception as exc:
            logger.warning(f"[quant_node] volatility failed: {exc}")

    # Volume: OBV + volume flow
    if calc_volume_flow:
        try:
            results["volume"] = calc_volume_flow(df)
            logger.info("[quant_node] volume calculated")
        except Exception as exc:
            logger.warning(f"[quant_node] volume failed: {exc}")

    # Candlestick patterns
    if analyze_candle_structure:
        try:
            results["candlestick"] = analyze_candle_structure(df)
            logger.info("[quant_node] candlestick analyzed")
        except Exception as exc:
            logger.warning(f"[quant_node] candlestick failed: {exc}")

    # Mean reversion (fetches its own daily bars from DAO internally)
    if MeanReversionStrategy:
        try:
            mr = MeanReversionStrategy(symbol=symbol, lookback=60, threshold=2.0)
            results["mean_reversion"] = mr.analyze()
            logger.info("[quant_node] mean_reversion analyzed")
        except Exception as exc:
            logger.warning(f"[quant_node] mean_reversion failed: {exc}")

    return results


def _parse_action_from_analysis(analysis: str) -> tuple[str, float]:
    """Parse trading action and confidence from LLM analysis text.

    Args:
        analysis: LLM-generated analysis string.

    Returns:
        Tuple of (action, confidence) where action is 'buy'/'sell'/'hold'.
    """
    lower = analysis.lower()
    if "**current signal:** bullish" in lower or "**recommendation:** buy" in lower:
        return "buy", 0.7
    if "**current signal:** bearish" in lower or "**recommendation:** sell" in lower:
        return "sell", 0.7
    return "hold", 0.6


def _save_quant_results(
    symbol: str,
    analysis: str,
    skill_results: dict,
    thread_id: str,
    query: str,
) -> None:
    """Persist quant analysis to DB for observability and audit trail.

    Saves to:
    - analysis.duckdb (strategy_results) via StrategyDAO
    - portfolio.duckdb (agent_interactions) via PortfolioDAO

    Args:
        symbol: Stock ticker.
        analysis: LLM-generated analysis text.
        skill_results: Raw indicator results dict.
        thread_id: Conversation thread UUID.
        query: Original user query.
    """
    try:
        from src.common.dao.strategy_dao import StrategyDAO
        from src.common.dao.portfolio_dao import PortfolioDAO

        action, confidence = _parse_action_from_analysis(analysis)

        mr_result = skill_results.get("mean_reversion", {}) or {}
        current_price = float(mr_result.get("current_price", 0.0) or 0.0)

        sdao = StrategyDAO()
        sdao.save_strategy_result(
            symbol=symbol,
            strategy_name="quant-analysis-langgraph",
            current_price=current_price,
            statistics=mr_result if mr_result else {},
            indicators={
                "momentum": skill_results.get("momentum", {}),
                "volatility": skill_results.get("volatility", {}),
                "volume": skill_results.get("volume", {}),
                "candlestick": skill_results.get("candlestick", {}),
            },
            signals={"source": "skill_functions" if skill_results else "precomputed_etl"},
            action=action,
            confidence=confidence,
            reason=analysis[:500],
            thought_trace=analysis,
            model_used="gpt-5-mini",
            timeframe="1Min",
        )
        sdao.close()

        pdao = PortfolioDAO()
        pdao.save_interaction(
            thread_id=thread_id,
            agent_name="quant_node",
            user_query=query,
            tool_sequence=[
                {"tool": "get_precomputed_indicators", "node": "quant_node"},
                {"tool": "get_company_fundamentals", "node": "quant_node"},
            ],
            agent_response=analysis[:500],
            model_used="gpt-5-mini",
        )
        pdao.close()

        logger.info(f"[quant_node] saved strategy result + interaction for {symbol}")

    except Exception as exc:
        logger.warning(f"[quant_node] DB persistence failed (non-critical): {exc}")


def quant_node(state: dict) -> dict:
    """Run technical analysis for the given symbol.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with quant_analysis and indicators keys.
    """
    symbol: Optional[str] = state.get("symbol")
    query: str = state.get("query", "")
    thread_id: str = state.get("thread_id", "unknown")

    if not symbol:
        logger.warning("[quant_node] no symbol in state — skipping quant analysis")
        return {
            "quant_analysis": (
                "No ticker symbol found in the query. "
                "Please specify a stock symbol for technical analysis."
            ),
            "indicators": {},
        }

    logger.info(f"[quant_node] running analysis for {symbol}")

    # ── Step 1: precomputed ETL data ─────────────────────────────────────────
    indicator_text: Optional[str] = None
    skill_results: dict = {}

    try:
        precomputed = get_precomputed_indicators.invoke({"symbol": symbol, "minutes": 30})
        if precomputed and "No precomputed indicators" not in precomputed:
            indicator_text = precomputed
            logger.info(f"[quant_node] using precomputed indicators for {symbol}")
    except Exception as exc:
        logger.warning(f"[quant_node] precomputed fetch failed: {exc}")

    # ── Step 2: individual skill functions (fallback) ─────────────────────────
    if indicator_text is None:
        logger.info(f"[quant_node] falling back to skill functions for {symbol}")
        df = _fetch_bars(symbol, lookback_minutes=60)
        if df is not None:
            skill_results = _run_skill_functions(symbol, df)
            indicator_text = json.dumps(skill_results, indent=2, default=str)
        else:
            indicator_text = f"No market data available for {symbol}."

    # ── Step 3: optional fundamentals ────────────────────────────────────────
    fundamentals_text = ""
    try:
        fundamentals = get_company_fundamentals.invoke({"symbol": symbol})
        if fundamentals and "Error" not in str(fundamentals):
            fundamentals_text = f"\n\nFundamentals:\n{fundamentals}"
    except Exception as exc:
        logger.debug(f"[quant_node] fundamentals skipped: {exc}")

    # ── Step 4: LLM synthesis ─────────────────────────────────────────────────
    combined = indicator_text + fundamentals_text
    analysis = _synthesize_analysis(symbol, query, combined)

    safe_skill_results = _to_native(skill_results)

    _save_quant_results(symbol, analysis, safe_skill_results, thread_id, query)

    return {
        "quant_analysis": analysis,
        "indicators": {
            "symbol": symbol,
            "source": "precomputed_etl" if not skill_results else "skill_functions",
            "skill_results": safe_skill_results,
        },
    }


def _synthesize_analysis(symbol: str, query: str, indicator_data: str) -> str:
    """LLM synthesis of raw indicator data into a structured analysis.

    Args:
        symbol: Stock ticker.
        query: Original user query for context.
        indicator_data: Raw indicator text/JSON to interpret.

    Returns:
        Structured analysis string.
    """
    try:
        from langchain_openai import ChatOpenAI

        from src.common.utils import secrets
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1, api_key=secrets.get("openai.api_key"))
        system_prompt = f"""You are a quantitative analyst synthesizing technical indicator data for {symbol}.

Provide analysis in exactly this format:

**Current Signal:** [Bullish / Bearish / Neutral]

**Key Indicators:**
- RSI: [value — >70 overbought, <30 oversold]
- MACD: [histogram sign interpretation]
- Bollinger Bands: [band position]
- OBV/Volume: [divergence or confirmation]
- Mean Reversion: [z-score interpretation if available]

**Recommendation:** [Buy / Sell / Hold with brief rationale]

**Risk Factors:** [2-3 key risks]

Be concise and data-driven. Only include sections with available data."""

        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User query: {query}\n\n"
                    f"Technical data for {symbol}:\n{indicator_data}"
                ),
            },
        ])
        return response.content

    except Exception as exc:
        logger.warning(f"[quant_node] LLM synthesis failed: {exc}")
        return (
            f"**Technical Analysis for {symbol}**\n\n"
            f"*(LLM synthesis unavailable)*\n\n"
            f"{indicator_data}"
        )


if __name__ == "__main__":
    """Functional test: run quant analysis for AAPL."""
    print("=" * 60)
    print("Quant Node Functional Tests")
    print("=" * 60)

    print("\n[1/2] quant analysis for AAPL")
    result = quant_node({
        "intent": "quant",
        "backtest_mode": True,
        "query": "Analyze AAPL for buy signal",
        "symbol": "AAPL",
    })
    print(f"[OK] keys returned: {list(result.keys())}")
    assert "quant_analysis" in result
    assert "indicators" in result
    print(f"     source: {result['indicators'].get('source')}")
    print(f"     quant_analysis preview: {result['quant_analysis'][:150]}...")

    print("\n[2/2] no symbol — graceful degradation")
    result = quant_node({"intent": "quant", "query": "Analyze the market"})
    assert "No ticker symbol" in result["quant_analysis"]
    print("[OK] no-symbol handled gracefully")

    print("\n" + "=" * 60)
    print("Quant node tests complete!")
