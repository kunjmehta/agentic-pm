"""Test end-to-end backtest with Pydantic integration."""

import sys
sys.path.insert(0, 'D:/Projects/agentic-trader')
sys.stdout.reconfigure(encoding='utf-8')

print('=' * 60)
print('END-TO-END BACKTEST TEST - Pydantic Integration')
print('=' * 60)

from src.server.skills.backtester.backtest_strategy import BacktestStrategySkill

backtester = BacktestStrategySkill()

# Test with buy-and-hold strategy (simplest)
print('\n[TEST] Running buy-and-hold backtest...')
print('  Ticker: AAPL')
print('  Period: 2024-01-02 to 2024-01-05 (3 trading days)')
print('  Strategy: buy-and-hold (Pydantic-based)')
print()

result = backtester.run(
    ticker='AAPL',
    start_date='2024-01-02',
    end_date='2024-01-05',
    strategy='buy-and-hold',
    initial_capital=100000.0,
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
    print('✅ END-TO-END BACKTEST SUCCESSFUL!')
    print('✅ Pydantic integration working correctly!')
elif result.get('status') == 'failed':
    print(f'  Error: {result.get("error", "Unknown error")}')
    print('✗ Backtest failed')
else:
    print(f'  Unexpected status: {result.get("status")}')
    print('✗ Unexpected result')

print('=' * 60)
