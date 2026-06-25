"""Dash app for the Analysis tab (plans/08). Wires chat input → analyst client → render → panels.

Run:  PYTHONPATH=src ./.venv/bin/python -m airraid.ui.app
By default the agent runs in-process; set ANALYST_API_URL=http://host:port to call the FastAPI boundary.
"""
from __future__ import annotations

from dash import Dash, Input, Output, State, ctx, no_update

from .client import get_client
from .layout import SUGGESTIONS, build_layout, render_history
from .render import chat_reply_markdown, image_caption, image_src

app = Dash(__name__, title="Ukraine Air-Raid Alert Intelligence System",
           suppress_callback_exceptions=True)
app.layout = build_layout()

_client = None


def client():
    global _client
    if _client is None:
        _client = get_client()
    return _client


@app.callback(
    Output("chat-history", "data"),
    Output("last-image", "data"),
    Output("left-caption", "children"),
    Output("user-input", "value"),
    Input("send-btn", "n_clicks"),
    Input("user-input", "n_submit"),
    State("user-input", "value"),
    State("chat-history", "data"),
    prevent_initial_call=True,
)
def on_submit(_n_clicks, _n_submit, value, history):
    """Append the user turn, call the agent, append the assistant turn, push the plot to the left."""
    if not value or not value.strip():
        return no_update, no_update, no_update, no_update
    q = value.strip()
    history = (history or []) + [{"role": "user", "text": q}]
    img, caption = None, no_update
    try:
        payload = client().ask(q)
        reply = chat_reply_markdown(payload)
        img = image_src(payload)
        if img:
            caption = image_caption(payload)
    except Exception as e:  # noqa: BLE001 — never raise into the UI; degrade gracefully
        reply = f"⚠️ The analyst could not complete that request: {e}"
    history = history + [{"role": "assistant", "text": reply}]
    return history, (img if img else no_update), caption, ""


@app.callback(Output("chat-window", "children"), Input("chat-history", "data"))
def render_chat(history):
    return render_history(history or [])


@app.callback(
    Output("left-image", "src"),
    Output("left-image", "style"),
    Output("left-placeholder", "style"),
    Input("last-image", "data"),
    State("left-image", "style"),
    prevent_initial_call=True,
)
def render_image(src, img_style):
    if not src:
        return no_update, no_update, no_update
    shown = {**(img_style or {}), "display": "block"}
    return src, shown, {"display": "none"}


@app.callback(
    Output("user-input", "value", allow_duplicate=True),
    [Input(f"chip-{i}", "n_clicks") for i in range(len(SUGGESTIONS))],
    prevent_initial_call=True,
)
def fill_from_chip(*_clicks):
    tid = ctx.triggered_id
    if isinstance(tid, str) and tid.startswith("chip-"):
        return SUGGESTIONS[int(tid.split("-")[1])]
    return no_update


def main() -> None:
    import os
    app.run(debug=bool(os.environ.get("DASH_DEBUG")), host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()
