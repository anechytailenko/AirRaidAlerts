"""Open-Meteo weather → exogenous_features (REAL data, no API key).

Per-oblast centroid; `past_days` history + `forecast_days` (the latter is the known-future input
usable for horizons k<=6h, per plans/01 §D). Idempotent UPSERT; source=open_meteo. Target-oblast
weather is the PRIMARY weather signal (interception-driven; see researches/exogenous §5).
"""
from __future__ import annotations

import pandas as pd
import requests
from sqlalchemy.dialects.postgresql import insert
from tenacity import retry, stop_after_attempt, wait_exponential

from .db import SessionLocal
from .models import ExogenousFeature, Scope, Source
from .reference import OBLASTS

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Open-Meteo hourly variable -> our feature_key
VARS = {
    "temperature_2m": "temp_c",
    "wind_speed_10m": "wind_speed",
    "precipitation": "precip_mm",
    "cloud_cover": "cloud_cover",
}
PAST_DAYS = 92
FORECAST_DAYS = 6
BATCH = 5000


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=60), reraise=True)
def _fetch(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat, "longitude": lon, "hourly": ",".join(VARS),
        "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS, "timezone": "UTC",
    }
    r = requests.get(FORECAST_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _upsert(values: list[dict]) -> int:
    if not values:
        return 0
    with SessionLocal() as s:
        for j in range(0, len(values), BATCH):
            chunk = values[j:j + BATCH]
            stmt = insert(ExogenousFeature).values(chunk)
            stmt = stmt.on_conflict_do_update(constraint="uq_exo", set_={"value_num": stmt.excluded.value_num})
            s.execute(stmt)
        s.commit()
    return len(values)


def main() -> None:
    total = 0
    for oid, name_en, _name_uk, lat, lon in OBLASTS:
        data = _fetch(lat, lon)
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
        n = _upsert(list(rows.values()))
        total += n
        print(f"  oblast {oid:2d} {name_en:16s} rows={n}")
    print(f"TOTAL weather rows upserted: {total}")


if __name__ == "__main__":
    main()
