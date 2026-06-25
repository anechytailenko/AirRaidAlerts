"""Frontend tests (plans/08 §6) — the page must correctly parse a mock AnalystResponse payload.

Run: PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_frontend.py -q
"""
from __future__ import annotations

import base64

import pytest

from airraid.eda import fmt_metric
from airraid.schemas import AnalystResponse
from airraid.ui import render

# a real 1x1 PNG so the base64 actually decodes to a valid image
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def mock_payload() -> dict:
    """Matches the agent's AnalystResponse schema (plans/07 §2)."""
    return {
        "description": "Seasonal decomposition of `self_alert_active` for Kyiv.",
        "plot_image": _PNG_B64,
        "test_result": {"peak_hour": 18, "seasonal_strength": 0.4231, "n": 1234},
        "tool_used": "analyze_seasonality",
        "is_dynamic_tool": False,
    }


def safety_payload() -> dict:
    return {"description": "Request refused for safety: read-only.", "plot_image": None,
            "test_result": None, "tool_used": "safety_refusal", "is_dynamic_tool": False}


# --------------------------------------------------------------------------- schema match
def test_mock_payload_matches_agent_schema():
    AnalystResponse(**mock_payload())
    AnalystResponse(**safety_payload())


# --------------------------------------------------------------------------- chat rendering (right)
def test_chat_reply_contains_description_and_all_metrics():
    md = render.chat_reply_markdown(mock_payload())
    assert "Seasonal decomposition" in md
    tr = mock_payload()["test_result"]
    for k, v in tr.items():
        assert k in md, f"metric key {k} missing from chat reply"
        assert fmt_metric(v) in md, f"metric value for {k} missing from chat reply"
    assert "analyze_seasonality" in md  # provenance tag


def test_safety_reply_has_no_metrics_block():
    md = render.chat_reply_markdown(safety_payload())
    assert "refused" in md.lower()
    assert "Metrics" not in md


# --------------------------------------------------------------------------- image decoding (left)
def test_image_src_is_decodable_png():
    src = render.image_src(mock_payload())
    assert src.startswith("data:image/png;base64,")
    raw = base64.b64decode(src.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "left panel must decode a real PNG"


def test_image_src_none_when_no_plot():
    assert render.image_src(safety_payload()) is None


# --------------------------------------------------------------------------- client roundtrip
def test_local_client_roundtrip_through_agent():
    from airraid.ui.client import LocalAnalystClient
    out = LocalAnalystClient().ask("seasonality of alerts in Kyiv")
    assert out["tool_used"] == "analyze_seasonality"
    assert out["plot_image"] and out["test_result"]
    # the full round-trip must still render correctly
    assert render.image_src(out) is not None
    assert "seasonal_strength" in render.chat_reply_markdown(out)


# --------------------------------------------------------------------------- app structure
def test_app_builds_two_columns_without_kpi_cards():
    from airraid.ui.app import app  # noqa: F401  (import side-effect builds the layout)
    from airraid.ui.layout import build_layout
    tree = str(build_layout())
    # the chat input + the left image container exist
    assert "user-input" in tree and "left-image" in tree and "chat-window" in tree
    # KPI cards are REMOVED (plans/08 §1)
    for kpi in ("Total alert hours", "Alert base rate", "Longest single alert", "Peak month"):
        assert kpi not in tree, f"KPI card '{kpi}' must be removed"


def test_render_history_builds_bubbles():
    from airraid.ui.layout import render_history
    bubbles = render_history([{"role": "user", "text": "hi"},
                              {"role": "assistant", "text": "**hello**"}])
    assert len(bubbles) == 2
