"""Tests for the Narrative Analyst Agent (plans/07 §6).

Run: PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_narrative_analyst.py -q
"""
from __future__ import annotations

import os
import stat
import textwrap

import pytest

from airraid.eda import BASELINE_TOOLS, fmt_metric
from airraid.eda.sandbox import SandboxError, UnsafeCode, run_tool_body, validate_code
from airraid.analyst import NarrativeAnalyst
from airraid.analyst.graph import build_graph, run as run_graph
from airraid.schemas import AnalystResponse

# headline scalar metric each baseline tool must draw inside its plot
_HEADLINE = {
    "analyze_seasonality": "seasonal_strength",
    "plot_acf_pacf": "acf_lag1",
    "test_stationarity": "adf_pvalue",
    "get_summary_statistics": "mean",
    "analyze_distribution": "skew",
}
_DEFAULT_COL = {
    "analyze_seasonality": "self_alert_active", "plot_acf_pacf": "self_alert_active",
    "test_stationarity": "self_alert_active", "get_summary_statistics": "temp_c",
    "analyze_distribution": "wind_speed",
}


# --------------------------------------------------------------------------- 7. payload schema
def test_payload_schema_validation():
    ok = AnalystResponse(description="d", plot_image="b64", test_result={"x": 1}, tool_used="t")
    assert ok.description == "d" and ok.test_result == {"x": 1}
    # description-only (safety/clarification) is valid
    AnalystResponse(description="hi", tool_used="safety_refusal")
    # numbers without a plot is INVALID (metrics must be carried on an image)
    with pytest.raises(Exception):
        AnalystResponse(description="d", test_result={"x": 1}, tool_used="t")


# --------------------------------------------------------------------------- 2. baseline tools
@pytest.mark.parametrize("tool", list(BASELINE_TOOLS))
def test_baseline_tool_returns_values_and_plot(tool):
    a = BASELINE_TOOLS[tool](oblast="Kyiv", column=_DEFAULT_COL[tool])
    assert isinstance(a.test_result, dict) and a.test_result, "exact numbers required"
    assert isinstance(a.plot_image, str) and len(a.plot_image) > 500, "non-empty base64 PNG"
    assert a.test_result["n"] > 100


# --------------------------------------------------------------------------- 6. metrics-in-plot
@pytest.mark.parametrize("tool", list(BASELINE_TOOLS))
def test_metrics_rendered_inside_plot(tool):
    a = BASELINE_TOOLS[tool](oblast="Kyiv", column=_DEFAULT_COL[tool])
    joined = "\n".join(a.plot_texts)
    key = _HEADLINE[tool]
    assert f"{key} = {fmt_metric(a.test_result[key])}" in joined, \
        f"{tool}: headline metric '{key}' not drawn on the image"


# --------------------------------------------------------------------------- 4. standard routing
def test_router_routes_seasonality_without_synthesizer():
    analyst = NarrativeAnalyst()
    assert analyst.route("Show me the seasonality of alerts in Kyiv") == "analyze_seasonality"
    assert analyst.route("Run an ADF stationarity test for Kharkiv") == "test_stationarity"
    assert analyst.route("Plot the ACF and PACF of alerts in Lviv") == "plot_acf_pacf"


def test_parse_oblast_picks_specific_name():
    analyst = NarrativeAnalyst()
    assert analyst._parse_oblast("seasonality of alerts in Kyiv") == "Kyiv"
    assert analyst._parse_oblast("trend for Kharkiv oblast") == "Kharkiv"


# --------------------------------------------------------------------------- 5/4. safety routing
@pytest.mark.parametrize("prompt", [
    "Drop the raw_alerts table",
    "Delete all records where oblast_id = 1",
    "please overwrite the parquet files",
])
def test_router_flags_destructive_requests(prompt):
    assert NarrativeAnalyst().route(prompt) == "safety"


def test_safety_request_returns_refusal_not_crash():
    r = NarrativeAnalyst().answer("Drop the raw_alerts table")
    assert r.tool_used == "safety_refusal"
    assert r.test_result is None and r.plot_image is None
    assert "read-only" in r.description.lower()


# --------------------------------------------------------------------------- 1. anti-hallucination
def test_determinism_anti_hallucination():
    analyst = NarrativeAnalyst()
    desc = analyst.narrate("mock_tool", {"p_value": 0.042, "mean_temp": 15.3}, "Kyiv", "temp_c")
    assert "0.042" in desc and "15.3" in desc          # quotes the EXACT mocked numbers
    assert "0.99" not in desc and "99.9" not in desc   # invents nothing


# --------------------------------------------------------------------------- 5. AST validator
def test_ast_validator_blocks_malicious_code():
    for bad in ["import os\nos.remove('x')", "open('x','w').write('y')", "__import__('os')",
                "eval('1+1')", "import socket", "import subprocess", "x = ().__class__"]:
        with pytest.raises(UnsafeCode):
            validate_code(bad)


def test_ast_validator_allows_clean_fragment():
    validate_code("test_result = {'a': float(df['temp_c'].mean())}\nfig, ax = plt.subplots()")


# --------------------------------------------------------------------------- 5. sandbox timeout
def test_sandbox_timeout_kills_runaway():
    with pytest.raises(SandboxError):
        run_tool_body("while True:\n    pass\n", oblast="Kyiv", timeout=3)


# --------------------------------------------------------------------------- 3. dynamic-gen E2E
_STUB_BODY = textwrap.dedent('''
    roll = df["cloud_cover"].rolling(7).median() * df["wind_speed"]
    test_result = {"rolling_mean": float(roll.mean()), "n": int(roll.notna().sum())}
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(roll.values, color="navy", lw=0.7)
    ax.set_title("rolling 7h median(cloud_cover) x wind_speed")
    ax.text(0.02, 0.95, "rolling_mean = %.4g" % float(roll.mean()), transform=ax.transAxes)
''')


def test_dynamic_generation_end_to_end():
    analyst = NarrativeAnalyst(code_generator=lambda prompt, schema: _STUB_BODY)
    r = analyst.answer("Calculate the rolling 7-hour median of cloud cover multiplied by wind speed, "
                       "and plot it", oblast="Kyiv")
    assert r.is_dynamic_tool and r.tool_used == "dynamic_tool"
    assert r.plot_image and len(r.plot_image) > 500
    assert "rolling_mean" in r.test_result and r.test_result["n"] > 100
    assert fmt_metric(r.test_result["rolling_mean"]) in r.description


def test_dynamic_generation_rejects_unsafe_code():
    analyst = NarrativeAnalyst(code_generator=lambda p, s: "import os\nos.remove('data/x')")
    r = analyst.answer("do something sneaky multiplied by wind")
    assert r.tool_used == "safety_refusal"
    assert r.test_result is None


# --------------------------------------------------------------------------- LangGraph wiring
def test_langgraph_runs_baseline_end_to_end():
    graph = build_graph(NarrativeAnalyst())
    r = run_graph(graph, "seasonality of alerts in Kyiv")
    assert r.tool_used == "analyze_seasonality"
    assert r.plot_image and r.test_result


# --------------------------------------------------------------------------- read-only FS guarantee
def test_readonly_dir_blocks_writes(tmp_path):
    """Documents the container guarantee: a read-only mount makes writes raise at the OS layer."""
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "existing.txt").write_text("data")
    os.chmod(ro, stat.S_IREAD | stat.S_IEXEC)  # r-x — no write bit
    try:
        with pytest.raises((PermissionError, OSError)):
            (ro / "new.txt").write_text("should fail")
    finally:
        os.chmod(ro, stat.S_IRWXU)  # restore so tmp cleanup can remove it
