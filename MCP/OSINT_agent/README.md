# MCP OSINT Agent — static, one-time, offline

Collects Telegram-derived air-threat OSINT flags (`mig_31_airborne`, `tu_95_takeoff`,
`mass_attack_active`) into a **frozen** `data/osint/osint_flags.csv`, which is then inserted **once**
into `exogenous_features` (`source=telegram`).

## Why this respects Use case A (plans/02)
`plans/02-general-workflow-architecture.md` → *Use case A — Static OSINT insert (one-time, frozen
dataset)* requires:

| Rule (Use case A) | How this agent complies |
|---|---|
| Frozen historical dataset, **not a live feed** | The scrape is run **on demand, by hand**; it writes a static file. Nothing re-runs it. |
| **No daily scraper / cron / scheduler / dynamic pipeline** | The MCP server exposes **tools an operator invokes manually** — it is a tool-interface boundary, not a daemon/poller. |
| Single **insert-once**, Pydantic-validated, idempotent UPSERT | `ingest_osint_static.py` validates each row (`_OsintFlag`) and UPSERTs on `uq_exo`. Re-running is a no-op. |
| Parse raw export with a **local Ollama** model, once, offline | `agent.resolve_ollama_model()` picks a **local** model (ignores external names like `claude-*`); regex fallback if Ollama is down. |
| **No synthetic data** | If Telegram auth is unavailable, the agent raises `AuthRequired` and writes nothing. Flags are never fabricated. |

This is also the doc's **MCP-ready architecture**: deterministic logic stays in version-controlled
Python (`src/airraid/...`); the LLM/agent layer only orchestrates *which* tool to run.

## Tools
- `scrape_osint_flags(since="2022-02-24", until=None, limit=None, use_llm=True)` — one-time scrape → frozen CSV.
- `osint_status()` — frozen-file rows + per-flag breakdown + DB `telegram` row count.
- `ingest_osint_flags()` — insert the frozen CSV into `exogenous_features` exactly once.

## Register the server (Claude Desktop / Claude Code)
Merge `mcp_config.json` into your MCP client config, or for Claude Code:
```
claude mcp add airraid-osint /Users/annanechytailenko/Desktop/AirRaidAlerts/.venv/bin/python \
  /Users/annanechytailenko/Desktop/AirRaidAlerts/MCP/OSINT_agent/server.py
```

## Run / smoke-test
```bash
# list tools and exit (proves the server boots & registers tools)
PYTHONPATH=src ./.venv/bin/python MCP/OSINT_agent/server.py selftest

# run as a stdio MCP server (a client drives it; it blocks waiting for one)
PYTHONPATH=src ./.venv/bin/python MCP/OSINT_agent/server.py
```

## Telegram authentication (manual, one-time)
The agent uses the saved `TELEGRAM_SESSION_STRING` and **never** triggers an interactive SMS/code
prompt from inside the server. If the session is missing or expired it stops gracefully
(`status=auth_required`). To (re)authenticate once and print a reusable session string:

```bash
PYTHONPATH=src ./.venv/bin/python - <<'PY'
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from airraid.config import settings
with TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash) as c:
    c.start(phone=settings.telegram_phone)   # prompts for the SMS code interactively
    print("TELEGRAM_SESSION_STRING=", c.session.save())   # paste this into .env
PY
```
Then re-run `scrape_osint_flags`. After the CSV exists, run `ingest_osint_flags` (or
`python -m airraid.ingest_osint_static`).
