"""MCP server for the airraid OSINT agent (Use case A — static, one-time, offline).

WHY AN MCP SERVER HERE (justified strictly against plans/02 Use case A)
-----------------------------------------------------------------------
Use case A mandates a **one-time, offline, insert-once** OSINT flow with **no daily scraper / cron /
scheduler / dynamic pipeline**. This server respects that exactly: it exposes the OSINT collection +
insert as **on-demand MCP tools an operator invokes manually**. It is a *tool-interface boundary*
(the project's "MCP-ready architecture" principle) — NOT a daemon that polls Telegram on a schedule.
The deterministic logic (parsing, validation, UPSERT) stays in version-controlled Python; the server
only exposes it. Nothing here time-updates the frozen dataset on its own.

TOOLS
  • scrape_osint_flags(since, until, limit, use_llm) → run the ONE-TIME scrape → frozen osint_flags.csv
  • osint_status()                                   → report frozen-file + DB ingestion state
  • ingest_osint_flags()                             → insert the frozen CSV into exogenous_features ONCE

Run as an MCP stdio server:   python MCP/OSINT_agent/server.py
Smoke-test (list tools, exit): python MCP/OSINT_agent/server.py selftest
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Make `airraid` (src/) and this agent dir importable regardless of launch cwd.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for p in (str(_REPO / "src"), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mcp.server.fastmcp import FastMCP  # noqa: E402

import agent  # noqa: E402  (MCP/OSINT_agent/agent.py)

mcp = FastMCP("airraid-osint")


@mcp.tool()
async def scrape_osint_flags(since: str = "2022-02-24", until: str | None = None,
                             limit: int | None = None, use_llm: bool = True) -> dict:
    """Run the ONE-TIME offline OSINT scrape (Telethon + local Ollama) → frozen data/osint/osint_flags.csv.

    Not scheduled; produces a frozen file. If Telegram needs manual auth, returns status=auth_required
    with instructions (no SMS prompt is ever triggered, no data is fabricated).
    """
    try:
        summary = await agent.collect_osint_flags(
            since=dt.date.fromisoformat(since),
            until=dt.date.fromisoformat(until) if until else None,
            limit=limit, use_llm=use_llm,
        )
        return {"status": "ok", **summary}
    except agent.AuthRequired as e:
        return {"status": "auth_required", "message": str(e),
                "action": "Authenticate Telegram manually once (see MCP/OSINT_agent/README.md), "
                          "then re-run this tool. Nothing was written."}


@mcp.tool()
def osint_status() -> dict:
    """Report whether the frozen osint_flags.csv exists (rows + flag breakdown) and DB ingestion count."""
    out = agent.OUT_DEFAULT
    info: dict = {"frozen_csv": str(out), "exists": out.exists()}
    if out.exists():
        import csv
        with out.open() as f:
            rows = list(csv.DictReader(f))
        breakdown: dict[str, int] = {}
        for r in rows:
            breakdown[r["feature_key"]] = breakdown.get(r["feature_key"], 0) + 1
        info.update(csv_rows=len(rows), flag_breakdown=breakdown)
    try:
        from sqlalchemy import func, select
        from airraid.db import SessionLocal
        from airraid.models import ExogenousFeature, Source
        with SessionLocal() as s:
            info["db_telegram_rows"] = s.scalar(
                select(func.count()).select_from(ExogenousFeature).where(ExogenousFeature.source == Source.telegram)
            )
    except Exception as e:  # noqa: BLE001 - status tool must never crash
        info["db_telegram_rows"] = f"unavailable: {e}"
    return info


@mcp.tool()
def ingest_osint_flags() -> dict:
    """Insert the frozen osint_flags.csv into exogenous_features EXACTLY ONCE (idempotent UPSERT)."""
    from sqlalchemy import func, select
    from airraid.db import SessionLocal
    from airraid.ingest_osint_static import main as ingest_main
    from airraid.models import ExogenousFeature, Source
    ingest_main()
    with SessionLocal() as s:
        n = s.scalar(select(func.count()).select_from(ExogenousFeature).where(ExogenousFeature.source == Source.telegram))
    return {"status": "ok", "db_telegram_rows": n}


def _selftest() -> None:
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    print("MCP server 'airraid-osint' OK — registered tools:")
    for t in tools:
        print(f"  - {t.name}: {(t.description or '').splitlines()[0]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        mcp.run()  # stdio transport — waits for an MCP client
