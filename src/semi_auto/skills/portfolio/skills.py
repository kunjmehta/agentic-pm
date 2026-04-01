"""Portfolio skill class for the semi_auto registry.

A single ``PortfolioSkills`` class groups all portfolio-related operations:

    get_status()                 — fetch live Alpaca account status.
    get_positions_summary()      — fetch current positions with P&L.
    check_health(status, pos)    — validate portfolio against risk limits.
    execute_order(...)           — place a market or limit order via Alpaca.
    close_position(symbol)       — liquidate one position at market price.
    scale_position(symbol, pct)  — resize position to a target % of equity.
    execute_strategy_signal(...) — translate buy/sell/hold signal into order.
    fetch_historical_data(...)   — download and cache historical bars.
    check_data_availability(...) — verify bar coverage in local DB.

All implementation code is inlined here so this module has no runtime
dependency on src/agentic/. All src/common/ imports are deferred to the
call site to avoid DAO-singleton ordering issues.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class PortfolioSkills:
    """All portfolio skill operations as a single cohesive class.

    Each method maps 1-to-1 with a registry function so the registry can
    either import the legacy free-function aliases below or call the class
    methods directly.
    """

    # ------------------------------------------------------------------
    # Portfolio status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Fetch current portfolio status from Alpaca and snapshot to DB.

        Returns:
            Dict with equity, cash, buying_power, long_positions,
            short_positions, portfolio_value, last_equity, timestamp.
        """
        from src.common.external.alpaca_portfolio import fetch_account_info, fetch_positions
        from src.common.dao import PortfolioDAO

        account_data = fetch_account_info()
        positions_data = fetch_positions()
        long_count = sum(1 for p in positions_data if p["side"] == "long")
        short_count = sum(1 for p in positions_data if p["side"] == "short")

        result = {
            "equity": account_data["equity"],
            "cash": account_data["cash"],
            "buying_power": account_data["buying_power"],
            "long_positions": long_count,
            "short_positions": short_count,
            "portfolio_value": account_data["portfolio_value"],
            "last_equity": account_data["last_equity"],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            dao = PortfolioDAO()
            dao.save_snapshot(
                timestamp=datetime.now(),
                equity=result["equity"],
                cash=result["cash"],
                buying_power=result["buying_power"],
                long_positions=long_count,
                short_positions=short_count,
                snapshot_source="alpaca",
            )
            dao.close()
        except Exception as dao_err:
            logger.warning(f"[PortfolioSkills.get_status] DAO snapshot failed: {dao_err}")

        return result

    # ------------------------------------------------------------------
    # Positions summary
    # ------------------------------------------------------------------

    def get_positions_summary(self) -> Dict:
        """Fetch current positions with P&L breakdown.

        Returns:
            Dict with positions list, count, total_market_value,
            total_unrealized_pl, timestamp.
        """
        from src.common.external.alpaca_portfolio import fetch_positions

        positions_data = fetch_positions()
        total_mv = sum(p.get("market_value", 0.0) for p in positions_data)
        total_upl = sum(p.get("unrealized_pl", 0.0) for p in positions_data)

        return {
            "positions": positions_data,
            "count": len(positions_data),
            "total_market_value": total_mv,
            "total_unrealized_pl": total_upl,
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def check_health(self, portfolio_status: Dict, positions_data: Dict) -> Dict:
        """Check portfolio against risk parameters stored in PortfolioDAO.

        Checks:
            - position concentration (% of equity per position)
            - position size (absolute share count)
            - cash reserves (minimum cash % threshold)

        Args:
            portfolio_status: Result from ``get_status()``.
            positions_data: Result from ``get_positions_summary()``.

        Returns:
            Dict with health_status ("healthy" / "warning" / "unhealthy"),
            violations list, warnings list, checks_performed,
            risk_parameters_used, timestamp.
        """
        from src.common.dao import PortfolioDAO

        dao = PortfolioDAO()
        risk_params = dao.get_risk_parameters()
        dao.close()

        position_limit_pct = risk_params.get("position_limit_percent", {}).get("value", 0.1)
        daily_loss_limit = risk_params.get("daily_loss_limit", {}).get("value", 0.05)
        max_position_size = risk_params.get("max_position_size", {}).get("value", 1000)

        violations = []
        warnings = []
        equity = portfolio_status.get("equity", 0)

        if equity > 0:
            for pos in positions_data.get("positions", []):
                pos_pct = abs(pos.get("market_value", 0)) / equity
                if pos_pct > position_limit_pct:
                    violations.append({
                        "rule": "position_limit_percent",
                        "symbol": pos.get("symbol"),
                        "current": pos_pct,
                        "limit": position_limit_pct,
                        "message": (
                            f"{pos.get('symbol')} represents "
                            f"{pos_pct * 100:.1f}% of portfolio "
                            f"(limit: {position_limit_pct * 100:.1f}%)"
                        ),
                    })
                if abs(pos.get("qty", 0)) > max_position_size:
                    warnings.append({
                        "rule": "max_position_size",
                        "symbol": pos.get("symbol"),
                        "current": abs(pos.get("qty", 0)),
                        "limit": max_position_size,
                        "message": (
                            f"{pos.get('symbol')} position size {abs(pos.get('qty', 0))} "
                            f"exceeds limit {max_position_size}"
                        ),
                    })

        cash_pct = portfolio_status.get("cash", 0) / equity if equity > 0 else 0
        if cash_pct < 0.05:
            warnings.append({
                "rule": "cash_reserve",
                "current": cash_pct,
                "message": f"Low cash reserves: {cash_pct * 100:.1f}%",
            })

        health_status = (
            "unhealthy" if violations else "warning" if warnings else "healthy"
        )

        return {
            "health_status": health_status,
            "violations": violations,
            "warnings": warnings,
            "checks_performed": ["position_concentration", "position_size", "cash_reserves"],
            "risk_parameters_used": {
                "position_limit_percent": position_limit_pct,
                "max_position_size": max_position_size,
                "daily_loss_limit": daily_loss_limit,
            },
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def execute_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """Place a buy or sell order via Alpaca.

        Routes to a market or limit order based on ``order_type``.

        Args:
            symbol: Stock ticker (e.g. "AAPL").
            qty: Number of shares.  Must be > 0.
            side: "buy" or "sell".
            order_type: "market" (default) or "limit".
            limit_price: Required when ``order_type == "limit"``.

        Returns:
            Dict with order id, symbol, qty, side, type, status,
            submitted_at, and optionally limit_price.

        Raises:
            ValueError: If order_type is unsupported or limit_price is
                missing for a limit order.
        """
        from src.common.external.alpaca_portfolio import (
            place_market_order,
            place_limit_order,
        )

        if order_type == "market":
            return place_market_order(symbol=symbol, qty=qty, side=side)
        if order_type == "limit":
            if limit_price is None or limit_price <= 0:
                raise ValueError(
                    f"limit_price must be > 0 for a limit order, got {limit_price}"
                )
            return place_limit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                limit_price=limit_price,
            )
        raise ValueError(
            f"Unsupported order_type '{order_type}'. Use 'market' or 'limit'."
        )

    def close_position(self, symbol: str) -> Dict:
        """Liquidate the full position for a symbol at market price.

        Args:
            symbol: Stock ticker whose position to close.

        Returns:
            Dict with closing order details.

        Raises:
            Exception: If the symbol has no open position or the API fails.
        """
        from src.common.external.alpaca_portfolio import close_position as _close

        return _close(symbol=symbol)

    def scale_position(
        self,
        symbol: str,
        target_pct: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Dict:
        """Scale an open (or new) position to a target portfolio percentage.

        Fetches current equity and position size, computes the delta in
        shares required to reach ``target_pct`` of portfolio, then places
        a buy or sell order for that delta.

        Args:
            symbol: Stock ticker (e.g. "AAPL").
            target_pct: Desired position size as a fraction of total equity
                (e.g. 0.05 = 5%).  Use 0.0 to fully close the position.
            order_type: "market" (default) or "limit".
            limit_price: Required when ``order_type == "limit"``.

        Returns:
            Dict with:
                - action: "buy" | "sell" | "hold" | "close"
                - symbol, target_pct, current_pct
                - current_qty, target_qty, delta_qty
                - order: result from execute_order (or None for "hold")
                - equity, current_price
                - timestamp

        Raises:
            Exception: If account or price data cannot be fetched.
        """
        from src.common.external.alpaca_portfolio import (
            fetch_account_info,
            fetch_positions,
        )

        # ── Fetch current state ──────────────────────────────────────────
        account = fetch_account_info()
        equity = account.get("equity", 0.0)
        if equity <= 0:
            raise ValueError(f"Cannot scale position: invalid equity {equity}")

        positions = fetch_positions()
        pos_map = {p["symbol"].upper(): p for p in positions}
        current_pos = pos_map.get(symbol.upper())

        current_qty = float(current_pos["qty"]) if current_pos else 0.0
        # qty_available excludes shares locked in pending orders — use it
        # for sell-side delta to avoid 403 (insufficient qty) errors.
        qty_available = float(current_pos.get("qty_available", current_pos["qty"])) if current_pos else 0.0
        current_price_raw = (
            float(current_pos["current_price"]) if current_pos else None
        )

        # ── Resolve current price ────────────────────────────────────────
        if current_price_raw is None or current_price_raw <= 0:
            # Fall back to latest bar price from DB
            try:
                from src.common.dao import AlpacaDAO
                from datetime import timedelta

                dao = AlpacaDAO()
                end = datetime.now()
                start = end - timedelta(days=5)
                df = dao.get_bars(symbol, start=start, end=end, timeframe="1Day")
                dao.close()
                current_price_raw = (
                    float(df["close"].iloc[-1]) if not df.empty else None
                )
            except Exception:
                current_price_raw = None

        if current_price_raw is None or current_price_raw <= 0:
            raise ValueError(
                f"Cannot determine current price for {symbol}. "
                "Ensure market data is available."
            )

        current_price = current_price_raw

        # ── Compute target qty ───────────────────────────────────────────
        target_notional = equity * max(0.0, float(target_pct))
        target_qty = int(target_notional / current_price)  # whole shares only
        delta_qty = target_qty - int(current_qty)

        current_pct = (abs(current_qty) * current_price / equity) if equity > 0 else 0.0

        result: Dict = {
            "symbol": symbol.upper(),
            "target_pct": target_pct,
            "current_pct": round(current_pct, 4),
            "current_qty": int(current_qty),
            "target_qty": target_qty,
            "delta_qty": delta_qty,
            "equity": equity,
            "current_price": current_price,
            "order_type": order_type,
            "timestamp": datetime.now().isoformat(),
        }

        # ── Determine action ─────────────────────────────────────────────
        if target_pct == 0.0 and current_qty != 0:
            order = self.close_position(symbol)
            result["action"] = "close"
            result["order"] = order
        elif delta_qty == 0:
            result["action"] = "hold"
            result["order"] = None
            result["message"] = "Position already at target — no order placed"
        elif delta_qty > 0:
            order = self.execute_order(
                symbol=symbol,
                qty=abs(delta_qty),
                side="buy",
                order_type=order_type,
                limit_price=limit_price,
            )
            result["action"] = "buy"
            result["order"] = order
        else:
            # Cap sell qty to available shares to avoid 403 on locked positions.
            sell_qty = min(abs(delta_qty), int(qty_available))
            if sell_qty <= 0:
                result["action"] = "hold"
                result["order"] = None
                result["message"] = "No available shares to sell — skipping"
            else:
                order = self.execute_order(
                    symbol=symbol,
                    qty=sell_qty,
                    side="sell",
                    order_type=order_type,
                    limit_price=limit_price,
                )
                result["action"] = "sell"
                result["order"] = order

        logger.info(
            f"[scale_position] {symbol} action={result['action']} "
            f"delta={delta_qty} current_pct={current_pct:.2%} → target={target_pct:.2%}"
        )
        return result

    def execute_strategy_signal(
        self,
        symbol: str,
        signal: str,
        confidence: float = 1.0,
        base_position_pct: float = 0.05,
        order_type: str = "market",
    ) -> Dict:
        """Translate a strategy signal into a scaled order.

        Maps buy/sell/hold signals to position sizes using confidence
        as a multiplier of ``base_position_pct``.

        Mapping:
            - "buy"  → scale_position(target_pct = base_position_pct * confidence)
            - "sell" → close_position(symbol) if long, or scale to 0
            - "hold" → no action

        Args:
            symbol: Stock ticker.
            signal: "buy" | "sell" | "hold" (case-insensitive).
            confidence: Conviction score 0–1.  Scales the buy size.
                Default 1.0 (full base_position_pct).
            base_position_pct: Maximum single-position allocation as a
                fraction of equity. Default 5% (0.05).
            order_type: "market" (default) or "limit".

        Returns:
            Dict with action, symbol, signal, confidence, order (or None),
            target_pct, timestamp.

        Raises:
            ValueError: If signal is not one of buy/sell/hold.
        """
        signal_lower = signal.lower().strip()
        if signal_lower not in {"buy", "sell", "hold"}:
            raise ValueError(
                f"Invalid signal '{signal}'. Must be 'buy', 'sell', or 'hold'."
            )

        conf = max(0.0, min(1.0, float(confidence)))

        # Read max_position_pct from config; fall back to 0.20 (20%).
        try:
            from src.common.utils import config as _cfg
            max_position_pct = float(_cfg.get("strategy.position_sizing.max_position_pct", 0.20))
        except Exception:
            max_position_pct = 0.20

        if signal_lower == "hold":
            logger.info(f"[execute_strategy_signal] {symbol} HOLD — no order")
            return {
                "action": "hold",
                "symbol": symbol.upper(),
                "signal": signal_lower,
                "confidence": conf,
                "order": None,
                "target_pct": None,
                "message": "Signal is HOLD — no order placed",
                "timestamp": datetime.now().isoformat(),
            }

        if signal_lower == "buy":
            target_pct = min(base_position_pct * conf, max_position_pct)
            scale_result = self.scale_position(
                symbol=symbol,
                target_pct=target_pct,
                order_type=order_type,
            )
            return {
                "action": scale_result.get("action", "buy"),
                "symbol": symbol.upper(),
                "signal": signal_lower,
                "confidence": conf,
                "target_pct": target_pct,
                "order": scale_result.get("order"),
                "scale_details": scale_result,
                "timestamp": datetime.now().isoformat(),
            }

        # signal_lower == "sell" → close position
        try:
            order = self.close_position(symbol)
        except Exception as exc:
            # No position to close is not an error — just report it
            logger.info(f"[execute_strategy_signal] no open position for {symbol}: {exc}")
            order = None
        return {
            "action": "sell",
            "symbol": symbol.upper(),
            "signal": signal_lower,
            "confidence": conf,
            "target_pct": 0.0,
            "order": order,
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Historical data management
    # ------------------------------------------------------------------

    def fetch_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1Min",
    ) -> Dict:
        """Download historical market data from Alpaca and persist to DB.

        If the requested bars already exist in the local database the
        function returns immediately without hitting the API.

        Args:
            symbol: Stock ticker (e.g. "AAPL").
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timeframe: Bar resolution. Defaults to ``"1Min"``.

        Returns:
            Dict with status, bars_fetched, symbol, date_range, timeframe,
            message, data_source.
        """
        from src.common.external.alpaca import fetch_historical_bars
        from src.common.dao import AlpacaDAO

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        now = datetime.now()

        if start_dt > now or end_dt > now:
            return {
                "status": "error",
                "error": "Future dates not allowed",
                "message": f"Start or end date is in the future. Current date: {now.date()}",
                "suggestion": f"Use dates up to {now.date()}",
            }

        # Check cache first
        dao = AlpacaDAO()
        existing = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)
        dao.close()

        if not existing.empty:
            return {
                "status": "success",
                "bars_fetched": len(existing),
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "timeframe": timeframe,
                "message": f"Data already available: {len(existing)} bars in database",
                "data_source": "database_cache",
            }

        bars_df = fetch_historical_bars(
            symbol=symbol, start=start_date, end=end_date, timeframe=timeframe
        )

        if bars_df is None or bars_df.empty:
            return {
                "status": "error",
                "error": "No data returned from API",
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"Alpaca API returned no data for {symbol}",
                "suggestion": "Verify symbol and date range",
            }

        count = len(bars_df)
        return {
            "status": "success",
            "bars_fetched": count,
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "timeframe": timeframe,
            "message": f"Successfully fetched {count} bars from Alpaca API",
            "data_source": "alpaca_api",
        }

    def check_data_availability(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1Min",
    ) -> Dict:
        """Check bar coverage for a symbol and date range in the local DB.

        Args:
            symbol: Stock ticker.
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timeframe: Bar resolution. Defaults to ``"1Min"``.

        Returns:
            Dict with available (True / False / "partial"), bar_count,
            expected_bars, coverage_pct, message, action_needed.
        """
        from src.common.dao import AlpacaDAO

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        dao = AlpacaDAO()
        bars_df = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)
        dao.close()

        bar_count = len(bars_df)
        trading_days = (end_dt - start_dt).days
        expected_bars = trading_days * 390 if timeframe == "1Min" else trading_days
        coverage_pct = (bar_count / expected_bars * 100) if expected_bars > 0 else 0

        if bar_count == 0:
            return {
                "available": False,
                "bar_count": 0,
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"No data found for {symbol}",
                "action_needed": "fetch_historical_data",
            }
        if coverage_pct < 80:
            return {
                "available": "partial",
                "bar_count": bar_count,
                "expected_bars": expected_bars,
                "coverage_pct": round(coverage_pct, 1),
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"Partial data: {bar_count} bars ({coverage_pct:.1f}% coverage)",
                "action_needed": "fetch_historical_data to fill gaps",
            }
        return {
            "available": True,
            "bar_count": bar_count,
            "expected_bars": expected_bars,
            "coverage_pct": round(coverage_pct, 1),
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Data available: {bar_count} bars",
            "action_needed": "none",
        }


# =============================================================================
# Module-level singleton + legacy function aliases
# =============================================================================

portfolio_skills = PortfolioSkills()

# These names are imported directly by the registry — keep them working.
get_portfolio_status_core = portfolio_skills.get_status
get_positions_summary_core = portfolio_skills.get_positions_summary
check_portfolio_health_core = portfolio_skills.check_health
fetch_historical_data_core = portfolio_skills.fetch_historical_data
check_data_availability_core = portfolio_skills.check_data_availability

# Order execution aliases (new — used by the registry)
execute_order_core = portfolio_skills.execute_order
close_position_core = portfolio_skills.close_position
scale_position_core = portfolio_skills.scale_position
execute_strategy_signal_core = portfolio_skills.execute_strategy_signal

__all__ = [
    "PortfolioSkills",
    "portfolio_skills",
    # Legacy function aliases
    "get_portfolio_status_core",
    "get_positions_summary_core",
    "check_portfolio_health_core",
    "fetch_historical_data_core",
    "check_data_availability_core",
    # Order execution aliases (new)
    "execute_order_core",
    "close_position_core",
    "scale_position_core",
    "execute_strategy_signal_core",
]
