"""Offline OSINT collection agent — Telethon scrape + LOCAL Ollama parse → frozen osint_flags.csv.

Implements **Use case A** of plans/02 (§ "Static OSINT insert — one-time, frozen dataset"):
  • OSINT flags are a FROZEN historical dataset, NOT a live feed.
  • This collector is run **once, offline, by hand** (or via the MCP tool that wraps it). It is NOT a
    cron/scheduler/daemon and never time-updates the data.
  • Message parsing uses a **local Ollama** model only (no external provider). If the configured
    `LLM_MODEL` is not a local Ollama model, we resolve a real local one; if Ollama is unreachable we
    fall back to the deterministic regex parser. **No data is ever fabricated** — if Telegram auth is
    not available we stop gracefully and write nothing.

Auth policy: we use the saved `TELEGRAM_SESSION_STRING`. We **never** trigger an interactive SMS/code
prompt from inside the agent/server — if the session is missing or unauthorized we raise `AuthRequired`
so the caller can stop gracefully and ask the operator to authenticate manually (see README).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import requests

from airraid.config import settings
from airraid.scrape_telegram_osint import _LLM_SYS, _detect_regex, _is_candidate

_REPO = Path(__file__).resolve().parents[2]  # MCP/OSINT_agent/agent.py → repo root
OUT_DEFAULT = _REPO / "data" / "osint" / "osint_flags.csv"
_PREFERRED_LOCAL = ("llama3.1:latest", "llama3.1:8b", "qwen2.5:latest", "qwen2.5:3b-instruct", "mistral:latest")


class AuthRequired(RuntimeError):
    """Raised when Telegram needs interactive auth — caller stops gracefully (no prompt, no fabrication)."""


# --------------------------------------------------------------------------- local LLM resolution
def resolve_ollama_model() -> str | None:
    """Return a real LOCAL Ollama model name, ignoring external names (e.g. claude-*) in LLM_MODEL."""
    try:
        r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return None
    if not names:
        return None
    if settings.llm_model in names:  # honor the configured model only if it is actually local
        return settings.llm_model
    for pref in _PREFERRED_LOCAL:
        if pref in names:
            return pref
    return names[0]


def _detect_llm(text: str, model: str) -> list[dict] | None:
    try:
        r = requests.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": model, "format": "json", "stream": False,
                  "prompt": f"{_LLM_SYS}\n\nMESSAGE:\n{text}\n\nJSON:"},
            timeout=90,
        )
        r.raise_for_status()
        obj = json.loads(r.json()["response"])
    except (requests.RequestException, KeyError, ValueError):
        return None
    ob = str(obj.get("oblast") or "").strip()
    out: list[dict] = []
    for key in ("mig_31_airborne", "tu_95_takeoff", "mass_attack_active"):
        if obj.get(key):
            national = key != "mass_attack_active" or not ob
            out.append({"feature_key": key, "scope": "national" if national else "oblast",
                        "oblast": "" if national else ob, "value_bool": True})
    return out


def _detect(text: str, model: str | None) -> list[dict]:
    if model:
        llm = _detect_llm(text, model)
        if llm is not None:
            return llm
    return _detect_regex(text)  # deterministic fallback (regex), never fabricated


# --------------------------------------------------------------------------- Telegram (async, no prompt)
async def _gather_messages(since_dt: dt.datetime, until_dt: dt.datetime, limit: int | None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise AuthRequired("TELEGRAM_API_ID / TELEGRAM_API_HASH are not set in .env.")
    if not settings.telegram_session_string:
        raise AuthRequired(
            "No TELEGRAM_SESSION_STRING in .env. Authenticate ONCE manually (interactive code), then "
            "store the printed StringSession in .env. See MCP/OSINT_agent/README.md."
        )

    client = TelegramClient(StringSession(settings.telegram_session_string),
                            settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():  # never call .start() → never prompts for a code
            raise AuthRequired("Saved Telegram session is invalid/expired. Re-authenticate manually (README).")
        channels = [c.strip() for c in settings.telegram_channels.split(",") if c.strip()]
        out: list[tuple[str, dt.datetime, str]] = []
        for ch in channels:
            seen = 0
            async for msg in client.iter_messages(ch, offset_date=until_dt):
                if msg.date and msg.date < since_dt:
                    break
                text = (msg.message or "").strip()
                if not text or not _is_candidate(text):
                    continue
                out.append((ch, msg.date, text))
                seen += 1
                if limit and seen >= limit:
                    break
        return out
    finally:
        await client.disconnect()


async def collect_osint_flags(since: dt.date, until: dt.date | None = None,
                              limit: int | None = None, use_llm: bool = True,
                              out: Path = OUT_DEFAULT) -> dict:
    """ONE-TIME offline scrape → frozen CSV. Returns a summary dict. Raises AuthRequired (graceful)."""
    import csv

    until = until or dt.date.today()
    since_dt = dt.datetime.combine(since, dt.time.min, tzinfo=dt.timezone.utc)
    until_dt = dt.datetime.combine(until, dt.time.max, tzinfo=dt.timezone.utc)
    model = resolve_ollama_model() if use_llm else None

    raw = await _gather_messages(since_dt, until_dt, limit)  # Telegram I/O first

    rows: dict[tuple, dict] = {}  # offline parse (dedupe on feature_key,event_ts,scope,oblast)
    for _ch, date, text in raw:
        ev = date.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()
        for flag in _detect(text, model):
            rows[(flag["feature_key"], ev, flag["scope"], flag["oblast"])] = {"event_ts": ev, **flag}

    out.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["event_ts"], r["feature_key"]))
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_ts", "feature_key", "scope", "oblast", "value_bool"])
        w.writeheader()
        for r in ordered:
            w.writerow({**r, "value_bool": str(bool(r["value_bool"])).lower()})

    return {"flags_written": len(ordered), "candidates_scanned": len(raw),
            "channels": settings.telegram_channels, "model_used": model or "regex-fallback",
            "since": since.isoformat(), "until": until.isoformat(), "out": str(out)}
