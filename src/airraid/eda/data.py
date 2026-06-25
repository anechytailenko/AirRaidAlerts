"""Read-only access to the analytical parquet export (plans/07 §4 — data is never mutated here).

All loads are `read_parquet` only; this module exposes no write path. On Kaggle/Docker the export is
mounted read-only, so even an attempted write would raise at the OS layer; here we simply never write.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

# src/airraid/eda/data.py  ->  repo root
_REPO = Path(__file__).resolve().parents[3]

# The contemporaneous alert-occurrence series (was THIS oblast under alert AT t) — the canonical
# "alerts" target for seasonality / ACF / stationarity (data_dictionary.md: self_alert_active).
ALERT_COLUMN = "self_alert_active"


def exports_dir() -> Path:
    return Path(os.environ.get("AIRRAID_EXPORTS_DIR", str(_REPO / "data" / "exports")))


def wide_path() -> Path:
    return exports_dir() / "airraid_analytical_wide.parquet"


@lru_cache(maxsize=1)
def load_wide() -> pd.DataFrame:
    """The wide export (one row per (hour_ts, oblast_id)) — loaded once, cached, read-only."""
    df = pd.read_parquet(wide_path())
    df["hour_ts"] = pd.to_datetime(df["hour_ts"], utc=True)
    return df


@lru_cache(maxsize=1)
def _oblast_index() -> dict:
    df = load_wide()[["oblast_id", "oblast_name"]].drop_duplicates()
    return {
        "name_to_id": {str(r.oblast_name).lower(): int(r.oblast_id) for r in df.itertuples()},
        "id_to_name": {int(r.oblast_id): str(r.oblast_name) for r in df.itertuples()},
    }


def resolve_oblast(oblast) -> tuple[int | None, str]:
    """Map a name / id / None → (oblast_id|None, display_name). None / 'national' → aggregate."""
    if oblast is None or (isinstance(oblast, str) and oblast.strip().lower() in
                          ("", "national", "ukraine", "all", "none", "country")):
        return None, "National"
    idx = _oblast_index()
    if isinstance(oblast, str):
        key = oblast.strip().lower()
        oid = idx["name_to_id"].get(key)
        if oid is None:  # forgiving contains-match ("kyiv" → "Kyiv City"? prefer exact "Kyiv")
            cands = [i for nm, i in idx["name_to_id"].items() if key == nm]
            cands = cands or [i for nm, i in idx["name_to_id"].items() if nm.startswith(key)]
            cands = cands or [i for nm, i in idx["name_to_id"].items() if key in nm]
            if cands:
                oid = sorted(cands)[0]
        if oid is None:
            raise ValueError(f"unknown oblast: {oblast!r}")
        return oid, idx["id_to_name"][oid]
    oid = int(oblast)
    return oid, idx["id_to_name"].get(oid, f"oblast {oid}")


def series(column: str, oblast=None) -> pd.Series:
    """Hourly series of `column` for one oblast (or the national hourly mean), tz-aware, sorted."""
    df = load_wide()
    if column not in df.columns:
        raise ValueError(f"unknown column: {column!r}")
    oid, _ = resolve_oblast(oblast)
    if oid is None:
        s = df.groupby("hour_ts")[column].mean()
    else:
        s = df[df["oblast_id"] == oid].set_index("hour_ts")[column]
    s = s.astype(float).sort_index()
    s.name = column
    return s


def hourly_series(column: str, oblast=None) -> pd.Series:
    """`series` resampled to a regular hourly grid (gaps→0) — required by decompose/ADF/ACF."""
    s = series(column, oblast)
    return s.asfreq("h").interpolate(limit_direction="both").fillna(0.0)


def feature_frame(oblast=None) -> pd.DataFrame:
    """All numeric features for one oblast (or national hourly mean), time-indexed — the sandbox `df`."""
    df = load_wide()
    oid, _ = resolve_oblast(oblast)
    if oid is None:
        g = df.groupby("hour_ts").mean(numeric_only=True)
    else:
        g = df[df["oblast_id"] == oid].set_index("hour_ts").select_dtypes("number")
    return g.sort_index()


def feature_columns() -> list[str]:
    return list(load_wide().select_dtypes("number").columns)
