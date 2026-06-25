"""MCP server for the Narrative Analyst Agent (plans/07 §5 Phase 2).

Thin wrapper: each tool delegates to the authoritative `airraid.eda` functions / the `airraid.analyst`
orchestrator. The deterministic statistics stay version-controlled in `src/`; this server only exposes
them over MCP. Read-only — it never writes to the export or artifacts.

Run as an MCP stdio server:   python MCP/Narrative_Analyst/server.py
Smoke-test (list tools, exit): python MCP/Narrative_Analyst/server.py selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `airraid` (src/) importable regardless of launch cwd (mirrors MCP/OSINT_agent/server.py).
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for p in (str(_REPO / "src"), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from airraid.eda import (  # noqa: E402
    analyze_distribution as _analyze_distribution,
    analyze_seasonality as _analyze_seasonality,
    get_summary_statistics as _get_summary_statistics,
    plot_acf_pacf as _plot_acf_pacf,
    test_stationarity as _test_stationarity,
)
from airraid.analyst import NarrativeAnalyst  # noqa: E402

mcp = FastMCP("airraid-analyst")
_analyst = NarrativeAnalyst()


def _payload(analysis, tool: str) -> dict:
    return {"description": f"{tool} · {analysis.oblast} · {analysis.column}",
            "test_result": analysis.test_result, "plot_image": analysis.plot_image,
            "tool_used": tool, "is_dynamic_tool": False}


@mcp.tool()
def analyze_seasonality(oblast: str | None = None, column: str = "self_alert_active") -> dict:
    """Trend/seasonal/residual decomposition + hour-of-day profile (metrics drawn on the plot)."""
    return _payload(_analyze_seasonality(oblast=oblast, column=column), "analyze_seasonality")


@mcp.tool()
def plot_acf_pacf(oblast: str | None = None, column: str = "self_alert_active", nlags: int = 48) -> dict:
    """ACF & PACF with significance bands and significant-lag indices (drawn on the plot)."""
    return _payload(_plot_acf_pacf(oblast=oblast, column=column, nlags=nlags), "plot_acf_pacf")


@mcp.tool()
def test_stationarity(oblast: str | None = None, column: str = "self_alert_active") -> dict:
    """Augmented Dickey-Fuller + KPSS; statistics/p-values printed inside the plot."""
    return _payload(_test_stationarity(oblast=oblast, column=column), "test_stationarity")


@mcp.tool()
def get_summary_statistics(oblast: str | None = None, column: str = "temp_c",
                           start: str | None = None, end: str | None = None) -> dict:
    """Mean/median/variance/percentiles over a window; histogram with the numbers on it."""
    return _payload(_get_summary_statistics(oblast=oblast, column=column, start=start, end=end),
                    "get_summary_statistics")


@mcp.tool()
def analyze_distribution(oblast: str | None = None, column: str = "wind_speed") -> dict:
    """Histogram + additive-vs-multiplicative regime check + mean drift (metrics drawn on the plot)."""
    return _payload(_analyze_distribution(oblast=oblast, column=column), "analyze_distribution")


@mcp.tool()
def ask_analyst(prompt: str, oblast: str | None = None, column: str | None = None) -> dict:
    """Full natural-language entrypoint: routes to a baseline tool or synthesizes one (sandboxed).
    Returns the standardized AnalystResponse payload (description + plot_image + test_result)."""
    return _analyst.answer(prompt, oblast=oblast, column=column).model_dump()


def _selftest() -> None:
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    print("MCP server 'airraid-analyst' OK — registered tools:")
    for t in tools:
        print(f"  - {t.name}: {(t.description or '').splitlines()[0]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        mcp.run()  # stdio transport — waits for an MCP client
