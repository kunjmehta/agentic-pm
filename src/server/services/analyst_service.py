"""Analyst summary service — generates 10-minute LLM market summaries per ticker.

Called by the ETL process every 10 minutes. For each symbol it:
1. Fetches 1-minute OHLCV bars for the window.
2. Fetches pre-computed indicators for the window.
3. Fetches strategy signals from ``precomputed_strategy_signals`` for the window.
4. Reads the rolling day-so-far summary from ``analyst_summaries``.
5. Calls the LLM and returns a structured ``AnalystSummaryResult``.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.dao.analysis_dao import AnalysisDAO
from src.common.utils import get_logger
from src.common.utils.prompt_loader import load_prompt
from src.server.agents import get_llm
from src.server.models.analyst_models import AnalystSummaryResult

logger = get_logger(__name__)

_SYSTEM_PROMPT: Optional[str] = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = load_prompt("analyst_summary")
    return _SYSTEM_PROMPT


def _format_bars(df: pd.DataFrame) -> str:
    """Convert OHLCV DataFrame to a compact text table for the LLM prompt."""
    if df.empty:
        return "No bar data available."
    cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in df.columns]
    rows = df[cols].tail(10).to_string(index=False, float_format="{:.2f}".format)
    return f"OHLCV bars (latest 10 of {len(df)}):\n{rows}"


def _format_indicators(df: pd.DataFrame) -> str:
    """Summarise computed indicators as latest-value key-value pairs."""
    if df.empty:
        return "No indicator data available."
    latest = df.iloc[-1]
    exclude = {"symbol", "timestamp", "timeframe", "id", "created_at"}
    pairs = [
        f"{col}={latest[col]:.4f}" if isinstance(latest[col], float) else f"{col}={latest[col]}"
        for col in df.columns
        if col not in exclude and pd.notna(latest[col])
    ]
    return "Latest indicators: " + ", ".join(pairs) if pairs else "No indicator values."


def _format_signals(df: pd.DataFrame) -> str:
    """Summarise strategy signals as a compact text list."""
    if df.empty:
        return "No strategy signals in this window."
    # Only include signals with meaningful confidence
    meaningful = df[df["confidence"].fillna(0) >= 0.4] if "confidence" in df.columns else df
    if meaningful.empty:
        return "No signals with confidence ≥ 0.4 in this window."
    lines = []
    for _, row in meaningful.iterrows():
        strat = row.get("strategy_name", "unknown")
        action = row.get("action", "?")
        conf = row.get("confidence", 0.0)
        reason = row.get("reason", "")
        lines.append(f"  • {strat}: {action} (confidence={conf:.2f}) — {reason}")
    return "Strategy signals:\n" + "\n".join(lines)


def _format_rolling_context(prior_summary: Optional[dict]) -> str:
    """Format the prior 10-minute summary as rolling context."""
    if not prior_summary:
        return "Rolling context: No prior summary for today — this is the first window."
    signals = prior_summary.get("signals", {})
    prior_trend = signals.get("trend", "unknown")
    prior_text = prior_summary.get("summary_text", "")
    ts = prior_summary.get("timestamp", "")
    return (
        f"Rolling day context (last update: {ts}):\n"
        f"  Prior trend: {prior_trend}\n"
        f"  Prior summary: {prior_text}"
    )


def _build_user_message(
    symbol: str,
    window_start: datetime,
    window_end: datetime,
    bars_df: pd.DataFrame,
    indicators_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    prior_summary: Optional[dict],
) -> str:
    """Assemble the full user message for the LLM."""
    return (
        f"## Analyst Summary Request\n\n"
        f"**Ticker:** {symbol}\n"
        f"**Window:** {window_start.strftime('%H:%M')} – {window_end.strftime('%H:%M')} ET "
        f"({window_end.strftime('%Y-%m-%d')})\n\n"
        f"### 1. Price Action\n{_format_bars(bars_df)}\n\n"
        f"### 2. Technical Indicators\n{_format_indicators(indicators_df)}\n\n"
        f"### 3. Strategy Signals\n{_format_signals(signals_df)}\n\n"
        f"### 4. Rolling Day Context\n{_format_rolling_context(prior_summary)}\n"
    )


class AnalystSummaryService:
    """Generates structured 10-minute analyst summaries via LLM.

    Designed to be instantiated once per ETL process and reused across
    scheduling cycles. DAO connections are opened and closed per call to avoid
    holding long-lived write connections to DuckDB.
    """

    async def generate_summary(
        self,
        symbol: str,
        window_start: datetime,
        window_end: datetime,
    ) -> Optional[AnalystSummaryResult]:
        """Generate an analyst summary for a single symbol over a 10-minute window.

        Args:
            symbol: Stock ticker (e.g. ``"AAPL"``).
            window_start: Start of the 10-minute window.
            window_end: End of the 10-minute window (typically now).

        Returns:
            Structured ``AnalystSummaryResult`` or ``None`` if data is insufficient
            or the LLM call fails.
        """
        alpaca_dao = AlpacaDAO()
        analysis_dao = AnalysisDAO()
        try:
            bars_df = alpaca_dao.get_bars(symbol, window_start, window_end, "1Min")
            indicators_df = alpaca_dao.get_computed_indicators(symbol, window_start, window_end, "1Min")
            signals_df = alpaca_dao.get_strategy_signals_range(symbol, window_start, window_end, "1Min")
            prior_summary = analysis_dao.get_latest_eod(symbol)

            if bars_df.empty:
                logger.debug(f"[analyst_service] no bars for {symbol} in window — skipping")
                return None

            user_message = _build_user_message(
                symbol, window_start, window_end, bars_df, indicators_df, signals_df, prior_summary
            )

            result: AnalystSummaryResult = await asyncio.to_thread(
                _invoke_llm, user_message
            )
            logger.info(
                f"[analyst_service] {symbol} → trend={result.trend} confidence={result.confidence}"
            )
            return result

        except Exception as exc:
            logger.error(f"[analyst_service] failed for {symbol}: {exc}", exc_info=True)
            return None
        finally:
            alpaca_dao.close()
            analysis_dao.close()


def _invoke_llm(user_message: str) -> AnalystSummaryResult:
    """Synchronous LLM call — run via asyncio.to_thread from async context."""
    structured_llm = get_llm("analyst").with_structured_output(
        AnalystSummaryResult, method="function_calling"
    )
    return structured_llm.invoke([
        {"role": "system", "content": _get_system_prompt()},
        {"role": "user", "content": user_message},
    ])


# Singleton for ETL process
analyst_summary_service = AnalystSummaryService()


__all__ = ["AnalystSummaryService", "analyst_summary_service"]


if __name__ == "__main__":
    """Smoke test — generates a summary for AAPL over the last 10 minutes."""
    import asyncio
    from datetime import timedelta

    async def _test() -> None:
        now = datetime.now()
        start = now - timedelta(minutes=10)
        result = await analyst_summary_service.generate_summary("AAPL", start, now)
        if result:
            print(f"trend      : {result.trend}")
            print(f"confidence : {result.confidence}")
            print(f"summary    : {result.summary}")
            print(f"reasoning  : {result.trend_reasoning}")
            print(f"signals    : {result.key_signals}")
        else:
            print("No result — check logs for details.")

    asyncio.run(_test())
