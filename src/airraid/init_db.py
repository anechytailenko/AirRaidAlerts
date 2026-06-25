"""Milestone 2 — create tables (idempotent, never drops) and verify existence."""
from __future__ import annotations

from sqlalchemy import inspect

from . import models  # noqa: F401  (register mappers)
from .db import Base, engine
from .models import ALL_TABLES


def main() -> None:
    # CREATE TABLE IF NOT EXISTS semantics — never drops or truncates existing data.
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    present = set(insp.get_table_names())
    print("Tables present:", sorted(present))
    missing = [t for t in ALL_TABLES if t not in present]
    if missing:
        raise SystemExit(f"FAIL — missing tables: {missing}")
    print(f"OK — all {len(ALL_TABLES)} required tables exist.")


if __name__ == "__main__":
    main()
