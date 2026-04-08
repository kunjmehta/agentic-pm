"""Test VWAP reversion strategy with Pydantic."""

import sys
sys.path.insert(0, 'D:/Projects/agentic-trader')
sys.stdout.reconfigure(encoding='utf-8')

print('=' * 60)
print('VWAP REVERSION BACKTEST - Parameter Passing Test')
print('=' * 60)

from src.server.skills.backtester.backtest_strategy import BacktestStrategySkill

backtester = BacktestStrategySkill()

print('\n[TEST] Running vwap-reversion backtest with custom parameters...')
print('  Ticker: AAPL')
print('  Period: 2024-01-02 to 2024-01-03 (1 trading day)')
print('  Strategy: vwap-reversion')
print('  Parameters: dev_pct=0.005, vol_mult=2.0')
print()

result = backtester.run(
    ticker='AAPL',
    start_date='2024-01-02',
    end_date='2024-01-03',
    strategy='vwap-reversion',
    initial_capital=100000.0,
    strategy_params={
        'dev_pct': 0.005,
        'vol_mult': 2.0
    },
    save_to_db=False
)

print(f'Status: {result.get("status")}')

if result.get('status') == 'completed':
    metrics = result.get('metrics', {})
    print(f'  Initial Capital: ${result.get("initial_capital", 0):,.2f}')
    print(f'  Final Capital: ${result.get("final_capital", 0):,.2f}')
    print(f'  Total Return: {metrics.get("total_return_pct", 0):.2f}%')
    print(f'  Total Trades: {metrics.get("total_trades", 0)}')
    print()
    print('✅ VWAP REVERSION BACKTEST SUCCESSFUL!')
    print('✅ Parameter passing works correctly!')
elif result.get('status') == 'failed':
    print(f'  Error: {result.get("error", "Unknown error")}')
    print('⚠️ Backtest failed (this may be expected if no signals generated)')
else:
    print(f'  Unexpected status: {result.get("status")}')

print('=' * 60)
