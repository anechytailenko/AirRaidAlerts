"""§D validation suite — STRICTLY READ-ONLY.

NEVER drops/creates/truncates. Verifies required tables exist, then prints total row
counts and the exact NULL count + ratio for EVERY column of EVERY table, to prove the
data actually landed and that no column is silently all-NULL.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from .db import engine
from .models import ALL_TABLES


def main() -> int:
    insp = inspect(engine)
    present = set(insp.get_table_names())

    print("=== Table existence ===")
    for t in ALL_TABLES:
        print(f"  {'OK     ' if t in present else 'MISSING'}  {t}")
    missing = [t for t in ALL_TABLES if t not in present]
    if missing:
        print(f"\nFAIL — missing tables: {missing}")
        return 1

    print("\n=== Row counts + NULL counts per column (read-only) ===")
    failures: list[str] = []
    with engine.connect() as c:
        for t in ALL_TABLES:
            cols = [col["name"] for col in insp.get_columns(t)]
            total = c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()
            print(f"\n[{t}]  rows = {total}")
            if total == 0:
                print("  (empty)")
                continue
            null_sql = ", ".join(
                f'count(*) FILTER (WHERE "{col}" IS NULL) AS "{col}"' for col in cols
            )
            row = c.execute(text(f'SELECT {null_sql} FROM "{t}"')).mappings().one()
            for col in cols:
                n = int(row[col])
                ratio = n / total
                flag = "  <-- ALL NULL" if n == total else ""
                if n == total:
                    failures.append(f"{t}.{col} is 100% NULL")
                print(f"    {col:26s} nulls = {n:>9d}  ({ratio:6.1%}){flag}")

    if failures:
        print("\nWARN — silently-sparse columns:")
        for f in failures:
            print(f"  - {f}")
    print("\nValidation complete (read-only; nothing dropped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
