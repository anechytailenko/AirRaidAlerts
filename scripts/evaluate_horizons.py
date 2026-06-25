#!/usr/bin/env python3
"""Per-oblast, per-horizon evaluation + visualization of the trained A3T-GCN on the 2026 holdout test.

Pipeline:
  1. Load the artifact bundle (best_model.pt, model_config.json, feature_scaler.json, edge_index.pt,
     node_mapping.json, thresholds.json) from `artifacts/` (or `artifacts/stgnn/`).
  2. Reconstruct the held-out TEST split from `data/exports/` (same logic as training: `test_start`
     origins, train-fit scaler applied) and run one inference pass for all 6 horizons.
  3. For EACH oblast build a 2x3 grid (one subplot per horizon k=1..6): predicted P(alert) as a line,
     actual alerts as shaded background, with per-(oblast,horizon) PR-AUC / F1-macro / ROC-AUC in the
     subplot title. Saved to `plots/per_oblast/horizon_eval_<oblast>.png`.
  4. Emit a master metrics table comparing all 27 oblasts (printed + `plots/per_oblast/metrics_summary.md`)
     and a per-(oblast,horizon) CSV.

Run: PYTHONPATH=src ./.venv/bin/python scripts/evaluate_horizons.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

import matplotlib
matplotlib.use("Agg")  # headless: write PNGs, never open a window
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ml.config import Config  # noqa: E402
from ml.dataset import A3TGCNWindowDataset, StandardScaler, _ts, load_panel, time_origins  # noqa: E402
from ml.model import A3TGCN  # noqa: E402

from sklearn.metrics import average_precision_score, f1_score, roc_auc_score  # noqa: E402

PLOTS = ROOT / "plots" / "per_oblast"


# --------------------------------------------------------------------------- loading
def _find_artifacts_dir() -> Path:
    for cand in (ROOT / "artifacts", ROOT / "artifacts" / "stgnn"):
        if (cand / "best_model.pt").exists():
            return cand
    raise FileNotFoundError("could not find best_model.pt under artifacts/ or artifacts/stgnn/")


def load_bundle(adir: Path):
    cfg_json = json.loads((adir / "model_config.json").read_text())
    model = A3TGCN(cfg_json["in_channels"], cfg_json["hidden"], cfg_json["horizon"],
                   cfg_json["num_layers"], cfg_json["dropout"])
    model.load_state_dict(torch.load(adir / "best_model.pt", map_location="cpu"))
    model.eval()

    edge_index = torch.load(adir / "edge_index.pt", map_location="cpu")
    sd = json.loads((adir / "feature_scaler.json").read_text())
    scaler = StandardScaler(mean=np.asarray(sd["mean"], dtype=np.float32),
                            std=np.asarray(sd["std"], dtype=np.float32))
    mapping = json.loads((adir / "node_mapping.json").read_text())
    idx_to_name = {int(k): v for k, v in mapping["idx_to_name"].items()}
    idx_to_oblast = {int(k): int(v) for k, v in mapping["idx_to_oblast_id"].items()}
    thresholds = json.loads((adir / "thresholds.json").read_text())
    return model, edge_index, scaler, idx_to_name, idx_to_oblast, thresholds, cfg_json


# --------------------------------------------------------------------------- inference
def run_inference(model, edge_index, scaler, cfg: Config):
    """Return probs/targets `[W, N, H]` plus the per-window origin timestamps (tz-naive, Kyiv local)."""
    panel = load_panel(cfg)
    times, X, Y = panel["times"], panel["X"], panel["Y"]
    Xs = scaler.transform(X).astype(np.float32)

    test_idx = time_origins(times, cfg.window, _ts(cfg.test_start), None)
    if not test_idx:
        raise RuntimeError(f"no test windows at/after {cfg.test_start}; check data/exports timeline")

    ds = A3TGCNWindowDataset(Xs, Y, cfg.window, test_idx)
    loader = DataLoader(ds, batch_size=128, shuffle=False)  # MUST stay ordered to align with origins

    probs, targs = [], []
    with torch.no_grad():
        for x, y in loader:
            logits = model(x, edge_index)
            probs.append(torch.sigmoid(logits).numpy())  # [B, N, H]
            targs.append(y.numpy())                       # [B, N, H]
    P = np.concatenate(probs, axis=0)
    T = np.concatenate(targs, axis=0)

    oi = pd.DatetimeIndex(times)[test_idx]
    origin_x = oi.tz_localize(None) if oi.tz is not None else oi  # wall-clock for plotting
    return P, T, origin_x


# --------------------------------------------------------------------------- metrics
def per_cell_metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    out = {"pr_auc": float("nan"), "roc_auc": float("nan"), "f1_macro": float("nan"),
           "n_pos": int(y.sum()), "n": int(len(y)), "pos_rate": float(y.mean()) if len(y) else float("nan")}
    yb = (p >= thr).astype(int)
    if len(np.unique(y)) >= 2:  # AUC metrics undefined for a single class
        try:
            out["pr_auc"] = float(average_precision_score(y, p))
        except Exception:
            pass
        try:
            out["roc_auc"] = float(roc_auc_score(y, p))
        except Exception:
            pass
    try:
        out["f1_macro"] = float(f1_score(y, yb, average="macro", labels=[0, 1], zero_division=0))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- plotting
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "node"


def plot_oblast(n: int, name: str, oblast_id: int, P, T, origin_x, thresholds, horizon: int) -> list[dict]:
    fig, axes = plt.subplots(2, 3, figsize=(20, 9))
    axes = axes.ravel()
    rows = []
    for k in range(horizon):
        ax = axes[k]
        p, y = P[:, n, k], T[:, n, k]
        thr = float(thresholds.get(f"k{k+1}", {}).get("threshold", 0.5))
        m = per_cell_metrics(y, p, thr)
        m.update({"oblast": name, "oblast_id": oblast_id, "horizon": k + 1, "threshold": thr})
        rows.append(m)

        x = origin_x + pd.Timedelta(hours=k + 1)  # valid (target) time = forecast issued at t, about t+k
        ax.fill_between(x, 0, 1, where=(y > 0.5), step="mid", color="crimson", alpha=0.18, linewidth=0)
        ax.plot(x, p, color="navy", lw=0.7)
        ax.axhline(thr, ls="--", color="gray", lw=0.8)
        ax.set_ylim(-0.03, 1.03)
        ax.set_title(
            f"k={k+1}h   PR-AUC={m['pr_auc']:.3f}   F1={m['f1_macro']:.3f}   ROC-AUC={m['roc_auc']:.3f}",
            fontsize=10,
        )
        ax.text(0.012, 0.96, f"alerts {m['n_pos']}/{m['n']} ({m['pos_rate']*100:.1f}%)",
                transform=ax.transAxes, va="top", ha="left", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.7", alpha=0.85))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%d"))
        ax.tick_params(axis="x", labelsize=8, rotation=0)
        ax.set_ylabel("P(alert)", fontsize=8)

    legend = [plt.Line2D([], [], color="navy", lw=1.2, label="predicted P(alert)"),
              Patch(fc="crimson", alpha=0.18, label="actual alert active"),
              plt.Line2D([], [], color="gray", ls="--", lw=0.9, label="decision threshold")]
    fig.legend(handles=legend, loc="lower center", ncol=3, fontsize=10, frameon=False)
    fig.suptitle(f"{name}  (oblast_id={oblast_id}) — A3T-GCN forecast vs actual, 2026 holdout test",
                 fontsize=14, y=0.98)
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(PLOTS / f"horizon_eval_{_slug(name)}.png", dpi=120)
    plt.close(fig)
    return rows


# --------------------------------------------------------------------------- tables
def _fmt(v) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.3f}"


def _md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def build_summary(detail: pd.DataFrame, horizon: int) -> str:
    g = detail.groupby(["oblast", "oblast_id"], sort=False)
    master = g.agg(pr_auc=("pr_auc", "mean"), f1_macro=("f1_macro", "mean"),
                   roc_auc=("roc_auc", "mean"), pos_rate=("pos_rate", "mean")).reset_index()
    master = master.sort_values("pr_auc", ascending=False, na_position="last")

    master_rows = [[r.oblast, int(r.oblast_id), _fmt(r.pr_auc), _fmt(r.f1_macro),
                    _fmt(r.roc_auc), _fmt(r.pos_rate)] for r in master.itertuples()]
    master_md = _md_table(
        ["Oblast", "id", "PR-AUC (mean)", "F1-macro (mean)", "ROC-AUC (mean)", "alert rate"], master_rows)

    # per-horizon PR-AUC breakdown (oblasts × k1..k6)
    pivot = detail.pivot_table(index=["oblast", "oblast_id"], columns="horizon",
                               values="pr_auc", sort=False).reset_index()
    hcols = [f"k{k+1}" for k in range(horizon)]
    breakdown_rows = []
    for r in pivot.itertuples(index=False):
        vals = list(r)
        breakdown_rows.append([vals[0], int(vals[1])] + [_fmt(v) for v in vals[2:]])
    breakdown_md = _md_table(["Oblast", "id"] + hcols, breakdown_rows)

    overall = detail[["pr_auc", "f1_macro", "roc_auc"]].mean()
    md = (
        "# Per-oblast holdout-test evaluation (A3T-GCN, 2026)\n\n"
        f"- Oblasts: **{detail['oblast'].nunique()}**  ·  horizons: **k=1..{horizon}**\n"
        f"- Global mean over all oblasts×horizons — PR-AUC **{overall['pr_auc']:.3f}**, "
        f"F1-macro **{overall['f1_macro']:.3f}**, ROC-AUC **{overall['roc_auc']:.3f}**\n\n"
        "## Master table — metrics averaged over horizons, per oblast\n\n"
        + master_md
        + "\n\n## PR-AUC by horizon (per oblast)\n\n"
        + breakdown_md + "\n"
    )
    return md


# --------------------------------------------------------------------------- main
def main() -> None:
    adir = _find_artifacts_dir()
    print(f"[load] artifacts ← {adir}")
    model, edge_index, scaler, idx_to_name, idx_to_oblast, thresholds, cfg_json = load_bundle(adir)

    cfg = Config(feature_cols=cfg_json["feature_cols"], window=cfg_json["window"],
                 horizon=cfg_json["horizon"])
    print(f"[data] exports ← {cfg.exports_dir}  (test_start={cfg.test_start}, window={cfg.window})")

    P, T, origin_x = run_inference(model, edge_index, scaler, cfg)
    W, N, H = P.shape
    if N != len(idx_to_name):
        raise RuntimeError(f"node-count mismatch: inference N={N} vs mapping {len(idx_to_name)}")
    if T.shape != P.shape:
        raise RuntimeError(f"shape mismatch: probs {P.shape} vs targets {T.shape}")
    print(f"[infer] test windows={W}  nodes={N}  horizons={H}  "
          f"span {origin_x.min():%Y-%m-%d} → {origin_x.max():%Y-%m-%d}")

    PLOTS.mkdir(parents=True, exist_ok=True)
    detail_rows: list[dict] = []
    for n in range(N):
        name = idx_to_name.get(n, f"node{n}")
        oid = idx_to_oblast.get(n, n)
        detail_rows.extend(plot_oblast(n, name, oid, P, T, origin_x, thresholds, H))
        print(f"  [plot] {n+1:>2}/{N}  horizon_eval_{_slug(name)}.png")

    detail = pd.DataFrame(detail_rows)
    detail.to_csv(PLOTS / "metrics_per_oblast_horizon.csv", index=False)
    summary_md = build_summary(detail, H)
    (PLOTS / "metrics_summary.md").write_text(summary_md)

    n_png = len(list(PLOTS.glob("horizon_eval_*.png")))
    print("\n" + summary_md)
    print(f"[done] {n_png} per-oblast PNGs + metrics_summary.md + metrics_per_oblast_horizon.csv → {PLOTS}")


if __name__ == "__main__":
    main()
