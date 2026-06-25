"""Deterministic, read-only EDA layer for the Narrative Analyst Agent (plans/07 §3).

These are the *authoritative* statistical + plotting functions; the MCP tools (and the LangGraph
agent) merely wrap them, so the statistics stay version-controlled and unit-tested — never
re-implemented inside the LLM (plans/02 MCP-ready principle). Every function reads the read-only
parquet export and returns an `Analysis` carrying exact numbers + a base64 plot with the metrics
drawn ON the image.
"""
from __future__ import annotations

from .plots import Analysis, fmt_metric
from .stats import (
    ALERT_COLUMN,
    analyze_distribution,
    analyze_seasonality,
    get_summary_statistics,
    plot_acf_pacf,
    test_stationarity,
)

BASELINE_TOOLS = {
    "analyze_seasonality": analyze_seasonality,
    "plot_acf_pacf": plot_acf_pacf,
    "test_stationarity": test_stationarity,
    "get_summary_statistics": get_summary_statistics,
    "analyze_distribution": analyze_distribution,
}

__all__ = [
    "Analysis", "fmt_metric", "ALERT_COLUMN", "BASELINE_TOOLS",
    "analyze_seasonality", "plot_acf_pacf", "test_stationarity",
    "get_summary_statistics", "analyze_distribution",
]
