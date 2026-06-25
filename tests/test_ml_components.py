"""Strict pre-training tests (plans/06 §8): data-loader shapes, A3T-GCN forward pass, loss behavior.

Run: PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_ml_components.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch
from torch.utils.data import DataLoader

from ml.config import FEATURE_COLS, Config
from ml.dataset import A3TGCNWindowDataset, build_datasets, load_panel
from ml.losses import MultiHorizonBCE, calibrate_thresholds, pos_weight_from_targets
from ml.model import A3TGCN

N_NODES = 5
HORIZON = 6
N_FEAT = len(FEATURE_COLS)
_BOOL_COLS = {"self_alert_active", "is_weekend", "osint_mig31_airborne", "osint_tu95_takeoff",
              "osint_mass_national", "osint_mass_oblast"}


def _make_exports(tmp_path, start="2022-02-24", T=40, N=N_NODES, H=HORIZON, **cfg_kwargs):
    """Write a tiny long/edges/oblasts parquet trio with the real schema."""
    rng = np.random.default_rng(0)
    times = pd.date_range(start, periods=T, freq="h", tz="UTC")
    rows = []
    for t in times:
        for oid in range(1, N + 1):
            base = {c: (float(rng.random() < 0.3) if c in _BOOL_COLS else float(rng.normal())) for c in FEATURE_COLS}
            for lead in range(1, H + 1):
                rows.append({"hour_ts": t, "oblast_id": oid, "lead_hours": lead,
                             "y_alert_active": bool(rng.random() < 0.2), **base})
    pd.DataFrame(rows).to_parquet(tmp_path / "airraid_analytical_long.parquet")
    _src = list(range(N))
    _dst = [(i + 1) % N for i in range(N)]  # ring over N nodes (valid for any N)
    pd.DataFrame({"src_oblast_id": [s + 1 for s in _src], "dst_oblast_id": [d + 1 for d in _dst],
                  "src_idx": _src, "dst_idx": _dst}).to_parquet(tmp_path / "edges.parquet")
    pd.DataFrame({"oblast_id": list(range(1, N + 1)), "oblast_name": [f"o{i}" for i in range(N)],
                  "centroid_lat": [50.0] * N, "centroid_lon": [30.0] * N,
                  "node_idx": list(range(N))}).to_parquet(tmp_path / "oblasts.parquet")
    return Config(exports_dir=str(tmp_path), window=6, batch_size=4, horizon=H, **cfg_kwargs)


def _edge_index(N=N_NODES):
    return torch.tensor([[0, 1, 2, 3], [1, 2, 3, 0]], dtype=torch.long)


# --------------------------------------------------------------------------- data loaders
def test_window_dataset_batch_shapes():
    T, W, B = 30, 6, 4
    X = np.random.randn(T, N_NODES, N_FEAT).astype(np.float32)
    Y = (np.random.rand(T, N_NODES, HORIZON) < 0.2).astype(np.float32)
    ds = A3TGCNWindowDataset(X, Y, window=W, origins=list(range(W - 1, T)))
    x, y = ds[0]
    assert x.shape == (N_NODES, N_FEAT, W)           # single item [N, F, W]
    assert y.shape == (N_NODES, HORIZON)
    xb, yb = next(iter(DataLoader(ds, batch_size=B, shuffle=False)))
    assert xb.shape == (B, N_NODES, N_FEAT, W)        # [batch, num_nodes, num_features, seq_len]
    assert yb.shape == (B, N_NODES, HORIZON)          # [batch, num_nodes, horizon]
    assert xb.dtype == torch.float32 and yb.dtype == torch.float32
    assert torch.isfinite(xb).all()


def test_edge_index_shape():
    ei = _edge_index()
    assert ei.shape[0] == 2 and ei.ndim == 2          # [2, num_edges]


def test_load_panel_and_build_datasets(tmp_path):
    cfg = _make_exports(tmp_path)
    panel = load_panel(cfg)
    T = len(panel["times"])
    assert panel["X"].shape == (T, N_NODES, N_FEAT)   # [T, N, F]
    assert panel["Y"].shape == (T, N_NODES, HORIZON)  # [T, N, H]
    assert not np.isnan(panel["X"]).any()

    data = build_datasets(cfg)
    assert data["edge_index"].shape == (2, N_NODES)  # ring fixture → N edges
    assert len(data["train"]) > 0
    xb, yb = next(iter(DataLoader(data["train"], batch_size=cfg.batch_size)))
    assert xb.shape[1:] == (N_NODES, N_FEAT, cfg.window)
    assert yb.shape[1:] == (N_NODES, HORIZON)


def test_time_origins_resolution_safe():
    """Regression: split must work for microsecond-resolution timestamps (parquet → us, not ns)."""
    from ml.dataset import time_origins
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC").as_unit("us")
    sel = time_origins(idx, window=6, start="2024-01-05", end="2024-01-07")
    assert len(sel) > 0  # the asi8/ns-vs-us bug returned [] here
    lo, hi = pd.Timestamp("2024-01-05", tz="UTC"), pd.Timestamp("2024-01-07", tz="UTC")
    assert all(lo <= idx[i] < hi for i in sel)


def test_build_datasets_populates_val_and_test(tmp_path):
    """Regression: with in-range split dates, val AND test must be non-empty (the NaN-PR-AUC bug)."""
    cfg = _make_exports(tmp_path, start="2024-01-01", T=240, N=3,
                        val_start="2024-01-06", test_start="2024-01-08")
    data = build_datasets(cfg)
    assert len(data["train"]) > 0
    assert len(data["val"]) > 0, "validation split is empty → val PR-AUC would be NaN"
    assert len(data["test"]) > 0, "test split is empty"


# --------------------------------------------------------------------------- model forward
@pytest.mark.parametrize("B", [1, 3])
def test_model_forward_shape(B):
    W = 6
    model = A3TGCN(in_channels=N_FEAT, hidden=16, horizon=HORIZON, num_layers=1)
    x = torch.randn(B, N_NODES, N_FEAT, W)
    out = model(x, _edge_index())
    assert out.shape == (B, N_NODES, HORIZON)
    assert torch.isfinite(out).all()


def test_model_forward_returns_attention():
    model = A3TGCN(in_channels=N_FEAT, hidden=16, horizon=HORIZON)
    out, attn = model(torch.randn(2, N_NODES, N_FEAT, 6), _edge_index(), return_attention=True)
    assert out.shape == (2, N_NODES, HORIZON)
    assert attn.shape == (2, N_NODES, 6)              # [B, N, T] temporal attention for XAI


def test_model_backward_grads_flow():
    model = A3TGCN(in_channels=N_FEAT, hidden=16, horizon=HORIZON)
    out = model(torch.randn(2, N_NODES, N_FEAT, 6), _edge_index())
    out.sum().backward()
    grads = [p.grad for p in model.parameters() if p.requires_grad]
    assert any(g is not None and torch.isfinite(g).all() and g.abs().sum() > 0 for g in grads)


def test_model_rejects_wrong_feature_dim():
    model = A3TGCN(in_channels=N_FEAT, hidden=8, horizon=HORIZON)
    with pytest.raises(ValueError):
        model(torch.randn(2, N_NODES, N_FEAT + 1, 6), _edge_index())


# --------------------------------------------------------------------------- loss edge cases
def test_loss_finite_on_all_zero_and_all_one():
    loss = MultiHorizonBCE()
    logits = torch.zeros(2, N_NODES, HORIZON)
    for target in (torch.zeros_like(logits), torch.ones_like(logits)):
        v = loss(logits, target)
        assert torch.isfinite(v) and v.item() >= 0.0


def test_loss_near_zero_for_confident_correct():
    loss = MultiHorizonBCE()
    targets = (torch.rand(2, N_NODES, HORIZON) < 0.3).float()
    logits = (targets * 2 - 1) * 12.0  # very confident & correct
    assert loss(logits, targets).item() < 0.01


def test_pos_weight_increases_positive_penalty():
    logits = torch.zeros(2, N_NODES, HORIZON)
    targets = torch.ones_like(logits)  # all positive → pos_weight should bite
    base = MultiHorizonBCE()(logits, targets)
    weighted = MultiHorizonBCE(pos_weight=[10.0] * HORIZON)(logits, targets)
    assert weighted.item() > base.item()


def test_loss_raises_on_shape_mismatch():
    with pytest.raises(ValueError):
        MultiHorizonBCE()(torch.zeros(2, N_NODES, HORIZON), torch.zeros(2, N_NODES, 3))


def test_pos_weight_from_targets_and_threshold_calibration():
    Y = (np.random.rand(500, HORIZON) < 0.17).astype(np.float32)
    pw = pos_weight_from_targets(Y, HORIZON)
    assert pw.shape == (HORIZON,) and (pw >= 1.0).all()
    probs = np.random.rand(500, HORIZON)
    thr = calibrate_thresholds(probs, Y, beta=1.0)
    assert set(thr.keys()) == {f"k{k+1}" for k in range(HORIZON)}
    assert all(0.0 <= thr[k]["threshold"] <= 1.0 for k in thr)
