"""Pure payload→view helpers (plans/08 §4). No Dash imports → unit-testable against a mock payload.

The data-flow rule (plans/08 §3): `description` + `test_result` → chat reply (right);
`plot_image` → image src (left).
"""
from __future__ import annotations

from ..eda import fmt_metric  # single canonical formatter (shared with the agent's plots)


def format_metrics(test_result: dict | None) -> str:
    """`test_result` → a compact markdown metrics block (numbers rendered EXACTLY as the agent gave them)."""
    if not test_result:
        return ""
    lines = [f"- `{k}` = {fmt_metric(v)}" for k, v in test_result.items()]
    return "**Metrics**\n" + "\n".join(lines)


def chat_reply_markdown(payload: dict) -> str:
    """Right-side chat reply = the narrative description + the exact metrics."""
    parts = [payload.get("description", "").strip()]
    metrics = format_metrics(payload.get("test_result"))
    if metrics:
        parts.append(metrics)
    tool = payload.get("tool_used")
    if tool:
        tag = "dynamic tool" if payload.get("is_dynamic_tool") else tool
        parts.append(f"<small>via `{tag}`</small>")
    return "\n\n".join(p for p in parts if p)


def image_src(payload: dict) -> str | None:
    """Left-side panel = the base64 PNG as an <img> data URI, or None when the answer has no plot."""
    b64 = payload.get("plot_image")
    if not b64:
        return None
    return f"data:image/png;base64,{b64}"


def image_caption(payload: dict) -> str:
    bits = [payload.get("tool_used", "")]
    return " · ".join(b for b in bits if b)
