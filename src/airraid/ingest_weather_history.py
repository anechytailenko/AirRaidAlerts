"""Open-Meteo **Historical Archive** (ERA5 reanalysis) → exogenous_features (REAL data, no API key).

This backfills target-oblast weather for the FULL alert history — from the earliest `raw_alerts`
date (≈2022-02-25, the start of the full-scale invasion) up to the present — complementing
`ingest_weather.py`, which only covers a recent ~90-day window plus the 6-day forecast.

Same contract as the forecast loader so the two align in one table:
    feature_key ∈ {temp_c, wind_speed, precip_mm, cloud_cover}, scope=oblast, value_num,
    source=open_meteo, UQ(feature_key, event_ts, scope, oblast_id, source) = `uq_exo`.

Overlap with the forecast loader is intentional and safe: idempotent UPSERT overwrites overlapping
hours with the ERA5 reanalysis value (the more accurate *past* estimate). ERA5 has a ~5-day latency,
so the most recent days are served by `ingest_weather.py` instead.

Endpoint: https://archive-api.open-meteo.com/v1/archive  (free, non-commercial, no key).
Chunked by calendar year per oblast to keep each response small and make partial failures cheap to retry.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests
from sqlalchemy import func, select
from tenacity import retry, stop_after_attempt, wait_exponential

from .db import SessionLocal
from .ingest_weather import VARS, _upsert  # reuse the exact feature map + batched UPSERT
from .models import RawAlert, Scope, Source
from .reference import OBLASTS

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Floor for the backfill if the table is somehow empty (full-scale invasion start).
_DEFAULT_START = dt.date(2022, 2, 24)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, max=120), reraise=True)
def _fetch(lat: float, lon: float, start: str, end: str) -> dict:
    params = {
        "latitude": lat, "longitude": lon, "hourly": ",".join(VARS),
        "start_date": start, "end_date": end, "timezone": "UTC",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _earliest_alert_date() -> dt.date:
    """Step 1 result, read live from the DB so the backfill window is data-driven."""
    with SessionLocal() as s:
        d = s.scalar(select(func.min(RawAlert.started_at)))
    return d.date() if d else _DEFAULT_START


def _year_windows(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        y_end = min(dt.date(cur.year, 12, 31), end)
        yield cur.isoformat(), y_end.isoformat()
        cur = y_end + dt.timedelta(days=1)


def _parse_rows(oid: int, data: dict) -> list[dict]:
    hourly = data.get("hourly", {})
    times = pd.to_datetime(hourly.get("time", []), utc=True)
    rows: dict[tuple, dict] = {}
    for omv, fkey in VARS.items():
        for ts, val in zip(times, hourly.get(omv, [])):
            if val is None or pd.isna(val):
                continue
            ev = ts.to_pydatetime()
            rows[(fkey, ev)] = dict(
                event_ts=ev, feature_key=fkey, scope=Scope.oblast,
                oblast_id=oid, value_num=float(val), source=Source.open_meteo,
            )
    return list(rows.values())


def main() -> None:
    start = _earliest_alert_date()
    end = dt.date.today()  # ERA5 lags ~5d; nulls beyond availability are skipped (recent days via forecast loader)
    windows = list(_year_windows(start, end))
    print(f"Historical weather backfill: {start} -> {end} | {len(OBLASTS)} oblasts × {len(windows)} yearly windows")
    grand = 0
    for oid, name_en, _name_uk, lat, lon in OBLASTS:
        o_total = 0
        for s_date, e_date in windows:
            data = _fetch(float(lat), float(lon), s_date, e_date)
            o_total += _upsert(_parse_rows(oid, data))
        grand += o_total
        print(f"  oblast {oid:2d} {name_en:16s} rows={o_total}")
    print(f"TOTAL historical weather rows upserted: {grand}")


if __name__ == "__main__":
    main()
