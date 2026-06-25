"""Build the leak-safe `feature_matrix` (one row per (hour_ts, oblast_id)).

Every feature is known **as-of decision time `t = hour_ts`** — so when this joins to `hourly_panel`
(label at `t + lead_hours`, lead ≥ 1, strictly future), no feature can leak the target:

  1. Weather (target oblast, contemporaneous at `t`)  — temp_c, wind_speed, precip_mm, cloud_cover.
     Open-Meteo at the oblast centroid; available at `t` (and as a forecast for `t+1..6h`, used later).
  2. Spatial alert state AT `t` (never `t+lead`):
       • self_alert_active     — was THIS oblast under alert at `t` (autoregressive).
       • neighbor_alert_count  — # adjacent oblasts under alert at `t`.
       • neighbor_alert_frac   — that count / total neighbors (alerts propagate across borders).
  3. Calendar (deterministic from `t`, UTC) — hour/dow/month, is_weekend, cyclical sin/cos.

Implementation mirrors `materialize.py`: interval-expand alerts → indexed TEMP set, pivot weather and
neighbor counts into TEMP tables, then one indexed INSERT … ON CONFLICT (idempotent). TEMP tables are
ON COMMIT DROP. The build is read-only w.r.t. all persistent source tables.
"""
from __future__ import annotations

from sqlalchemy import text

from .db import Base, engine
from .models import FeatureMatrix  # noqa: F401 — registers the table on Base.metadata

_ACTIVE = text(
    """
    CREATE TEMP TABLE _active ON COMMIT DROP AS
    SELECT DISTINCT r.oblast_id, gs AS hour_ts
    FROM raw_alerts r
    CROSS JOIN LATERAL generate_series(
        date_trunc('hour', r.started_at),
        date_trunc('hour', COALESCE(r.ended_at, r.started_at + interval '30 minutes') - interval '1 microsecond'),
        interval '1 hour'
    ) AS gs;
    """
)

_WX = text(
    """
    CREATE TEMP TABLE _wx ON COMMIT DROP AS
    SELECT oblast_id, event_ts AS hour_ts,
        max(value_num) FILTER (WHERE feature_key = 'temp_c')      AS temp_c,
        max(value_num) FILTER (WHERE feature_key = 'wind_speed')  AS wind_speed,
        max(value_num) FILTER (WHERE feature_key = 'precip_mm')   AS precip_mm,
        max(value_num) FILTER (WHERE feature_key = 'cloud_cover') AS cloud_cover
    FROM exogenous_features
    WHERE source = 'open_meteo' AND scope = 'oblast'
    GROUP BY oblast_id, event_ts;
    """
)

_NBR = text(
    """
    CREATE TEMP TABLE _nbr ON COMMIT DROP AS
    SELECT adj.oblast_id, a.hour_ts, count(*)::int AS cnt
    FROM oblast_adjacency adj
    JOIN _active a ON a.oblast_id = adj.neighbor_oblast_id
    GROUP BY adj.oblast_id, a.hour_ts;
    """
)

_NTOT = text(
    "CREATE TEMP TABLE _ntot ON COMMIT DROP AS "
    "SELECT oblast_id, count(*)::int AS tot FROM oblast_adjacency GROUP BY oblast_id;"
)

_INSERT = text(
    """
    INSERT INTO feature_matrix (
        hour_ts, oblast_id, temp_c, wind_speed, precip_mm, cloud_cover,
        self_alert_active, neighbor_alert_count, neighbor_alert_frac,
        hour_of_day, dow, month, is_weekend, hour_sin, hour_cos, dow_sin, dow_cos)
    SELECT g.hour_ts, g.oblast_id,
        wx.temp_c, wx.wind_speed, wx.precip_mm, wx.cloud_cover,
        (sa.hour_ts IS NOT NULL)                                    AS self_alert_active,
        COALESCE(nb.cnt, 0)                                         AS neighbor_alert_count,
        COALESCE(nb.cnt::numeric / NULLIF(nt.tot, 0), 0)            AS neighbor_alert_frac,
        EXTRACT(hour  FROM g.hour_ts AT TIME ZONE 'UTC')::int       AS hour_of_day,
        EXTRACT(dow   FROM g.hour_ts AT TIME ZONE 'UTC')::int       AS dow,
        EXTRACT(month FROM g.hour_ts AT TIME ZONE 'UTC')::int       AS month,
        (EXTRACT(dow FROM g.hour_ts AT TIME ZONE 'UTC') IN (0, 6))  AS is_weekend,
        sin(2 * pi() * EXTRACT(hour FROM g.hour_ts AT TIME ZONE 'UTC') / 24.0) AS hour_sin,
        cos(2 * pi() * EXTRACT(hour FROM g.hour_ts AT TIME ZONE 'UTC') / 24.0) AS hour_cos,
        sin(2 * pi() * EXTRACT(dow  FROM g.hour_ts AT TIME ZONE 'UTC') /  7.0) AS dow_sin,
        cos(2 * pi() * EXTRACT(dow  FROM g.hour_ts AT TIME ZONE 'UTC') /  7.0) AS dow_cos
    FROM (SELECT DISTINCT hour_ts, oblast_id FROM hourly_panel) g
    LEFT JOIN _wx     wx ON wx.oblast_id = g.oblast_id AND wx.hour_ts = g.hour_ts
    LEFT JOIN _active sa ON sa.oblast_id = g.oblast_id AND sa.hour_ts = g.hour_ts
    LEFT JOIN _nbr    nb ON nb.oblast_id = g.oblast_id AND nb.hour_ts = g.hour_ts
    LEFT JOIN _ntot   nt ON nt.oblast_id = g.oblast_id
    ON CONFLICT (hour_ts, oblast_id) DO UPDATE SET
        temp_c = EXCLUDED.temp_c, wind_speed = EXCLUDED.wind_speed, precip_mm = EXCLUDED.precip_mm,
        cloud_cover = EXCLUDED.cloud_cover, self_alert_active = EXCLUDED.self_alert_active,
        neighbor_alert_count = EXCLUDED.neighbor_alert_count, neighbor_alert_frac = EXCLUDED.neighbor_alert_frac,
        hour_of_day = EXCLUDED.hour_of_day, dow = EXCLUDED.dow, month = EXCLUDED.month,
        is_weekend = EXCLUDED.is_weekend, hour_sin = EXCLUDED.hour_sin, hour_cos = EXCLUDED.hour_cos,
        dow_sin = EXCLUDED.dow_sin, dow_cos = EXCLUDED.dow_cos, built_at = now();
    """
)


def main() -> None:
    Base.metadata.create_all(engine)  # create feature_matrix IF NOT EXISTS (never drops)
    with engine.begin() as c:
        c.execute(_ACTIVE)
        c.execute(text("CREATE INDEX ON _active (oblast_id, hour_ts)"))
        c.execute(_WX)
        c.execute(text("CREATE INDEX ON _wx (oblast_id, hour_ts)"))
        c.execute(_NBR)
        c.execute(text("CREATE INDEX ON _nbr (oblast_id, hour_ts)"))
        c.execute(_NTOT)
        c.execute(text("ANALYZE _active"))
        c.execute(text("ANALYZE _wx"))
        c.execute(text("ANALYZE _nbr"))
        c.execute(_INSERT)
        n = c.execute(text("SELECT count(*) FROM feature_matrix")).scalar_one()
        lo, hi = c.execute(text("SELECT min(hour_ts), max(hour_ts) FROM feature_matrix")).one()
        wx_null = c.execute(text("SELECT count(*) FROM feature_matrix WHERE temp_c IS NULL")).scalar_one()
        self_pos = c.execute(text("SELECT count(*) FROM feature_matrix WHERE self_alert_active")).scalar_one()
        nbr_any = c.execute(text("SELECT count(*) FROM feature_matrix WHERE neighbor_alert_count > 0")).scalar_one()
    print(f"feature_matrix: rows={n} window=[{lo} .. {hi}]")
    print(f"  weather-null rows (pre-ERA5 start)={wx_null} | self_alert_active={self_pos} | neighbor>0={nbr_any}")


if __name__ == "__main__":
    main()
