"""Stage-1 → Stage-2 bridge: compile ALL Postgres tables into one unified, leak-safe analytical bundle.

STRICTLY READ-ONLY. We open the Postgres session as `default_transaction_read_only=on`, issue only
`SELECT`s, and create **zero** objects in Postgres (no temp, no views, no tables). All alignment happens
out-of-database in an in-memory **DuckDB** instance whose `ASOF JOIN` performs the leak-safe OSINT merge.
Output is written only to a local `data/exports/` directory (gitignored).

Grain & leak-safety (see plans/04-analytics-eda.md):
  decision time t = hour_ts; every feature is known AS-OF t; the label y lives at t + lead_hours (≥1,
  strictly future). The OSINT flags (the only data not already in feature_matrix) are forward-filled from
  events with event_ts ≤ t (DuckDB ASOF), with a TTL guard + hours_since staleness columns.

Bundle: airraid_analytical_long.parquet (primary, ~6.15M), airraid_analytical_wide.parquet (~1.02M),
edges.parquet (GNN edge_index), oblasts.parquet (node meta), data_dictionary.md, sample_preview.csv,
manifest.json.

Usage:
  PYTHONPATH=src python -m airraid.export_dataset --grain both --bundle --out data/exports
  PYTHONPATH=src python -m airraid.export_dataset --verify --out data/exports
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import text

from .db import engine

OUT_DEFAULT = Path("data/exports")
TTL_HOURS = 6  # a stale OSINT "airborne=true" with no closing all-clear older than this reverts to false

LONG_NAME = "airraid_analytical_long.parquet"
WIDE_NAME = "airraid_analytical_wide.parquet"
EDGES_NAME = "edges.parquet"
OBLASTS_NAME = "oblasts.parquet"
DICT_NAME = "data_dictionary.md"
SAMPLE_NAME = "sample_preview.csv"
MANIFEST_NAME = "manifest.json"

# --- read-only SELECTs against existing tables (casts give clean ML dtypes; no Decimal) ----------------
_Q_PANEL = "SELECT hour_ts, oblast_id::int AS oblast_id, lead_hours::int AS lead_hours, y_alert_active FROM hourly_panel"
_Q_FM = """
SELECT hour_ts, oblast_id::int AS oblast_id,
       temp_c::float8 AS temp_c, wind_speed::float8 AS wind_speed,
       precip_mm::float8 AS precip_mm, cloud_cover::float8 AS cloud_cover,
       self_alert_active, neighbor_alert_count::int AS neighbor_alert_count,
       neighbor_alert_frac::float8 AS neighbor_alert_frac,
       hour_of_day::int AS hour_of_day, dow::int AS dow, month::int AS month, is_weekend,
       hour_sin::float8 AS hour_sin, hour_cos::float8 AS hour_cos,
       dow_sin::float8 AS dow_sin, dow_cos::float8 AS dow_cos
FROM feature_matrix
"""
_Q_OBL = "SELECT id::int AS oblast_id, name_en AS oblast_name, centroid_lat::float8 AS centroid_lat, centroid_lon::float8 AS centroid_lon FROM oblasts"
_Q_ADJ = "SELECT oblast_id::int AS oblast_id, neighbor_oblast_id::int AS neighbor_oblast_id FROM oblast_adjacency"
_Q_OSINT = "SELECT event_ts, feature_key, scope::text AS scope, oblast_id::int AS oblast_id, value_bool FROM exogenous_features WHERE source = 'telegram' ORDER BY event_ts"


def _read_base_tables() -> dict[str, pd.DataFrame]:
    """Pull every analytical table once, read-only. Memory is trivial (only panel is 6M × 4 narrow cols)."""
    with engine.connect() as c:
        c.execute(text("SET default_transaction_read_only = on"))  # hard read-only guard
        frames = {
            "panel": pd.read_sql(text(_Q_PANEL), c),
            "fm": pd.read_sql(text(_Q_FM), c),
            "obl": pd.read_sql(text(_Q_OBL), c),
            "adj": pd.read_sql(text(_Q_ADJ), c),
            "osint": pd.read_sql(text(_Q_OSINT), c),
        }
    return frames


def _osint_state_sql() -> str:
    """DuckDB ASOF assembly → one row per (hour_ts, oblast_id) with leak-safe OSINT flag-states.

    National flags are oblast-independent: resolve them per distinct hour (small) then broadcast.
    The oblast-scoped mass-attack flag is ASOF-joined partitioned by oblast_id.
    """
    return f"""
    CREATE TEMP TABLE osint_state AS
    WITH hours AS (SELECT DISTINCT hour_ts FROM fm),
    mig  AS (SELECT event_ts, value_bool FROM osint WHERE feature_key='mig_31_airborne'    AND scope='national'),
    tu   AS (SELECT event_ts, value_bool FROM osint WHERE feature_key='tu_95_takeoff'      AND scope='national'),
    massn AS (SELECT event_ts, value_bool FROM osint WHERE feature_key='mass_attack_active' AND scope='national'),
    masso AS (SELECT event_ts, oblast_id, value_bool FROM osint WHERE feature_key='mass_attack_active' AND scope='oblast'),
    nat AS (
        SELECT h.hour_ts,
            COALESCE(mig.value_bool  AND date_diff('hour', mig.event_ts,  h.hour_ts) <= {TTL_HOURS}, FALSE) AS osint_mig31_airborne,
            COALESCE(tu.value_bool   AND date_diff('hour', tu.event_ts,   h.hour_ts) <= {TTL_HOURS}, FALSE) AS osint_tu95_takeoff,
            COALESCE(massn.value_bool AND date_diff('hour', massn.event_ts, h.hour_ts) <= {TTL_HOURS}, FALSE) AS osint_mass_national,
            CASE WHEN mig.event_ts IS NULL THEN NULL ELSE date_diff('hour', mig.event_ts, h.hour_ts) END AS hours_since_mig31,
            CASE WHEN tu.event_ts  IS NULL THEN NULL ELSE date_diff('hour', tu.event_ts,  h.hour_ts) END AS hours_since_tu95
        FROM hours h
        ASOF LEFT JOIN mig   ON h.hour_ts >= mig.event_ts
        ASOF LEFT JOIN tu    ON h.hour_ts >= tu.event_ts
        ASOF LEFT JOIN massn ON h.hour_ts >= massn.event_ts
    ),
    obl_mass AS (
        SELECT g.hour_ts, g.oblast_id,
            COALESCE(masso.value_bool AND date_diff('hour', masso.event_ts, g.hour_ts) <= {TTL_HOURS}, FALSE) AS osint_mass_oblast
        FROM (SELECT hour_ts, oblast_id FROM fm) g
        ASOF LEFT JOIN masso ON g.oblast_id = masso.oblast_id AND g.hour_ts >= masso.event_ts
    )
    SELECT g.hour_ts, g.oblast_id,
        nat.osint_mig31_airborne, nat.osint_tu95_takeoff, nat.osint_mass_national,
        om.osint_mass_oblast, nat.hours_since_mig31, nat.hours_since_tu95
    FROM (SELECT hour_ts, oblast_id FROM fm) g
    JOIN nat ON nat.hour_ts = g.hour_ts
    JOIN obl_mass om ON om.hour_ts = g.hour_ts AND om.oblast_id = g.oblast_id;
    """


_LONG_SELECT = """
SELECT p.hour_ts, p.oblast_id, p.lead_hours, p.y_alert_active,
       o.oblast_name, o.centroid_lat, o.centroid_lon,
       f.temp_c, f.wind_speed, f.precip_mm, f.cloud_cover,
       f.self_alert_active, f.neighbor_alert_count, f.neighbor_alert_frac,
       f.hour_of_day, f.dow, f.month, f.is_weekend, f.hour_sin, f.hour_cos, f.dow_sin, f.dow_cos,
       s.osint_mig31_airborne, s.osint_tu95_takeoff, s.osint_mass_national, s.osint_mass_oblast,
       s.hours_since_mig31, s.hours_since_tu95,
       CAST(EXTRACT(year FROM p.hour_ts) AS INT) AS year
FROM panel p
JOIN fm f          ON f.hour_ts = p.hour_ts AND f.oblast_id = p.oblast_id
JOIN obl o         ON o.oblast_id = p.oblast_id
JOIN osint_state s ON s.hour_ts = p.hour_ts AND s.oblast_id = p.oblast_id
"""

_WIDE_SELECT = """
WITH lab AS (
    SELECT hour_ts, oblast_id,
        MAX(CASE WHEN lead_hours=1 THEN y_alert_active END) AS y_lead_1,
        MAX(CASE WHEN lead_hours=2 THEN y_alert_active END) AS y_lead_2,
        MAX(CASE WHEN lead_hours=3 THEN y_alert_active END) AS y_lead_3,
        MAX(CASE WHEN lead_hours=4 THEN y_alert_active END) AS y_lead_4,
        MAX(CASE WHEN lead_hours=5 THEN y_alert_active END) AS y_lead_5,
        MAX(CASE WHEN lead_hours=6 THEN y_alert_active END) AS y_lead_6
    FROM panel GROUP BY hour_ts, oblast_id
)
SELECT f.hour_ts, f.oblast_id,
       lab.y_lead_1, lab.y_lead_2, lab.y_lead_3, lab.y_lead_4, lab.y_lead_5, lab.y_lead_6,
       o.oblast_name, o.centroid_lat, o.centroid_lon,
       f.temp_c, f.wind_speed, f.precip_mm, f.cloud_cover,
       f.self_alert_active, f.neighbor_alert_count, f.neighbor_alert_frac,
       f.hour_of_day, f.dow, f.month, f.is_weekend, f.hour_sin, f.hour_cos, f.dow_sin, f.dow_cos,
       s.osint_mig31_airborne, s.osint_tu95_takeoff, s.osint_mass_national, s.osint_mass_oblast,
       s.hours_since_mig31, s.hours_since_tu95,
       CAST(EXTRACT(year FROM f.hour_ts) AS INT) AS year
FROM fm f
JOIN lab           ON lab.hour_ts = f.hour_ts AND lab.oblast_id = f.oblast_id
JOIN obl o         ON o.oblast_id = f.oblast_id
JOIN osint_state s ON s.hour_ts = f.hour_ts AND s.oblast_id = f.oblast_id
"""


def _git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "no-commit"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _con(frames: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()  # in-memory; nothing touches Postgres
    con.execute("SET TimeZone='UTC'")  # UTC-consistent with feature_matrix calendar + deterministic year
    for name, df in frames.items():
        con.register(name, df)
    con.execute(_osint_state_sql())
    return con


def build(out: Path, grain: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    frames = _read_base_tables()
    con = _con(frames)
    info: dict = {}

    if grain in ("long", "both"):
        lp = out / LONG_NAME
        con.execute(f"COPY ({_LONG_SELECT}) TO '{lp}' (FORMAT parquet, COMPRESSION zstd)")
        info["long_rows"] = con.execute(f"SELECT count(*) FROM read_parquet('{lp}')").fetchone()[0]
    if grain in ("wide", "both"):
        wp = out / WIDE_NAME
        con.execute(f"COPY ({_WIDE_SELECT}) TO '{wp}' (FORMAT parquet, COMPRESSION zstd)")
        info["wide_rows"] = con.execute(f"SELECT count(*) FROM read_parquet('{wp}')").fetchone()[0]

    # companions: GNN edge_index (0-based node indices from sorted oblast ids) + node metadata
    ep = out / EDGES_NAME
    con.execute(
        f"""COPY (
            WITH nodes AS (SELECT oblast_id, row_number() OVER (ORDER BY oblast_id) - 1 AS node_idx FROM obl)
            SELECT a.oblast_id AS src_oblast_id, a.neighbor_oblast_id AS dst_oblast_id,
                   ns.node_idx AS src_idx, nd.node_idx AS dst_idx
            FROM adj a JOIN nodes ns ON ns.oblast_id=a.oblast_id JOIN nodes nd ON nd.oblast_id=a.neighbor_oblast_id
            ORDER BY src_idx, dst_idx
        ) TO '{ep}' (FORMAT parquet, COMPRESSION zstd)"""
    )
    op = out / OBLASTS_NAME
    con.execute(
        f"""COPY (
            SELECT oblast_id, oblast_name, centroid_lat, centroid_lon,
                   row_number() OVER (ORDER BY oblast_id) - 1 AS node_idx FROM obl ORDER BY oblast_id
        ) TO '{op}' (FORMAT parquet, COMPRESSION zstd)"""
    )
    info["edges_rows"] = con.execute(f"SELECT count(*) FROM read_parquet('{ep}')").fetchone()[0]
    info["oblasts_rows"] = con.execute(f"SELECT count(*) FROM read_parquet('{op}')").fetchone()[0]

    # human preview (the only CSV) from the primary file
    primary = out / (LONG_NAME if grain != "wide" else WIDE_NAME)
    con.execute(f"COPY (SELECT * FROM read_parquet('{primary}') LIMIT 10000) TO '{out / SAMPLE_NAME}' (HEADER, DELIMITER ',')")

    _write_dictionary(out / DICT_NAME)
    manifest = _write_manifest(out, frames, info, grain)
    con.close()
    return manifest


def _write_manifest(out: Path, frames: dict[str, pd.DataFrame], info: dict, grain: str) -> dict:
    with engine.connect() as c:
        c.execute(text("SET default_transaction_read_only = on"))
        src_max = c.execute(text(
            "SELECT max(m) FROM (SELECT max(ingested_at) m FROM raw_alerts UNION ALL "
            "SELECT max(ingested_at) FROM exogenous_features) z"
        )).scalar_one()
    files = {}
    for p in sorted(out.glob("*")):
        if p.is_file():
            files[p.name] = {"bytes": p.stat().st_size, "sha256_16": _sha256(p)}
    manifest = {
        "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_rev": _git_rev(),
        "grain": grain,
        "ttl_hours": TTL_HOURS,
        "source_db_max_ingested_at": str(src_max),
        "row_counts": info,
        "source_table_rows": {k: int(len(v)) for k, v in frames.items()},
        "files": files,
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    return manifest


def _write_dictionary(path: Path) -> None:
    rows = [
        ("hour_ts", "timestamptz", "hourly_panel/feature_matrix", "Decision time t (UTC). Key."),
        ("oblast_id", "int", "oblasts", "Oblast id (1–27). Key."),
        ("lead_hours", "int", "hourly_panel", "Forecast horizon k∈1..6 (LONG only). Key."),
        ("y_alert_active", "bool", "hourly_panel", "LABEL: alert active at t+lead_hours (LONG)."),
        ("y_lead_1..y_lead_6", "bool", "hourly_panel", "LABELS at t+k for k=1..6 (WIDE)."),
        ("oblast_name", "str", "oblasts", "English oblast name (static)."),
        ("centroid_lat/lon", "double", "oblasts", "Oblast centroid (static; GNN/geo)."),
        ("temp_c/wind_speed/precip_mm/cloud_cover", "double", "exogenous_features(open_meteo)→feature_matrix", "Target-oblast weather AS-OF t (contemporaneous, leak-safe)."),
        ("self_alert_active", "bool", "raw_alerts→feature_matrix", "Was THIS oblast under alert AT t (autoregressive)."),
        ("neighbor_alert_count", "int", "raw_alerts+oblast_adjacency→feature_matrix", "# adjacent oblasts under alert AT t."),
        ("neighbor_alert_frac", "double", "raw_alerts+oblast_adjacency→feature_matrix", "Fraction of neighbors under alert AT t."),
        ("hour_of_day/dow/month", "int", "hour_ts", "Calendar parts (UTC), deterministic."),
        ("is_weekend", "bool", "hour_ts", "Sat/Sun (UTC)."),
        ("hour_sin/cos, dow_sin/cos", "double", "hour_ts", "Cyclical calendar encodings."),
        ("osint_mig31_airborne", "bool", "exogenous_features(telegram)", "ASOF state: MiG-31K airborne at t (TTL 6h). Leak-safe (event_ts≤t)."),
        ("osint_tu95_takeoff", "bool", "exogenous_features(telegram)", "ASOF state: Tu-95 takeoff active at t (TTL 6h)."),
        ("osint_mass_national", "bool", "exogenous_features(telegram)", "ASOF state: national mass-attack active at t (TTL 6h)."),
        ("osint_mass_oblast", "bool", "exogenous_features(telegram)", "ASOF state: oblast-scoped mass-attack active at t (TTL 6h)."),
        ("hours_since_mig31/tu95", "int|null", "exogenous_features(telegram)", "Hours since last MiG-31/Tu-95 event ≤ t (staleness; null if none yet)."),
        ("year", "int", "hour_ts", "Partition/CV key (UTC year)."),
    ]
    lines = [
        "# Data Dictionary — airraid analytical export",
        "",
        "Every feature is known **as-of `t = hour_ts`**; labels are at `t + lead`. The export is strictly",
        "read-only and out-of-database. Companion files: `edges.parquet` (GNN `edge_index` via `node_idx`),",
        "`oblasts.parquet` (node metadata + `node_idx`).",
        "",
        "| Column(s) | Dtype | Source | Meaning / leak-safety |",
        "|---|---|---|---|",
        *[f"| `{c}` | {d} | {s} | {m} |" for c, d, s, m in rows],
    ]
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- verification
def verify(out: Path) -> None:
    lp, wp, ep, op = out / LONG_NAME, out / WIDE_NAME, out / EDGES_NAME, out / OBLASTS_NAME
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")

    def q(sql: str):
        return con.execute(sql).fetchone()[0]

    long_rows = q(f"SELECT count(*) FROM read_parquet('{lp}')")
    wide_rows = q(f"SELECT count(*) FROM read_parquet('{wp}')")
    edges_rows = q(f"SELECT count(*) FROM read_parquet('{ep}')")
    obl_rows = q(f"SELECT count(*) FROM read_parquet('{op}')")
    long_pos = q(f"SELECT sum(CASE WHEN y_alert_active THEN 1 ELSE 0 END) FROM read_parquet('{lp}')")
    osint_on = q(
        f"SELECT count(*) FROM read_parquet('{lp}') WHERE osint_mig31_airborne OR osint_tu95_takeoff "
        f"OR osint_mass_national OR osint_mass_oblast"
    )
    feat_nulls = q(
        f"SELECT count(*) FROM read_parquet('{lp}') WHERE self_alert_active IS NULL OR neighbor_alert_count IS NULL "
        f"OR hour_sin IS NULL OR year IS NULL"
    )
    # weather NULLs come only from the pre-ERA5 edge (2022-02-24): 648 node cells × 6 leads in LONG, 648 in WIDE
    wx_nulls_long = q(f"SELECT count(*) FROM read_parquet('{lp}') WHERE temp_c IS NULL")
    wx_nulls_wide = q(f"SELECT count(*) FROM read_parquet('{wp}') WHERE temp_c IS NULL")
    wx_nulls_post_era5 = q(f"SELECT count(*) FROM read_parquet('{lp}') WHERE temp_c IS NULL AND hour_ts >= TIMESTAMPTZ '2022-02-25 00:00:00+00'")

    with engine.connect() as c:
        c.execute(text("SET default_transaction_read_only = on"))
        db_panel = c.execute(text("SELECT count(*) FROM hourly_panel")).scalar_one()
        db_panel_pos = c.execute(text("SELECT count(*) FROM hourly_panel WHERE y_alert_active")).scalar_one()
        db_grid = c.execute(text("SELECT count(*) FROM feature_matrix")).scalar_one()
        cat = c.execute(text(
            "SELECT string_agg(table_name, ',' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public'"
        )).scalar_one()

    checks = [
        ("long rows == hourly_panel", long_rows == db_panel, f"{long_rows} vs {db_panel}"),
        ("wide rows == feature_matrix grid", wide_rows == db_grid, f"{wide_rows} vs {db_grid}"),
        ("edges == 106", edges_rows == 106, str(edges_rows)),
        ("oblasts == 27", obl_rows == 27, str(obl_rows)),
        ("long positives == panel positives", long_pos == db_panel_pos, f"{long_pos} vs {db_panel_pos}"),
        ("OSINT states present (>0)", osint_on > 0, f"{osint_on} rows flagged"),
        ("no NULL in non-weather features", feat_nulls == 0, f"{feat_nulls} null rows"),
        ("long weather NULLs == 648×6 leads", wx_nulls_long == 648 * 6, f"{wx_nulls_long}"),
        ("wide weather NULLs == 648", wx_nulls_wide == 648, f"{wx_nulls_wide}"),
        ("all weather NULLs are pre-ERA5 edge", wx_nulls_post_era5 == 0, f"{wx_nulls_post_era5} post-2022-02-25"),
        ("catalog unchanged (7 known tables)", cat == "exogenous_features,feature_matrix,hourly_panel,ingest_errors,oblast_adjacency,oblasts,raw_alerts", cat),
    ]
    con.close()
    print("VERIFY:")
    ok = True
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}  — {detail}")
        ok = ok and passed
    print("ALL PASS ✅" if ok else "SOME CHECKS FAILED ❌")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only analytical export (Postgres → Parquet bundle)")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--grain", choices=["long", "wide", "both"], default="both")
    ap.add_argument("--bundle", action="store_true", help="(default behaviour) emit companions + manifest")
    ap.add_argument("--verify", action="store_true", help="verify an existing export against the DB")
    a = ap.parse_args()
    if a.verify:
        verify(a.out)
        return
    manifest = build(a.out, a.grain)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
