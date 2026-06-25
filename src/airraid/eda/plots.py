"""Plot helpers — render the metrics INSIDE the image (plans/07 §2, CRITICAL rule).

Reuses the convention proven in `scripts/evaluate_horizons.py`: metrics in the title + an in-axes
text box, headless `Agg` backend. `Analysis.plot_texts` exposes every text artist drawn on the
figure so a test can assert the numbers are actually on the image (no OCR needed).
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Agg")  # headless — never opens a window
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.text as mtext  # noqa: E402


@dataclass
class Analysis:
    """A baseline-tool result: exact numbers + a base64 plot that carries those numbers."""
    test_result: dict
    plot_image: str               # base64 PNG
    plot_texts: list[str]         # every text string drawn on the figure (for verification)
    title: str
    tool: str = ""
    oblast: str = ""
    column: str = ""
    metrics_meta: dict = field(default_factory=dict)


def fmt_metric(v) -> str:
    """Single canonical formatter used by the plot box, the narrator, and the tests — so the
    string drawn on the image == the string quoted in the narrative."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt_metric(x) for x in v) + "]"
    return str(v)


def metrics_textbox(ax, metrics: dict, loc: str = "upper left") -> None:
    """Draw `metrics` as a monospace box inside `ax` (the metrics-in-plot enforcement)."""
    lines = [f"{k} = {fmt_metric(v)}" for k, v in metrics.items()]
    x, ha = (0.02, "left") if "left" in loc else (0.98, "right")
    y, va = (0.97, "top") if "upper" in loc else (0.03, "bottom")
    ax.text(x, y, "\n".join(lines), transform=ax.transAxes, ha=ha, va=va, fontsize=8.5,
            family="monospace",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.55", alpha=0.92))


def rendered_texts(fig) -> list[str]:
    return [t.get_text() for t in fig.findobj(mtext.Text) if t.get_text().strip()]


def finalize(fig, test_result: dict, title: str, *, tool="", oblast="", column="") -> Analysis:
    """Capture the drawn text, encode the figure to base64, close it, return an `Analysis`."""
    texts = rendered_texts(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return Analysis(test_result=test_result, plot_image=b64, plot_texts=texts, title=title,
                    tool=tool, oblast=oblast, column=column)


def b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64.encode("ascii"))
