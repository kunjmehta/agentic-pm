"""Signal Aggregator Service for autonomous trading.

Periodically fetches high-confidence signals from the strategy_results table,
aggregates them by symbol using conditional consensus logic, validates against
portfolio constraints and recent orders, and prepares signal batches for PM review.

Consensus Logic:
- For tickers with 2+ strategies configured: require 2+ strategies to agree
- For tickers with 1 strategy configured: accept single strategy signal (no consensus)
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from src.common.dao.strategy_dao import StrategyDAO
from src.common.dao.orders_dao import OrdersDAO
from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.utils import get_logger
from src.common.utils.config_loader import config as app_config
from src.semi_auto.models.autonomous_signals import (
    StrategySignal,
    AggregatedSignal,
    SignalBatch
)

logger = get_logger(__name__)


class SignalAggregator:
    """Aggregates strategy signals and validates portfolio constraints."""

    def __init__(
        self,
        strategy_dao: Optional[StrategyDAO] = None,
        orders_dao: Optional[OrdersDAO] = None,
        portfolio_dao: Optional[AlpacaDAO] = None
    ):
        """Initialize SignalAggregator with DAO dependencies.

        Args:
            strategy_dao: DAO for strategy results. Auto-created if None.
            orders_dao: DAO for order history. Auto-created if None.
            portfolio_dao: DAO for portfolio data. Auto-created if None.
        """
        self.strategy_dao = strategy_dao or StrategyDAO()
        self.orders_dao = orders_dao or OrdersDAO()
        self.portfolio_dao = portfolio_dao or AlpacaDAO()

    async def fetch_actionable_signals(
        self,
        min_confidence: float = 0.65,
        lookback_minutes: int = 30
    ) -> List[StrategySignal]:
        """Fetch signals generated in last N minutes above confidence threshold.

        Args:
            min_confidence: Minimum confidence threshold (0-1). Default 0.65.
            lookback_minutes: Time window for signal fetching. Default 30.

        Returns:
            List of StrategySignal objects.
        """
        try:
            raw_signals = self.strategy_dao.get_actionable_signals_by_time(
                min_confidence=min_confidence,
                lookback_minutes=lookback_minutes
            )

            if not raw_signals:
                logger.info(f"[signal_agg] No signals found in last {lookback_minutes}m")
                return []

            # Convert DB rows to StrategySignal Pydantic models
            signals = []
            for row in raw_signals:
                try:
                    signals.append(StrategySignal(
                        signal_id=row['id'],
                        symbol=row['symbol'],
                        strategy_name=row['strategy_name'],
                        action=row['action'],
                        confidence=row['confidence'],
                        entry_price=row.get('entry_price'),
                        stop_loss=row.get('stop_loss'),
                        take_profit=row.get('take_profit'),
                        reason=row['reason'],
                        timestamp=row['timestamp'],
                        indicators=row['indicators'],
                        statistics=row['statistics']
                    ))
                except Exception as exc:
                    logger.warning(f"[signal_agg] Failed to parse signal {row.get('id')}: {exc}")
                    continue

            logger.info(f"[signal_agg] Fetched {len(signals)} actionable signals")
            return signals

        except Exception as exc:
            logger.error(f"[signal_agg] Error fetching signals: {exc}", exc_info=True)
            return []

    async def aggregate_by_symbol(
        self,
        signals: List[StrategySignal]
    ) -> Dict[str, AggregatedSignal]:
        """Group signals by symbol and apply conditional consensus logic.

        For tickers with 2+ strategies configured in watchlist:
          - Require 2+ strategies to agree (consensus)
          - If 3+ agree on same action: boost confidence by 10%
          - If mixed signals (buy+sell): skip (no consensus)

        For tickers with 1 strategy configured:
          - Accept single strategy signal (no consensus required)

        Args:
            signals: List of StrategySignal objects.

        Returns:
            Dict mapping symbol -> AggregatedSignal.
        """
        # Group signals by symbol
        by_symbol = defaultdict(list)
        for sig in signals:
            by_symbol[sig.symbol].append(sig)

        aggregated = {}

        for symbol, symbol_signals in by_symbol.items():
            try:
                # Get configured strategies for this symbol
                watchlist = app_config.get("watchlist", {})
                watchlist_config = watchlist.get(symbol, {})
                configured_strategies = watchlist_config.get("strategies", [])
                num_configured = len(configured_strategies)

                if num_configured == 0:
                    logger.warning(f"[signal_agg] {symbol} not in watchlist config, skipping")
                    continue

                if not watchlist_config.get("autonomous_trading_enabled", True):
                    logger.info(f"[signal_agg] {symbol} autonomous trading disabled, skipping")
                    continue

                # Case 1: Single strategy configured - no consensus needed
                if num_configured == 1:
                    if len(symbol_signals) > 0:
                        # Use the most recent signal
                        sig = max(symbol_signals, key=lambda s: s.timestamp)
                        aggregated[symbol] = AggregatedSignal(
                            symbol=symbol,
                            action=sig.action,
                            confidence=sig.confidence,
                            strategies=[sig.strategy_name],
                            strategy_count=1,
                            consensus_reached=True,  # Single strategy = automatic consensus
                            entry_price=sig.entry_price or 0.0,
                            stop_loss=sig.stop_loss or 0.0,
                            take_profit=sig.take_profit or 0.0,
                            reason=f"[{sig.strategy_name}] {sig.reason}",
                            timestamp=sig.timestamp,
                            source_signals=[sig]
                        )
                        logger.info(
                            f"[signal_agg] {symbol}: single strategy '{sig.strategy_name}' "
                            f"→ {sig.action} @ {sig.confidence:.2f}"
                        )

                # Case 2: Multiple strategies configured - require consensus
                else:
                    # Count actions
                    action_votes = defaultdict(list)
                    for sig in symbol_signals:
                        action_votes[sig.action].append(sig)

                    # Find majority action (must have 2+ votes)
                    best_action = None
                    best_signals = []
                    for action, action_sigs in action_votes.items():
                        if action == "hold":
                            continue  # Skip hold signals
                        if len(action_sigs) >= 2:
                            if not best_action or len(action_sigs) > len(best_signals):
                                best_action = action
                                best_signals = action_sigs

                    if not best_action or len(best_signals) < 2:
                        logger.info(
                            f"[signal_agg] {symbol}: no consensus (need 2+ strategies to agree), skipping"
                        )
                        continue

                    # Consensus reached!
                    avg_confidence = sum(s.confidence for s in best_signals) / len(best_signals)

                    # Boost confidence if 3+ strategies agree
                    if len(best_signals) >= 3:
                        avg_confidence = min(1.0, avg_confidence * 1.10)
                        logger.info(
                            f"[signal_agg] {symbol}: 3+ strategies agree, boosting confidence by 10%"
                        )

                    # Aggregate entry/stop/target prices (average)
                    valid_entries = [s.entry_price for s in best_signals if s.entry_price]
                    valid_stops = [s.stop_loss for s in best_signals if s.stop_loss]
                    valid_targets = [s.take_profit for s in best_signals if s.take_profit]

                    entry = sum(valid_entries) / len(valid_entries) if valid_entries else 0.0
                    stop = sum(valid_stops) / len(valid_stops) if valid_stops else 0.0
                    target = sum(valid_targets) / len(valid_targets) if valid_targets else 0.0

                    # Combine reasoning
                    strategies_list = [s.strategy_name for s in best_signals]
                    combined_reason = f"{len(best_signals)}/{num_configured} strategies agree: " + \
                                      "; ".join([f"[{s.strategy_name}] {s.reason[:50]}" for s in best_signals[:3]])

                    aggregated[symbol] = AggregatedSignal(
                        symbol=symbol,
                        action=best_action,
                        confidence=avg_confidence,
                        strategies=strategies_list,
                        strategy_count=len(best_signals),
                        consensus_reached=True,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        reason=combined_reason,
                        timestamp=datetime.now(),
                        source_signals=best_signals
                    )

                    logger.info(
                        f"[signal_agg] {symbol}: consensus {best_action} @ {avg_confidence:.2f} "
                        f"({len(best_signals)}/{num_configured} strategies)"
                    )

            except Exception as exc:
                logger.error(f"[signal_agg] Error aggregating {symbol}: {exc}", exc_info=True)
                continue

        logger.info(f"[signal_agg] Aggregated {len(aggregated)} symbols from {len(signals)} signals")
        return aggregated

    async def check_recent_orders(
        self,
        symbol: str,
        action: str,
        lookback_hours: int = 24
    ) -> bool:
        """Check if a similar order was recently placed.

        Args:
            symbol: Stock ticker.
            action: Proposed action ("buy" or "sell").
            lookback_hours: How far back to check. Default 24.

        Returns:
            True if recent order exists (duplicate), False otherwise.
        """
        try:
            recent = self.orders_dao.get_recent_orders_for_symbol(
                symbol=symbol,
                side=action,
                lookback_hours=lookback_hours
            )
            if recent:
                logger.info(
                    f"[signal_agg] {symbol} duplicate check: found {len(recent)} "
                    f"recent {action} order(s) in last {lookback_hours}h"
                )
                return True
            return False
        except Exception as exc:
            logger.error(f"[signal_agg] Error checking recent orders for {symbol}: {exc}")
            return False  # On error, don't block (fail-open)

    async def validate_portfolio_constraints(
        self,
        symbol: str,
        action: str
    ) -> Tuple[bool, str]:
        """Check if order would violate position limits.

        Validates:
        - Max position size: 5% of equity
        - Already at max position for this symbol

        Args:
            symbol: Stock ticker.
            action: Proposed action ("buy" or "sell").

        Returns:
            Tuple (is_valid: bool, reason: str).
        """
        try:
            # Get account equity
            from src.common.external.alpaca_portfolio import fetch_account_info, fetch_positions
            account = fetch_account_info()
            equity = float(account.get('equity', 0))

            if equity == 0:
                return False, "Account equity is zero"

            max_position_value = equity * 0.05  # 5% max

            # Get current position
            positions = fetch_positions()
            current_position = next((p for p in positions if p['symbol'] == symbol), None)

            if action == "buy":
                if current_position:
                    current_value = float(current_position.get('market_value', 0))
                    if current_value >= max_position_value:
                        return False, f"Position already at max (${current_value:,.2f} >= ${max_position_value:,.2f})"

            # If we get here, constraints are satisfied
            return True, "Portfolio constraints satisfied"

        except Exception as exc:
            logger.error(f"[signal_agg] Error validating constraints for {symbol}: {exc}", exc_info=True)
            return False, f"Validation error: {exc}"

    async def generate_signal_batch(
        self,
        min_confidence: float = 0.65,
        lookback_minutes: int = 30
    ) -> Optional[SignalBatch]:
        """Main orchestration: fetch → aggregate → validate → return batch.

        Args:
            min_confidence: Minimum confidence threshold. Default 0.65.
            lookback_minutes: Time window for signal fetching. Default 30.

        Returns:
            SignalBatch with validated aggregated signals, or None if no signals.
        """
        try:
            logger.info(
                f"[signal_agg] Starting batch generation "
                f"(min_confidence={min_confidence}, lookback={lookback_minutes}m)"
            )

            # Step 1: Fetch raw signals
            raw_signals = await self.fetch_actionable_signals(min_confidence, lookback_minutes)
            if not raw_signals:
                logger.info("[signal_agg] No signals to aggregate")
                return None

            # Step 2: Aggregate by symbol (conditional consensus)
            aggregated = await self.aggregate_by_symbol(raw_signals)
            if not aggregated:
                logger.info("[signal_agg] No signals passed aggregation")
                return None

            # Step 3: Filter by recent orders and portfolio constraints
            validated_signals = []
            for symbol, agg_signal in aggregated.items():
                # Check for duplicate orders
                is_duplicate = await self.check_recent_orders(
                    symbol=symbol,
                    action=agg_signal.action,
                    lookback_hours=24
                )
                if is_duplicate:
                    logger.info(f"[signal_agg] {symbol}: skipping (duplicate order)")
                    continue

                # Check portfolio constraints
                is_valid, reason = await self.validate_portfolio_constraints(
                    symbol=symbol,
                    action=agg_signal.action
                )
                if not is_valid:
                    logger.info(f"[signal_agg] {symbol}: skipping ({reason})")
                    continue

                # Signal passed all checks
                validated_signals.append(agg_signal)

            if not validated_signals:
                logger.info("[signal_agg] No signals passed validation")
                return None

            # Step 4: Create SignalBatch
            batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            batch = SignalBatch(
                batch_id=batch_id,
                signals=validated_signals,
                generated_at=datetime.now(),
                lookback_minutes=lookback_minutes,
                min_confidence=min_confidence,
                total_signals_fetched=len(raw_signals),
                total_signals_aggregated=len(validated_signals)
            )

            logger.info(
                f"[signal_agg] Batch {batch_id} ready: "
                f"{len(validated_signals)} signals from {len(raw_signals)} raw signals"
            )
            return batch

        except Exception as exc:
            logger.error(f"[signal_agg] Error generating signal batch: {exc}", exc_info=True)
            return None


if __name__ == "__main__":
    """Smoke test for SignalAggregator (requires populated strategy_results)."""
    import asyncio

    print("=" * 60)
    print("SignalAggregator Smoke Test")
    print("=" * 60)

    async def test():
        aggregator = SignalAggregator()

        # Test 1: Fetch signals
        print("\n[1/3] Testing fetch_actionable_signals...")
        signals = await aggregator.fetch_actionable_signals(
            min_confidence=0.50,  # Lower threshold for testing
            lookback_minutes=120  # Longer window
        )
        print(f"[OK] Fetched {len(signals)} signals")

        if signals:
            # Test 2: Aggregate by symbol
            print("\n[2/3] Testing aggregate_by_symbol...")
            aggregated = await aggregator.aggregate_by_symbol(signals)
            print(f"[OK] Aggregated {len(aggregated)} symbols")

            for symbol, agg in aggregated.items():
                print(f"     {symbol}: {agg.action} @ {agg.confidence:.2f} "
                      f"({agg.strategy_count} strategies)")

        # Test 3: Generate full batch
        print("\n[3/3] Testing generate_signal_batch...")
        batch = await aggregator.generate_signal_batch(
            min_confidence=0.50,
            lookback_minutes=120
        )
        if batch:
            print(f"[OK] Batch {batch.batch_id}: {len(batch.signals)} signals")
            for sig in batch.signals:
                print(f"     {sig.symbol}: {sig.action} @ {sig.confidence:.2f}")
        else:
            print("[OK] No batch generated (no signals passed validation)")

    asyncio.run(test())

    print("\n" + "=" * 60)
    print("SignalAggregator smoke test complete!")
    print("=" * 60)
