"""One-time historical Telegram OSINT scrape → frozen `data/osint/osint_flags.csv`.

WHY THIS EXISTS (reconciling the asymmetric-ingestion architecture)
-------------------------------------------------------------------
The live `alerts.in.ua` poller is the ONLY scheduled job in this project. OSINT air-tactical flags
are a STATIC, FROZEN dataset: we collect them **once** with this *collector*, write a frozen CSV, and
`ingest_osint_static.py` inserts that CSV **once**. This module is therefore run by hand for the
historical backfill — it is NOT a cron, daemon, or APScheduler job. Re-running it simply refreshes /
extends the frozen CSV; nothing schedules it. (See plans/03 §A.0 + §D and
researches/exogenous-variables-research.md.)

PIPELINE
--------
    Telegram (Telethon, creds from .env)
      └─ iter historical messages (since the earliest alert date)
         └─ keyword pre-filter  (cheap, deterministic — avoids LLM calls on irrelevant chatter)
            └─ local Ollama parse (LLM_MODEL over OLLAMA_BASE_URL; deterministic regex fallback)
               └─ structured flags → data/osint/osint_flags.csv
                    columns: event_ts (ISO-8601 UTC), feature_key, scope (national|oblast),
                             oblast (name; blank if national), value_bool

FLAGS detected
--------------
    mig_31_airborne    — MiG-31K takeoff (Kinzhal carrier); national, very short lead → a k=1h feature
    tu_95_takeoff      — Tu-95MS strategic-bomber takeoff (Kh-101 cruise-missile precursor); national
    mass_attack_active — mass strike in progress (may be oblast-scoped)

CHANNELS
--------
Pinned by the operator in TELEGRAM_CHANNELS (default: kpszsu,air_alert_ua — official Air Force ЗСУ).
⚠ Fake Air Force channels exist (disinfo.detector.media). Prefer the numeric channel id over the @handle.

USAGE (run by a human — first run needs interactive Telegram auth unless TELEGRAM_SESSION_STRING is set)
------
    PYTHONPATH=src ./.venv/bin/python -m airraid.scrape_telegram_osint --since 2022-02-24 [--limit N] [--no-llm]
    # then insert the frozen CSV exactly once:
    PYTHONPATH=src ./.venv/bin/python -m airraid.ingest_osint_static
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

import requests

from .config import settings
from .reference import OBLASTS

OUT_DEFAULT = Path("data/osint/osint_flags.csv")

# ---------------------------------------------------------------------------
# Deterministic keyword detection (Ukrainian + transliteration). Used as a
# pre-filter (skip irrelevant messages) AND as the fallback when Ollama is down.
# ---------------------------------------------------------------------------
_MIG31 = re.compile(r"(міг|mig)[-\s]?31", re.I)
_TU95 = re.compile(r"(ту|tu)[-\s]?95", re.I)
# Takeoff/airborne root covers зліт/злет/зльот/зльоті and виліт/вильоту etc.
_TAKEOFF = re.compile(r"зл[іеьо]+т|вил[іеьо]+т|airborne|take[-\s]?off|пуск", re.I)
_LANDING = re.compile(r"посадк|land(ed|ing)|відб[іе]й|відмін", re.I)
_MASS = re.compile(r"масован|масова атака|mass(ive)?\s+(attack|strike)|ракетн\w*\s+удар", re.I)


def _uk_stem(uk_root: str) -> str:
    """Strip the adjectival oblast suffix so declined forms match (Харківська→харків, Запорізька→запорі)."""
    for suf in ("зька", "цька", "ська"):
        if uk_root.endswith(suf):
            return uk_root[: -len(suf)]
    return uk_root


# Oblast scan: (oblast_id, name_en lowercased, uk stem) — stem matches declined forms in free text.
_OBLAST_SCAN: list[tuple[int, str, str]] = [
    (oid, en.lower(), _uk_stem(uk.lower().split(" обл")[0].split(" авто")[0]))
    for oid, en, uk, _lat, _lon in OBLASTS
]


def _scan_oblast(text: str) -> str | None:
    low = text.lower()
    for _oid, en, uk_root in _OBLAST_SCAN:
        if (en and en in low) or (len(uk_root) >= 4 and uk_root in low):
            return en
    return None


def _detect_regex(text: str) -> list[dict]:
    """Return flag dicts inferred purely from keywords (deterministic fallback)."""
    out: list[dict] = []
    has_takeoff = bool(_TAKEOFF.search(text))
    cleared = bool(_LANDING.search(text))
    if _MIG31.search(text):
        out.append({"feature_key": "mig_31_airborne", "scope": "national",
                    "oblast": "", "value_bool": has_takeoff and not cleared})
    if _TU95.search(text):
        out.append({"feature_key": "tu_95_takeoff", "scope": "national",
                    "oblast": "", "value_bool": has_takeoff and not cleared})
    if _MASS.search(text):
        ob = _scan_oblast(text)
        out.append({"feature_key": "mass_attack_active",
                    "scope": "oblast" if ob else "national",
                    "oblast": ob or "", "value_bool": not cleared})
    return out


def _is_candidate(text: str) -> bool:
    return bool(_MIG31.search(text) or _TU95.search(text) or _MASS.search(text))


# ---------------------------------------------------------------------------
# Local Ollama parse (no external LLM provider). Strict JSON out; regex fallback.
# ---------------------------------------------------------------------------
_LLM_SYS = (
    "You extract Ukrainian air-threat OSINT flags from a single Telegram message. "
    "Reply ONLY with JSON: {\"mig_31_airborne\":bool, \"tu_95_takeoff\":bool, "
    "\"mass_attack_active\":bool, \"oblast\":string}. A *_takeoff/airborne flag is true ONLY if the "
    "message reports the aircraft taking off / being airborne NOW (not a landing/all-clear). "
    "'oblast' is the English oblast name if the message localizes the threat, else empty string."
)


def _detect_llm(text: str) -> list[dict] | None:
    try:
        r = requests.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": settings.llm_model, "format": "json", "stream": False,
                  "prompt": f"{_LLM_SYS}\n\nMESSAGE:\n{text}\n\nJSON:"},
            timeout=60,
        )
        r.raise_for_status()
        obj = json.loads(r.json()["response"])
    except (requests.RequestException, KeyError, ValueError):
        return None  # Ollama unreachable / bad JSON → caller uses regex fallback
    ob = str(obj.get("oblast") or "").strip()
    out: list[dict] = []
    for key in ("mig_31_airborne", "tu_95_takeoff", "mass_attack_active"):
        if obj.get(key):
            national = key != "mass_attack_active" or not ob
            out.append({"feature_key": key, "scope": "national" if national else "oblast",
                        "oblast": "" if national else ob, "value_bool": True})
    return out


def _detect(text: str, use_llm: bool) -> list[dict]:
    if use_llm:
        llm = _detect_llm(text)
        if llm is not None:
            return llm
    return _detect_regex(text)


# ---------------------------------------------------------------------------
# Telegram historical iteration (Telethon)
# ---------------------------------------------------------------------------
def _client():
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as e:  # pragma: no cover - dependency guard
        raise SystemExit("Telethon not installed. Run: ./.venv/bin/pip install 'telethon>=1.34'") from e
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")
    session = StringSession(settings.telegram_session_string) if settings.telegram_session_string else StringSession()
    return TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash)


def scrape(since: dt.date, until: dt.date, limit: int | None, use_llm: bool, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    channels = [c.strip() for c in settings.telegram_channels.split(",") if c.strip()]
    since_dt = dt.datetime.combine(since, dt.time.min, tzinfo=dt.timezone.utc)
    until_dt = dt.datetime.combine(until, dt.time.max, tzinfo=dt.timezone.utc)
    rows: dict[tuple, dict] = {}  # dedupe on (feature_key, event_ts, scope, oblast)

    client = _client()
    with client:
        if not settings.telegram_session_string:
            client.start(phone=settings.telegram_phone)  # interactive code prompt on first run
        for ch in channels:
            seen = 0
            for msg in client.iter_messages(ch, offset_date=until_dt, reverse=False):
                if msg.date and msg.date < since_dt:
                    break  # iterating newest→oldest; past the window
                text = (msg.message or "").strip()
                if not text or not _is_candidate(text):
                    continue
                ev = msg.date.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()
                for flag in _detect(text, use_llm):
                    key = (flag["feature_key"], ev, flag["scope"], flag["oblast"])
                    rows[key] = {"event_ts": ev, **flag}
                seen += 1
                if limit and seen >= limit:
                    break
            print(f"  channel @{ch}: {seen} candidate messages scanned")

    ordered = sorted(rows.values(), key=lambda r: (r["event_ts"], r["feature_key"]))
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_ts", "feature_key", "scope", "oblast", "value_bool"])
        w.writeheader()
        for r in ordered:
            w.writerow({**r, "value_bool": str(bool(r["value_bool"])).lower()})
    print(f"Wrote {len(ordered)} OSINT flags → {out}")
    return len(ordered)


def main() -> None:
    ap = argparse.ArgumentParser(description="One-time historical Telegram OSINT scrape → frozen CSV")
    ap.add_argument("--since", type=lambda s: dt.date.fromisoformat(s), default=dt.date(2022, 2, 24),
                    help="earliest message date (default 2022-02-24 — invasion start)")
    ap.add_argument("--until", type=lambda s: dt.date.fromisoformat(s), default=dt.date.today())
    ap.add_argument("--limit", type=int, default=None, help="max candidate messages per channel (testing)")
    ap.add_argument("--no-llm", action="store_true", help="skip Ollama; use the deterministic regex parser only")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args()
    print(f"Telegram OSINT scrape (ONE-TIME): {a.since} → {a.until} | llm={'off' if a.no_llm else settings.llm_model}")
    scrape(a.since, a.until, a.limit, use_llm=not a.no_llm, out=a.out)


if __name__ == "__main__":
    main()
