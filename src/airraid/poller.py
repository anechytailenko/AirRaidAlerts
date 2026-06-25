"""Live alerts.in.ua poller — the ONLY scheduled job (APScheduler).

Polls currently-active alerts, validates via Pydantic, idempotent-upserts into `raw_alerts`
(source=alerts_in_ua), and closes (`ended_at`) rows that have dropped out of the active set.

Usage:
  python -m airraid.poller once    # single real poll cycle
  python -m airraid.poller run     # continuous APScheduler loop (blocking)
"""
from __future__ import annotations

import datetime as dt
import sys

import requests
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from tenacity import retry, stop_after_attempt, wait_exponential, wait_random

from .config import settings
from .db import SessionLocal
from .models import AlertType, IngestError, RawAlert, Source
from .reference import resolve_oblast
from .schemas import RawAlertEvent

ACTIVE_URL = "https://api.alerts.in.ua/v1/alerts/active.json"
_PERMANENT_SIREN_OBLASTS = {4, 14}  # Crimea, Luhansk — permanent sirens (excluded, matches dataset policy)
_TYPE_MAP = {
    "air_raid": AlertType.air_raid,
    "artillery_shelling": AlertType.artillery,
    "urban_fights": AlertType.urban_combat,
    "chemical": AlertType.chemical,
    "nuclear": AlertType.nuclear,
}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=60) + wait_random(0, 2), reraise=True)
def _fetch() -> dict:
    if not settings.alerts_in_ua_token:
        raise RuntimeError("ALERTS_IN_UA_TOKEN is not set in .env")
    r = requests.get(
        ACTIVE_URL,
        headers={"Authorization": f"Bearer {settings.alerts_in_ua_token}"},
        timeout=30,
    )
    if r.status_code == 429:  # transient — let tenacity retry (honors backoff)
        raise RuntimeError("HTTP 429 rate limited")
    r.raise_for_status()
    return r.json()


def poll_once() -> dict:
    data = _fetch()
    alerts = data.get("alerts", []) if isinstance(data, dict) else (data or [])

    rows: dict[tuple[int, object], dict] = {}
    errors: list[tuple[str, str, str]] = []
    for a in alerts:
        # Roll every sub-region (raion / hromada / city) up to its PARENT oblast — oblast-grain target.
        # `location_oblast` is present on every alert and names the parent oblast.
        region_name = a.get("location_oblast") or a.get("location_title") or ""
        oid = resolve_oblast(region_name)
        if oid is None:
            errors.append(("resolve", f"unresolved region: {region_name}", region_name))
            continue
        if oid in _PERMANENT_SIREN_OBLASTS:  # Crimea / Luhansk permanent sirens — excluded
            continue
        try:
            ev = RawAlertEvent(
                oblast_id=oid,
                started_at=a.get("started_at"),
                ended_at=None,
                alert_type=_TYPE_MAP.get(a.get("alert_type"), AlertType.air_raid),
                source=Source.alerts_in_ua,
                external_id=str(a.get("id")) if a.get("id") is not None else None,
            )
        except ValidationError as e:
            errors.append(("validate", str(e).replace("\n", " ")[:400], title))
            continue
        rows[(oid, ev.started_at)] = dict(
            oblast_id=ev.oblast_id, started_at=ev.started_at, ended_at=None,
            alert_type=ev.alert_type, source=ev.source, external_id=ev.external_id,
        )

    upserted = _upsert(list(rows.values()))
    closed = _close_ended(set(rows.keys()))
    _log_errors(errors)
    res = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "active": len(alerts),
           "upserted": upserted, "closed": closed, "errors": len(errors)}
    return res


def _upsert(values: list[dict]) -> int:
    if not values:
        return 0
    with SessionLocal() as s:
        stmt = insert(RawAlert).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_raw_alert", set_={"external_id": stmt.excluded.external_id}
        )
        s.execute(stmt)
        s.commit()
    return len(values)


def _close_ended(active_keys: set[tuple[int, object]]) -> int:
    """Mark alerts_in_ua rows that are open but no longer in the active set as ended (now)."""
    closed = 0
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as s:
        open_rows = s.execute(
            select(RawAlert).where(RawAlert.source == Source.alerts_in_ua, RawAlert.ended_at.is_(None))
        ).scalars().all()
        for r in open_rows:
            if (r.oblast_id, r.started_at) not in active_keys:
                r.ended_at = now
                closed += 1
        s.commit()
    return closed


def _log_errors(errors: list[tuple[str, str, str]]) -> None:
    if not errors:
        return
    with SessionLocal() as s:
        for stage, msg, payload in errors[:500]:
            s.execute(insert(IngestError).values(
                source=Source.alerts_in_ua.value, stage=stage, error=msg[:2000], payload=str(payload)[:500]))
        s.commit()


def run() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        lambda: print(poll_once()), "interval",
        seconds=settings.poll_interval_seconds, next_run_time=dt.datetime.now(),
        max_instances=1, coalesce=True,
    )
    print(f"Live poller started (every {settings.poll_interval_seconds}s). Ctrl-C to stop.")
    sched.start()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "run":
        run()
    else:
        print(poll_once())
