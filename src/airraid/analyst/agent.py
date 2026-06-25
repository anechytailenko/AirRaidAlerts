"""`NarrativeAnalyst` — router + deterministic narrator + dynamic-tool synthesizer (plans/07)."""
from __future__ import annotations

import re
from typing import Callable

from ..eda import BASELINE_TOOLS, fmt_metric
from ..eda import data as _data
from ..eda.sandbox import SandboxError, UnsafeCode, run_tool_body
from ..schemas import AnalystResponse

# CRITICAL system-prompt rule, verbatim from plans/07 §2 — fed to the code synthesizer and documented.
SYSTEM_PROMPT = (
    "You are the Narrative Analyst for a Ukraine air-raid forecasting project. You are STRICTLY "
    "read-only and you NEVER fabricate numbers — every figure you state comes from executed Python "
    "over the read-only export. Every analytical answer returns a Description, exact Metrics, and a "
    "Plot. CRITICAL: every plot you produce MUST render the key numerical metrics directly INSIDE the "
    "image (as the title, an annotation, or an in-axes text box) alongside clear legends and axis "
    "labels. The frontend has no separate numbers pane; if a metric is not drawn on the plot, the user "
    "will never see it. A plot that omits its metrics is an invalid answer and must be regenerated."
)

# Routing vocabulary (plans/07 §3) — keyword → baseline tool.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "test_stationarity": ("stationar", "adf", "dickey", "unit root", "kpss"),
    "plot_acf_pacf": ("acf", "pacf", "autocorrel", "partial autocorrel", "lag structure"),
    "analyze_seasonality": ("season", "seasonal", "decompos", "trend", "peak hour", "hour of day",
                            "time of day", "hourly pattern", "diurnal"),
    "analyze_distribution": ("distribution", "histogram", "multiplicative", "additive", "skew",
                             "drift", "regime", "density"),
    "get_summary_statistics": ("summary", "statistics", "describe", "mean", "median", "variance",
                               "percentile", "average", "std"),
}

_DESTRUCTIVE = re.compile(r"\b(drop|delete|truncate|erase|overwrite|wipe|remove|rm|corrupt)\b", re.I)
_DATA_OBJ = re.compile(r"\b(table|record|records|row|rows|parquet|file|files|data|dataset|"
                       r"artifact|artifacts|weights|database|column|csv)\b", re.I)
_COMPLEX = re.compile(r"\b(rolling|multiplied|multiply|times|product|divided|ratio|bivariate|"
                      r"versus|interaction|combined|correlation between)\b|\bvs\b", re.I)

# light NL → column aliasing
_COL_ALIASES = {
    "temperature": "temp_c", "temp": "temp_c", "wind": "wind_speed", "precip": "precip_mm",
    "rain": "precip_mm", "cloud": "cloud_cover", "alert": "self_alert_active",
    "neighbor": "neighbor_alert_frac", "neighbour": "neighbor_alert_frac",
}
_CONTINUOUS_DEFAULT = "temp_c"


class NarrativeAnalyst:
    """Stateless orchestrator. Inject `code_generator` (prompt, schema) -> python body to make the
    dynamic synthesizer deterministic in tests; default uses the local Ollama model."""

    def __init__(self, code_generator: Callable[[str, str], str] | None = None,
                 dynamic_timeout: int = 20):
        self._gen = code_generator
        self._dynamic_timeout = dynamic_timeout

    # ------------------------------------------------------------------ routing
    def route(self, prompt: str) -> str:
        p = prompt.lower()
        if _DESTRUCTIVE.search(p) and _DATA_OBJ.search(p):
            return "safety"
        if _COMPLEX.search(p):
            return "dynamic"
        for tool, kws in _KEYWORDS.items():
            if any(k in p for k in kws):
                return tool
        return "dynamic"

    def _parse_oblast(self, prompt: str):
        p = prompt.lower()
        names = list(_data._oblast_index()["id_to_name"].values())
        hits = [n for n in names if n.lower() in p]
        return max(hits, key=len) if hits else None  # most specific name wins

    def _parse_column(self, prompt: str, tool: str) -> str:
        p = prompt.lower()
        for col in _data.feature_columns():
            if col.lower() in p:
                return col
        for alias, col in _COL_ALIASES.items():
            if alias in p:
                return col
        if tool in ("get_summary_statistics", "analyze_distribution"):
            return "wind_speed" if tool == "analyze_distribution" else _CONTINUOUS_DEFAULT
        return _data.ALERT_COLUMN

    # ------------------------------------------------------------------ narration (deterministic)
    def narrate(self, tool_used: str, test_result: dict, name: str, column: str,
                is_dynamic: bool = False) -> str:
        pairs = "; ".join(f"{k} = {fmt_metric(v)}" for k, v in test_result.items())
        leads = {
            "analyze_seasonality": f"Seasonal decomposition of `{column}` for {name}.",
            "plot_acf_pacf": f"Autocorrelation (ACF/PACF) of `{column}` for {name}.",
            "test_stationarity": f"Stationarity tests (ADF + KPSS) on `{column}` for {name}.",
            "get_summary_statistics": f"Summary statistics of `{column}` for {name}.",
            "analyze_distribution": f"Distribution & additive-vs-multiplicative regime of `{column}` for {name}.",
        }
        lead = "Dynamically-synthesized analysis" + f" for {name}." if is_dynamic else \
            leads.get(tool_used, f"Analysis ({tool_used}) of `{column}` for {name}.")
        return (f"{lead} Key results — {pairs}. All figures are computed deterministically over the "
                f"read-only export and are rendered on the attached plot.")

    # ------------------------------------------------------------------ per-route handlers
    def baseline_response(self, prompt: str, oblast=None, column=None, tool=None) -> AnalystResponse:
        tool = tool or self.route(prompt)
        oblast = oblast if oblast is not None else self._parse_oblast(prompt)
        column = column or self._parse_column(prompt, tool)
        analysis = BASELINE_TOOLS[tool](oblast=oblast, column=column)
        desc = self.narrate(tool, analysis.test_result, analysis.oblast or "National", column)
        return AnalystResponse(description=desc, plot_image=analysis.plot_image,
                               test_result=analysis.test_result, tool_used=tool)

    def dynamic_response(self, prompt: str, oblast=None, column=None) -> AnalystResponse:
        oblast = oblast if oblast is not None else self._parse_oblast(prompt)
        try:
            body = self._generate_code(prompt)
        except Exception as e:  # noqa: BLE001 — codegen offline/unavailable → graceful (no fabrication)
            return AnalystResponse(
                description=f"Could not synthesize a tool for this request (code generator "
                            f"unavailable: {e}). No numbers were produced.",
                tool_used="dynamic_tool_unavailable", is_dynamic_tool=True)
        try:
            res = run_tool_body(body, oblast=oblast, timeout=self._dynamic_timeout)
        except UnsafeCode as e:
            return self.safety_response(prompt, reason=f"the generated code was rejected by the "
                                                       f"security validator ({e})")
        except SandboxError as e:
            return AnalystResponse(
                description=f"The synthesized tool failed to execute safely ({e}). No numbers were "
                            f"produced; nothing was written to the read-only data.",
                tool_used="dynamic_tool_error", is_dynamic_tool=True)
        name = (self._resolve_name(oblast))
        desc = self.narrate("dynamic_tool", res["test_result"], name, column or "(custom)",
                            is_dynamic=True)
        return AnalystResponse(description=desc, plot_image=res["plot_image"],
                               test_result=res["test_result"], tool_used="dynamic_tool",
                               is_dynamic_tool=True)

    def safety_response(self, prompt: str, reason: str | None = None) -> AnalystResponse:
        why = reason or ("this agent is strictly read-only — it can analyze the data but cannot "
                         "modify, delete, or overwrite any table, file, or model artifact")
        return AnalystResponse(
            description=f"Request refused for safety: {why}. The data/exports and artifacts are "
                        f"mounted read-only, so no destructive operation is possible. Ask me to "
                        f"*analyze* the data instead (seasonality, stationarity, ACF/PACF, summary "
                        f"statistics, distribution, or a custom metric).",
            tool_used="safety_refusal")

    # ------------------------------------------------------------------ entrypoint
    def answer(self, prompt: str, oblast=None, column=None) -> AnalystResponse:
        route = self.route(prompt)
        if route == "safety":
            return self.safety_response(prompt)
        if route == "dynamic":
            return self.dynamic_response(prompt, oblast, column)
        return self.baseline_response(prompt, oblast, column, tool=route)

    # ------------------------------------------------------------------ helpers
    def _resolve_name(self, oblast) -> str:
        try:
            return _data.resolve_oblast(oblast)[1]
        except Exception:  # noqa: BLE001
            return "National"

    def _generate_code(self, prompt: str) -> str:
        if self._gen is not None:
            return self._gen(prompt, _SCHEMA_HINT)
        return _ollama_code_generator(prompt, _SCHEMA_HINT)


# --------------------------------------------------------------------------- dynamic-tool template
_SCHEMA_HINT = (
    "Write a Python FRAGMENT (no imports, no function def). Available names: `df` (a time-indexed "
    "pandas DataFrame of numeric features for the requested oblast), `pd`, `np`, `plt`, `sns`, "
    "`load(column, oblast=None)`, and statsmodels `acf,pacf,adfuller,kpss,seasonal_decompose`. "
    "Columns include: temp_c, wind_speed, precip_mm, cloud_cover, self_alert_active, "
    "neighbor_alert_count, neighbor_alert_frac, osint_mig31_airborne, osint_tu95_takeoff, "
    "hours_since_mig31, hours_since_tu95, y_lead_1..y_lead_6. You MUST assign `test_result` (a dict "
    "of exact numbers) and build a matplotlib figure `fig` that renders those numbers inside the "
    "image (title + an in-axes text box). Do not import anything; do not read/write files."
)


def _ollama_code_generator(prompt: str, schema: str) -> str:
    """Default synthesizer: ask the local Ollama model for a code fragment (temp 0). Network-free in
    tests because tests inject a stub generator instead."""
    import requests

    from ..config import settings
    full = (f"{SYSTEM_PROMPT}\n\n{schema}\n\nUSER REQUEST:\n{prompt}\n\n"
            "Return ONLY the Python fragment, no prose, no markdown fences.")
    r = requests.post(f"{settings.ollama_base_url}/api/generate",
                      json={"model": settings.llm_model, "stream": False,
                            "options": {"temperature": 0}, "prompt": full}, timeout=120)
    r.raise_for_status()
    text = r.json().get("response", "")
    if "```" in text:  # strip accidental code fences
        text = re.sub(r"^.*?```(?:python)?\n", "", text, flags=re.S)
        text = text.split("```")[0]
    return text.strip()
