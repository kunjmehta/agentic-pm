"""Data conversion utilities for JSON serialization.

Provides canonical type coercion for converting numpy/pandas types to Python
native types, safe for JSON serialization and LangGraph MemorySaver storage.
"""
from __future__ import annotations

import decimal
import math
from datetime import date, datetime
from typing import Any


def _to_native(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable types to native Python equivalents.

    Handles numpy scalar types, pandas Timestamps, Decimals, datetimes, and
    nested containers so that results from DAO layers can be safely
    JSON-serialised or passed as plain dicts to the executor/synthesizer.

    Args:
        obj: Any Python object — scalar, dict, list, or nested structure.

    Returns:
        Object with all non-native types replaced by their Python equivalents.
    """
    if obj is None:
        return None
    # numpy integer / float scalars and arrays
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, np.ndarray):
            return [_to_native(v) for v in obj.tolist()]
    except ImportError:
        pass
    # pandas Timestamp
    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass
    # Decimal
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    # datetime / date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # containers
    if isinstance(obj, dict):
        return {str(k): _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def df_to_records(df: Any) -> list:
    """Convert a DataFrame to a JSON-serializable list of native dicts.

    Applies full type coercion via ``_to_native`` so that numpy/pandas scalar
    types are converted to Python primitives safe for JSON serialization.

    Args:
        df: pandas DataFrame or None.

    Returns:
        List of native dicts, empty list if df is None or empty.
    """
    try:
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        return _to_native(df.to_dict("records"))
    except Exception:
        return []


if __name__ == "__main__":
    """Smoke test: verify type coercion for common non-native types."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("converters.py smoke test")
    print("=" * 60)

    # Test 1: numpy types
    try:
        import numpy as np
        assert _to_native(np.int64(42)) == 42
        assert isinstance(_to_native(np.int64(42)), int)
        assert _to_native(np.float32(3.14)) is not None
        assert isinstance(_to_native(np.float32(3.14)), float)
        assert _to_native(np.float64(float("nan"))) is None
        assert _to_native(np.array([1, 2, 3])) == [1, 2, 3]
        print("  [OK] numpy types")
    except ImportError:
        print("  [SKIP] numpy not installed")

    # Test 2: pandas Timestamp
    try:
        import pandas as pd
        ts = pd.Timestamp("2024-01-15 10:30:00")
        result = _to_native(ts)
        assert isinstance(result, str) and "2024-01-15" in result
        print("  [OK] pandas Timestamp")
    except ImportError:
        print("  [SKIP] pandas not installed")

    # Test 3: Decimal
    from decimal import Decimal
    assert _to_native(Decimal("3.14")) == 3.14
    print("  [OK] Decimal")

    # Test 4: datetime / date
    from datetime import datetime as dt, date as d
    assert _to_native(dt(2024, 1, 15, 10, 30)) == "2024-01-15T10:30:00"
    assert _to_native(d(2024, 1, 15)) == "2024-01-15"
    print("  [OK] datetime / date")

    # Test 5: nested containers
    nested = {"a": [1, {"b": 2}], "c": (3, 4)}
    result = _to_native(nested)
    assert result == {"a": [1, {"b": 2}], "c": [3, 4]}
    print("  [OK] nested containers")

    # Test 6: df_to_records
    try:
        import pandas as pd
        import numpy as np
        df = pd.DataFrame({"x": np.array([1, 2], dtype=np.int64), "y": [1.1, 2.2]})
        records = df_to_records(df)
        assert len(records) == 2
        assert isinstance(records[0]["x"], int)
        assert df_to_records(None) == []
        assert df_to_records(pd.DataFrame()) == []
        print("  [OK] df_to_records")
    except ImportError:
        print("  [SKIP] pandas/numpy not installed")

    print("\n[ALL OK] converters.py smoke test passed")
