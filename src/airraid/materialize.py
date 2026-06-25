"""Milestone 4 — materialize `hourly_panel` (Direct grid: hour_ts × oblast_id × lead_hours).

Efficient interval-expansion: expand each alert into the discrete hours it covers (a small,
indexed set), then label `y_alert_active` = active at `hour_ts + lead_hours` via an index lookup.
Bounded to a recent window for the first build; idempotent UPSERT. TEMP table is ON COMMIT DROP
(session scratch — never touches persistent tables).
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from .db import engine

WINDOW_DAYS = 120

_ACTIVE = text(
    """
    CREATE TEMP TABLE _active ON COMMIT DROP AS
    SELECT DISTINCT r.oblast_id, gs AS hour_ts
    FROM raw_alerts r
    CROSS JOIN LATERAL generate_series(
        date_trunc('hour', r.started_at),
        date_trunc('hour', COALESCE(r.ended_at, r.started_at + interval '30 minutes') - interval '1 microsecond'),
        interval '1 hour'
    ) AS gs
    WHERE r.started_at >= (SELECT max(started_at) FROM raw_alerts) - make_interval(days => :days + 2)
    """
)

_INSERT = text(
    """
    WITH bounds AS (SELECT date_trunc('hour', max(started_at)) AS hi FROM raw_alerts),
    hours AS (
        SELECT generate_series((SELECT hi FROM bounds) - make_interval(days => :days),
                               (SELECT hi FROM bounds), interval '1 hour') AS hour_ts
    )
    INSERT INTO hourly_panel (hour_ts, oblast_id, lead_hours, y_alert_active)
    SELECT h.hour_ts, o.id, l.lead,
           EXISTS (
               SELECT 1 FROM _active a
               WHERE a.oblast_id = o.id
                 AND a.hour_ts = h.hour_ts + make_interval(hours => l.lead::int)
           )
    FROM hours h
    CROSS JOIN oblasts o
    CROSS JOIN generate_series(1, 6) AS l(lead)
    ON CONFLICT (hour_ts, oblast_id, lead_hours)
    DO UPDATE SET y_alert_active = EXCLUDED.y_alert_active, built_at = now()
    """
)


def main(window_days: int = WINDOW_DAYS) -> None:
    with engine.begin() as c:
        c.execute(_ACTIVE, {"days": window_days})
        c.execute(text("CREATE INDEX ON _active (oblast_id, hour_ts)"))
        c.execute(text("ANALYZE _active"))
        c.execute(_INSERT, {"days": window_days})
        n = c.execute(text("SELECT count(*) FROM hourly_panel")).scalar_one()
        pos = c.execute(text("SELECT count(*) FROM hourly_panel WHERE y_alert_active")).scalar_one()
        lo, hi = c.execute(text("SELECT min(hour_ts), max(hour_ts) FROM hourly_panel")).one()
    rate = (pos / n) if n else 0.0
    print(f"hourly_panel: rows={n} window=[{lo} .. {hi}] positives={pos} base_rate={rate:.3%}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else WINDOW_DAYS
    main(days)
