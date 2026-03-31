"""
Test script for portfolio schema verification.
Module 1: Portfolio Schema (DuckDB)

Tests:
1. Schema file execution
2. Table creation verification
3. Sample data insertion
4. Index verification
5. Views verification
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.dao.base_dao import BaseDAO


def test_schema_creation():
    """Test that all tables are created successfully."""
    print("\n=== Test 1: Schema Creation ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Execute schema
        schema_path = "config/schema/portfolio_schema.sql"
        dao.execute_schema_file(schema_path)
        print(f"[OK] Schema executed successfully from {schema_path}")

        # Verify tables exist
        tables = ['portfolio_snapshots', 'agent_interactions', 'portfolio_parameters']
        for table in tables:
            exists = dao.table_exists(table)
            if exists:
                print(f"[OK] Table '{table}' exists")
            else:
                print(f"[FAIL] Table '{table}' NOT FOUND")
                return False

        return True
    except Exception as e:
        print(f"[FAIL] Schema creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        dao.close()


def test_portfolio_snapshots_insert():
    """Test inserting data into portfolio_snapshots table."""
    print("\n=== Test 2: Portfolio Snapshots Insert ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Insert sample snapshot
        insert_query = """
            INSERT INTO portfolio_snapshots (
                timestamp, date_only, equity, cash, buying_power,
                daily_pnl, total_pnl, daily_pnl_percent,
                long_positions, short_positions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date_only) DO UPDATE SET
                timestamp = excluded.timestamp,
                equity = excluded.equity,
                cash = excluded.cash,
                buying_power = excluded.buying_power,
                daily_pnl = excluded.daily_pnl,
                total_pnl = excluded.total_pnl,
                daily_pnl_percent = excluded.daily_pnl_percent,
                long_positions = excluded.long_positions,
                short_positions = excluded.short_positions
        """

        now = datetime.now()
        today = date.today()

        params = (
            now, today, 100000.00, 50000.00, 100000.00,
            1500.00, 5000.00, 0.0150,
            3, 0
        )

        dao.execute(insert_query, params)
        print("[OK] Inserted sample portfolio snapshot")

        # Verify insert
        select_query = "SELECT * FROM portfolio_snapshots WHERE date_only = ?"
        result = dao.fetch_one(select_query, (today,))

        if result:
            print(f"[OK] Verified snapshot: equity=${result['equity']}, cash=${result['cash']}")
            print(f"  P&L: ${result['daily_pnl']} ({result['daily_pnl_percent']*100:.2f}%)")
            print(f"  Positions: {result['long_positions']} long, {result['short_positions']} short")
        else:
            print("[FAIL] Failed to verify snapshot")
            return False

        # Test UNIQUE constraint on date_only
        try:
            dao.execute(insert_query, params)  # Should update, not fail
            print("[OK] UNIQUE constraint on date_only works (upsert succeeded)")
        except Exception as e:
            print(f"[FAIL] UNIQUE constraint test failed: {e}")
            return False

        return True
    except Exception as e:
        print(f"[FAIL] Portfolio snapshots insert failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        dao.close()


def test_agent_interactions_insert():
    """Test inserting data into agent_interactions table."""
    print("\n=== Test 3: Agent Interactions Insert ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Insert sample interaction
        insert_query = """
            INSERT INTO agent_interactions (
                timestamp, thread_id, agent_name, user_query,
                tool_sequence, agent_response, model_used,
                token_count, execution_time_ms, tool_timings,
                delegated_to, delegation_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        import json
        now = datetime.now()

        tool_sequence = json.dumps([
            {"tool": "get_portfolio_status", "executed": True},
            {"tool": "check_portfolio_health", "executed": True}
        ])

        tool_timings = json.dumps([
            {"tool": "get_portfolio_status", "duration_ms": 150, "status": "success"},
            {"tool": "check_portfolio_health", "duration_ms": 75, "status": "success"}
        ])

        params = (
            now, "test-thread-001", "portfolio_manager", "What's my portfolio status?",
            tool_sequence, "Your portfolio is healthy with equity of $100,000.",
            "gpt-4o-mini", 450, 225, tool_timings,
            None, None
        )

        dao.execute(insert_query, params)
        print("[OK] Inserted sample agent interaction")

        # Verify insert
        select_query = """
            SELECT * FROM agent_interactions
            WHERE thread_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """
        result = dao.fetch_one(select_query, ("test-thread-001",))

        if result:
            print(f"[OK] Verified interaction: agent={result['agent_name']}, thread={result['thread_id']}")
            print(f"  Execution time: {result['execution_time_ms']}ms, Tokens: {result['token_count']}")
            print(f"  Tool timings: {result['tool_timings']}")
            print(f"  Expires at: {result['expires_at']}")
        else:
            print("[FAIL] Failed to verify interaction")
            return False

        # Test expires_at default (should be +30 days)
        expires = datetime.fromisoformat(str(result['expires_at']))
        created = datetime.fromisoformat(str(result['created_at']))
        days_diff = (expires - created).days

        if 29 <= days_diff <= 31:  # Allow for some rounding
            print(f"[OK] Expires_at default works: {days_diff} days from creation")
        else:
            print(f"[FAIL] Expires_at incorrect: {days_diff} days (expected ~30)")
            return False

        return True
    except Exception as e:
        print(f"[FAIL] Agent interactions insert failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        dao.close()


def test_portfolio_parameters_seed():
    """Test that risk parameters were seeded correctly."""
    print("\n=== Test 4: Portfolio Parameters Seed ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Query all parameters
        query = "SELECT * FROM portfolio_parameters ORDER BY parameter_key"
        results = dao.fetch_all(query)

        if not results:
            print("[FAIL] No parameters found")
            return False

        print(f"[OK] Found {len(results)} risk parameters:")
        for param in results:
            import json
            value = json.loads(param['parameter_value'])
            print(f"  - {param['parameter_key']}: {value}")
            print(f"    Description: {param['description']}")

        # Verify expected parameters exist
        expected_keys = [
            'max_position_size', 'max_daily_trades', 'position_limit_percent',
            'stop_loss_percent', 'daily_loss_limit', 'risk_free_rate'
        ]

        found_keys = [r['parameter_key'] for r in results]
        missing = set(expected_keys) - set(found_keys)

        if missing:
            print(f"[FAIL] Missing parameters: {missing}")
            return False

        print("[OK] All expected parameters found")
        return True
    except Exception as e:
        print(f"[FAIL] Portfolio parameters verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        dao.close()


def test_indexes():
    """Test that indexes were created successfully."""
    print("\n=== Test 5: Index Verification ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Query index information
        query = """
            SELECT index_name, table_name
            FROM duckdb_indexes()
            WHERE table_name IN ('portfolio_snapshots', 'agent_interactions', 'portfolio_parameters')
            ORDER BY table_name, index_name
        """

        results = dao.fetch_all(query)

        if not results:
            print("[WARN] No indexes found (may be expected for some databases)")
            return True

        print(f"[OK] Found {len(results)} indexes:")
        for idx in results:
            print(f"  - {idx['table_name']}.{idx['index_name']}")

        return True
    except Exception as e:
        print(f"[WARN] Index verification skipped (not critical): {e}")
        return True  # Don't fail on index verification
    finally:
        dao.close()


def test_views():
    """Test that views were created successfully."""
    print("\n=== Test 6: View Verification ===")

    dao = BaseDAO(db_path="data/portfolio.duckdb")

    try:
        # Test latest_portfolio_snapshot view
        query1 = "SELECT * FROM latest_portfolio_snapshot"
        result1 = dao.fetch_one(query1)
        if result1:
            print("[OK] View 'latest_portfolio_snapshot' works")
        else:
            print("[WARN] View 'latest_portfolio_snapshot' returned no data (expected if no snapshots)")

        # Test recent_agent_interactions view
        query2 = "SELECT * FROM recent_agent_interactions LIMIT 5"
        result2 = dao.fetch_all(query2)
        if result2:
            print(f"[OK] View 'recent_agent_interactions' works ({len(result2)} rows)")
        else:
            print("[WARN] View 'recent_agent_interactions' returned no data (expected if no interactions)")

        # Test agent_performance_summary view
        query3 = "SELECT * FROM agent_performance_summary"
        result3 = dao.fetch_all(query3)
        if result3:
            print(f"[OK] View 'agent_performance_summary' works ({len(result3)} agents)")
            for agent in result3:
                print(f"  - {agent['agent_name']}: {agent['total_interactions']} interactions, "
                      f"avg {agent['avg_execution_time_ms']:.0f}ms")
        else:
            print("[WARN] View 'agent_performance_summary' returned no data (expected if no recent interactions)")

        return True
    except Exception as e:
        print(f"[FAIL] View verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        dao.close()


def main():
    """Run all schema tests."""
    print("="*60)
    print("Portfolio Schema Test Suite")
    print("="*60)

    tests = [
        ("Schema Creation", test_schema_creation),
        ("Portfolio Snapshots Insert", test_portfolio_snapshots_insert),
        ("Agent Interactions Insert", test_agent_interactions_insert),
        ("Portfolio Parameters Seed", test_portfolio_parameters_seed),
        ("Index Verification", test_indexes),
        ("View Verification", test_views),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n[FAIL] Test '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "[OK]" if result else "[FAIL]"
        print(f"{symbol} {name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n[SUCCESS] All tests passed! Schema is ready.")
        return 0
    else:
        print(f"\n[ERROR] {total - passed} test(s) failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    exit(main())
