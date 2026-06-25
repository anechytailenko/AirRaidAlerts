"""Dash layout for the Analysis tab — two columns: visuals (left) + chat (right) (plans/08 §2).

No KPI cards (plans/08 §1). Pure component construction; callbacks live in `app.py`.
"""
from __future__ import annotations

from dash import dcc, html

# --- palette (dark, echoing demo/web_01.png) ---
BG = "#0e1117"
PANEL = "#161b26"
PANEL2 = "#1c2230"
BORDER = "#2a3242"
ACCENT = "#2dd4bf"
TEXT = "#e6edf3"
MUTED = "#8b98a9"

SUGGESTIONS = [
    "Show the seasonality of alerts in Kyiv",
    "Is the alert series for Kharkiv stationary?",
    "Plot the ACF and PACF of alerts in Lviv",
    "Distribution of wind speed in Odesa",
]
GREETING = ("Hi — I'm the **Narrative Analyst**. Ask me about the air-raid data for any oblast or "
            "period (seasonality, stationarity, ACF/PACF, summary statistics, distribution, or a custom "
            "metric). I'll put the **chart on the left** and the **findings here**.")


def _bubble(role: str, text: str):
    is_user = role == "user"
    return html.Div(
        dcc.Markdown(text, dangerously_allow_html=True, link_target="_blank",
                     style={"margin": 0}),
        style={
            "alignSelf": "flex-end" if is_user else "flex-start",
            "maxWidth": "92%",
            "background": ACCENT if is_user else PANEL2,
            "color": "#06281f" if is_user else TEXT,
            "border": f"1px solid {'transparent' if is_user else BORDER}",
            "borderRadius": "12px",
            "padding": "8px 12px",
            "margin": "6px 0",
            "fontSize": "14px",
            "lineHeight": "1.45",
        },
    )


def render_history(history: list[dict]):
    return [_bubble(m.get("role", "assistant"), m.get("text", "")) for m in (history or [])]


def _header():
    chip = lambda t: html.Span(t, style={"color": MUTED, "fontSize": "12px", "marginLeft": "16px"})
    tab = lambda t, active: html.Span(
        t, style={"padding": "6px 14px", "borderRadius": "8px", "fontSize": "14px",
                  "fontWeight": 600, "marginRight": "8px",
                  "background": ACCENT if active else "transparent",
                  "color": "#06281f" if active else MUTED,
                  "border": f"1px solid {BORDER if not active else 'transparent'}"})
    return html.Div([
        html.Div([
            html.Span("◢", style={"color": ACCENT, "marginRight": "10px", "fontSize": "18px"}),
            html.Span("Ukraine Air-Raid Alert Intelligence System",
                      style={"fontWeight": 700, "fontSize": "16px"}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div([tab("Analysis", True), tab("Prediction", False)],
                 style={"display": "flex", "alignItems": "center"}),
        html.Div([chip("● Pipeline active"), chip("27 oblasts monitored")],
                 style={"display": "flex", "alignItems": "center"}),
    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
              "padding": "12px 20px", "borderBottom": f"1px solid {BORDER}", "background": PANEL})


def _left_panel():
    return html.Div([
        html.Div("Visual", style={"color": MUTED, "fontSize": "12px", "textTransform": "uppercase",
                                   "letterSpacing": "1px", "marginBottom": "10px"}),
        html.Div([
            html.Div("📊  Ask a question on the right — the generated chart appears here.",
                     id="left-placeholder",
                     style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                            "height": "100%", "color": MUTED, "fontSize": "15px", "textAlign": "center",
                            "padding": "0 30px"}),
            html.Img(id="left-image", src="", style={"display": "none", "maxWidth": "100%",
                                                     "maxHeight": "100%", "objectFit": "contain"}),
        ], style={"flex": 1, "display": "flex", "alignItems": "center", "justifyContent": "center",
                  "background": PANEL2, "border": f"1px solid {BORDER}", "borderRadius": "12px",
                  "overflow": "hidden", "minHeight": "420px"}),
        html.Div(id="left-caption", style={"color": MUTED, "fontSize": "12px", "marginTop": "8px"}),
    ], style={"flex": "1 1 62%", "display": "flex", "flexDirection": "column", "padding": "18px"})


def _right_panel():
    chips = [html.Button(s, id=f"chip-{i}", n_clicks=0,
                         style={"background": "transparent", "color": ACCENT, "fontSize": "12px",
                                "border": f"1px solid {BORDER}", "borderRadius": "14px",
                                "padding": "5px 10px", "margin": "0 6px 6px 0", "cursor": "pointer"})
             for i, s in enumerate(SUGGESTIONS)]
    return html.Div([
        html.Div("Narrative Analyst", style={"fontWeight": 700, "fontSize": "15px",
                                             "marginBottom": "2px"}),
        html.Div("Ask about the alert data for any oblast or period.",
                 style={"color": MUTED, "fontSize": "12px", "marginBottom": "10px"}),
        dcc.Loading(
            html.Div(id="chat-window", children=render_history([{"role": "assistant", "text": GREETING}]),
                     style={"flex": 1, "overflowY": "auto", "display": "flex",
                            "flexDirection": "column", "paddingRight": "4px"}),
            type="dot", color=ACCENT,
        ),
        html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "margin": "10px 0 6px"}),
        html.Div([
            dcc.Input(id="user-input", type="text", placeholder="Ask about the data…",
                      debounce=False, n_submit=0,
                      style={"flex": 1, "background": BG, "color": TEXT, "border": f"1px solid {BORDER}",
                             "borderRadius": "10px", "padding": "10px 12px", "fontSize": "14px"}),
            html.Button("▸", id="send-btn", n_clicks=0,
                        style={"marginLeft": "8px", "background": ACCENT, "color": "#06281f",
                               "border": "none", "borderRadius": "10px", "padding": "0 16px",
                               "fontSize": "18px", "cursor": "pointer", "fontWeight": 700}),
        ], style={"display": "flex", "alignItems": "stretch"}),
    ], style={"flex": "1 1 38%", "display": "flex", "flexDirection": "column", "padding": "18px",
              "borderLeft": f"1px solid {BORDER}", "background": PANEL, "minHeight": "0"})


def build_layout():
    return html.Div([
        dcc.Store(id="chat-history", data=[{"role": "assistant", "text": GREETING}]),
        dcc.Store(id="last-image", data=None),
        _header(),
        html.Div([_left_panel(), _right_panel()],
                 style={"display": "flex", "flex": 1, "minHeight": "0",
                        "height": "calc(100vh - 58px)"}),
    ], style={"background": BG, "color": TEXT, "height": "100vh", "display": "flex",
              "flexDirection": "column", "fontFamily": "Inter, system-ui, sans-serif"})
