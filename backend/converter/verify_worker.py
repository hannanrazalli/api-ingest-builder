import json
import sys

import duckdb
import pandas as pd

from backend.converter.compiler import parse
from backend.converter.pandas_runtime import _query


def compare(sql, dialect, plan, tables):
    frames = {name: pd.DataFrame(rows) for name, rows in tables.items()}
    node = parse(sql, dialect)
    db = duckdb.connect(
        config={
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "threads": "1",
            "memory_limit": "128MB",
        }
    )
    try:
        for name, frame in frames.items():
            db.register(name, frame)
        expected = db.execute(node.sql(dialect="duckdb")).fetchdf()
        actual = _query(plan, frames)
        if not node.args.get("order"):
            expected = expected.astype(object).where(expected.notna(), None)
            actual = actual.astype(object).where(actual.notna(), None)

            def key(frame):
                return (
                    frame.assign(__sort=frame.apply(lambda row: repr(list(row)), axis=1))
                    .sort_values("__sort")
                    .drop(columns="__sort")
                    .reset_index(drop=True)
                )

            expected, actual = key(expected), key(actual)
        pd.testing.assert_frame_equal(
            actual,
            expected,
            check_dtype=False,
            check_index_type=False,
            check_names=False,
            atol=1e-8,
            rtol=1e-8,
        )
        return {
            "match": True,
            "rows": len(actual),
            "columns": list(actual.columns),
            "detail": "pandas matches DuckDB on the supplied sample only",
        }
    except AssertionError:
        return {
            "match": False,
            "detail": "Results differ on the supplied sample; inspect SQL null/order semantics",
        }
    finally:
        db.close()


if __name__ == "__main__":
    value = json.load(sys.stdin)
    print(json.dumps(compare(**value)))
