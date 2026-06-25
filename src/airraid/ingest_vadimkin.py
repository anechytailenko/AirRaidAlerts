"""Milestone 3/4 — backfill `raw_alerts` from the public Vadimkin dataset (REAL data).

Flow: download CSV → parse (UTC) → resolve oblast → Pydantic-validate → idempotent UPSERT.
Unresolved/invalid rows are dead-lettered to `ingest_errors`, never silently dropped.
"""
from __future__ import annotations

import io

import pandas as pd
import requests
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from tenacity import retry, stop_after_attempt, wait_exponential

from .db import SessionLocal
from .models import AlertType, IngestError, RawAlert, Source
from .reference import resolve_oblast
from .schemas import RawAlertEvent

URL = "https://raw.githubusercontent.com/Vadimkin/ukrainian-air-raid-sirens-dataset/main/datasets/volunteer_data_en.csv"
SOURCE = Source.vadimkin_volunteer
BATCH = 5000


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=60), reraise=True)
def fetch_df() -> pd.DataFrame:
    r = requests.get(URL, timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def main() -> None:
    df = fetch_df()
    print(f"Downloaded {len(df)} rows; columns={list(df.columns)}")

    started = pd.to_datetime(df["started_at"], utc=True, errors="coerce")
    finished = pd.to_datetime(df["finished_at"], utc=True, errors="coerce")
    naive = df["naive"].astype(str).str.strip().str.lower().isin(["true", "1"])
    region = df["region"].astype(str)

    # Resolve the (small) set of distinct region strings once.
    region_map = {r: resolve_oblast(r) for r in region.unique()}
    unresolved = {r: int((region == r).sum()) for r, oid in region_map.items() if oid is None}

    rows: dict[tuple[int, object], dict] = {}  # natural-key dedup within batch
    errors: list[tuple[str, str, str]] = []
    for i in range(len(df)):
        oid = region_map[region.iat[i]]
        if oid is None:
            errors.append(("resolve", f"unresolved region: {region.iat[i]}", region.iat[i]))
            continue
        st = started.iat[i]
        if pd.isna(st):
            errors.append(("parse", "missing/invalid started_at", region.iat[i]))
            continue
        st = st.to_pydatetime()
        en = None if pd.isna(finished.iat[i]) else finished.iat[i].to_pydatetime()
        try:
            ev = RawAlertEvent(
                oblast_id=oid, started_at=st, ended_at=en,
                alert_type=AlertType.air_raid, source=SOURCE, is_naive=bool(naive.iat[i]),
            )
        except ValidationError as e:
            errors.append(("validate", str(e).replace("\n", " ")[:500], region.iat[i]))
            continue
        rows[(oid, st)] = dict(
            oblast_id=ev.oblast_id, started_at=ev.started_at, ended_at=ev.ended_at,
            alert_type=ev.alert_type, source=ev.source, is_naive=ev.is_naive,
        )

    values = list(rows.values())
    print(f"Valid (deduped): {len(values)} | Errors: {len(errors)} | Unresolved regions: {unresolved}")

    upserted = _upsert(values)
    _log_errors(errors)
    print(f"UPSERT complete — {upserted} rows applied to raw_alerts; {len(errors)} dead-lettered.")


def _upsert(values: list[dict]) -> int:
    if not values:
        return 0
    with SessionLocal() as s:
        for j in range(0, len(values), BATCH):
            chunk = values[j:j + BATCH]
            stmt = insert(RawAlert).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_raw_alert",
                set_={"ended_at": stmt.excluded.ended_at, "is_naive": stmt.excluded.is_naive},
            )
            s.execute(stmt)
        s.commit()
    return len(values)


def _log_errors(errors: list[tuple[str, str, str]]) -> None:
    if not errors:
        return
    with SessionLocal() as s:
        for stage, msg, payload in errors[:2000]:
            s.execute(insert(IngestError).values(
                source=SOURCE.value, stage=stage, error=msg[:2000], payload=str(payload)[:500],
            ))
        s.commit()


if __name__ == "__main__":
    main()
