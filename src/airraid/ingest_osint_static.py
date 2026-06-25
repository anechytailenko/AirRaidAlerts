"""Static OSINT insert — ONE-TIME, frozen historical dataset.

Strategy (per the asymmetric ingestion decision): OSINT/Telegram flags are treated as a FROZEN
dataset. There is NO scraper, cron, scheduler, or dynamic pipeline. This script processes a real
frozen export exactly once and idempotent-UPSERTs it into `exogenous_features` (source=telegram).

Expected real export (supply a genuine file — no synthetic data is ever generated):
  data/osint/osint_flags.csv
  columns: event_ts (ISO-8601 UTC), feature_key (e.g. mig_31_airborne, tu_95_takeoff),
           scope (national|oblast), oblast (name, blank if national), value_bool (true|false)

If the file is absent, the script inserts NOTHING and says so.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import AwareDatetime, BaseModel, ValidationError
from sqlalchemy.dialects.postgresql import insert

from .db import SessionLocal
from .models import ExogenousFeature, IngestError, Scope, Source
from .reference import resolve_oblast

# Anchored to the repo root so it agrees with the MCP collector regardless of launch cwd.
FROZEN = Path(__file__).resolve().parents[2] / "data" / "osint" / "osint_flags.csv"


class _OsintFlag(BaseModel):
    event_ts: AwareDatetime
    feature_key: str
    scope: Scope
    oblast_id: int | None = None
    value_bool: bool


def main() -> None:
    if not FROZEN.exists():
        print(
            f"NO-OP: no frozen OSINT export found at '{FROZEN}'. Nothing inserted "
            f"(no synthetic data generated). Supply a real export to ingest the static OSINT flags once."
        )
        return

    df = pd.read_csv(FROZEN)
    ts = pd.to_datetime(df["event_ts"], utc=True, errors="coerce")
    rows: dict[tuple, dict] = {}
    errors: list[tuple[str, str, str]] = []
    for i in range(len(df)):
        scope_raw = str(df["scope"].iat[i]).strip().lower()
        oblast_id = None
        if scope_raw == "oblast":
            oblast_id = resolve_oblast(str(df["oblast"].iat[i]))
            if oblast_id is None:
                errors.append(("resolve", f"unresolved oblast: {df['oblast'].iat[i]}", str(df["oblast"].iat[i])))
                continue
        try:
            flag = _OsintFlag(
                event_ts=ts.iat[i].to_pydatetime() if pd.notna(ts.iat[i]) else None,
                feature_key=str(df["feature_key"].iat[i]).strip(),
                scope=Scope(scope_raw),
                oblast_id=oblast_id,
                value_bool=bool(df["value_bool"].iat[i]),
            )
        except (ValidationError, ValueError) as e:
            errors.append(("validate", str(e).replace("\n", " ")[:300], str(df.iloc[i].to_dict())[:200]))
            continue
        key = (flag.feature_key, flag.event_ts, flag.scope.value, flag.oblast_id, Source.telegram.value)
        rows[key] = dict(
            event_ts=flag.event_ts, feature_key=flag.feature_key, scope=flag.scope,
            oblast_id=flag.oblast_id, value_bool=flag.value_bool, source=Source.telegram,
        )

    values = list(rows.values())
    if values:
        with SessionLocal() as s:
            stmt = insert(ExogenousFeature).values(values)
            stmt = stmt.on_conflict_do_update(constraint="uq_exo", set_={"value_bool": stmt.excluded.value_bool})
            s.execute(stmt)
            if errors:
                for stage, msg, payload in errors[:500]:
                    s.execute(insert(IngestError).values(source=Source.telegram.value, stage=stage, error=msg, payload=payload))
            s.commit()
    print(f"Static OSINT insert (ONE-TIME): applied={len(values)} flags; errors={len(errors)}.")


if __name__ == "__main__":
    main()
