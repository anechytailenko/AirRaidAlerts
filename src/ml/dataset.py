"""Dataset / DataLoader: integrate the long parquet + edges + oblasts into windowed graph snapshots.

Pipeline (plans/06 §1):
  airraid_analytical_long.parquet  (one row per (hour_ts, oblast_id, lead_hours))
    → pivot leads → per-cell features `[T, N, F]` + multi-horizon targets `[T, N, 6]`
  edges.parquet  → static `edge_index [2, E]`
  oblasts.parquet → node order (`node_idx`) + node↔oblast mapping

A sample at origin hour `t` is a window of the W past hours `X[N, F, W]` (features as-of t) with the
6-horizon label `Y[N, 6]` (truth at t+1..t+6). Default collate → batch `[B, N, F, W]`, `[B, N, 6]`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from .config import FEATURE_COLS, STANDARDIZE_COLS, Config


# --------------------------------------------------------------------------- scaler
@dataclass
class StandardScaler:
    mean: np.ndarray  # [F]
    std: np.ndarray   # [F]

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def fit(cls, feats: np.ndarray, feature_cols: list[str]) -> "StandardScaler":
        """Fit on `feats[*, F]`. Only STANDARDIZE_COLS get real stats; others use mean=0,std=1."""
        F = feats.shape[-1]
        flat = feats.reshape(-1, F)
        mean = np.zeros(F, dtype=np.float64)
        std = np.ones(F, dtype=np.float64)
        std_idx = {feature_cols.index(c) for c in STANDARDIZE_COLS if c in feature_cols}
        for j in std_idx:
            col = flat[:, j]
            mean[j] = float(np.nanmean(col))
            s = float(np.nanstd(col))
            std[j] = s if s > 1e-8 else 1.0
        return cls(mean=mean.astype(np.float32), std=std.astype(np.float32))


# --------------------------------------------------------------------------- panel loading
def load_edge_index(edges_path: str) -> torch.Tensor:
    """edges.parquet (src_idx, dst_idx) → LongTensor [2, E]."""
    e = pd.read_parquet(edges_path, columns=["src_idx", "dst_idx"])
    return torch.tensor(np.stack([e["src_idx"].to_numpy(), e["dst_idx"].to_numpy()]), dtype=torch.long)


def load_node_mapping(oblasts_path: str) -> dict:
    o = pd.read_parquet(oblasts_path).sort_values("node_idx")
    return {
        "num_nodes": int(o["node_idx"].max()) + 1,
        "oblast_id_to_idx": {int(r.oblast_id): int(r.node_idx) for r in o.itertuples()},
        "idx_to_oblast_id": {int(r.node_idx): int(r.oblast_id) for r in o.itertuples()},
        "idx_to_name": {int(r.node_idx): str(r.oblast_name) for r in o.itertuples()},
    }


def load_panel(cfg: Config) -> dict:
    """Read the long parquet → time-aligned grids. Returns dict with `times, X[T,N,F], Y[T,N,H], mapping`.

    The long file has exactly `horizon` rows per (hour_ts, oblast_id) (leads 1..H); after a stable sort
    on (hour_ts, oblast_id, lead_hours) every block of H rows is one cell's leads in order, so features
    are the lead-1 rows and the target is a reshape of `y_alert_active`.
    """
    mapping = load_node_mapping(cfg.oblasts_path)
    N = mapping["num_nodes"]
    H = cfg.horizon
    cols = ["hour_ts", "oblast_id", "lead_hours", "y_alert_active"] + cfg.feature_cols
    df = pd.read_parquet(cfg.long_path, columns=cols)

    df = df.sort_values(["hour_ts", "oblast_id", "lead_hours"], kind="stable").reset_index(drop=True)
    if len(df) % H != 0:
        raise ValueError(f"long parquet not divisible by horizon={H} (got {len(df)} rows)")

    y = df["y_alert_active"].to_numpy().astype(np.float32).reshape(-1, H)  # [cells, H]
    cell = df.iloc[::H].copy()                                            # lead-1 row per cell
    cell["node_idx"] = cell["oblast_id"].map(mapping["oblast_id_to_idx"])

    times = pd.Index(cell["hour_ts"].unique()).sort_values()
    if cfg.max_hours is not None:
        times = times[: cfg.max_hours]
        keep = cell["hour_ts"].isin(times)
        cell, y = cell[keep], y[keep.to_numpy()]
    t_to_i = {t: i for i, t in enumerate(times)}
    T, F = len(times), len(cfg.feature_cols)

    ti = cell["hour_ts"].map(t_to_i).to_numpy()
    ni = cell["node_idx"].to_numpy()
    feats = cell[cfg.feature_cols].to_numpy(dtype=np.float32)
    feats = np.nan_to_num(feats, nan=0.0)

    X = np.zeros((T, N, F), dtype=np.float32)
    Y = np.zeros((T, N, H), dtype=np.float32)
    X[ti, ni, :] = feats
    Y[ti, ni, :] = y
    return {"times": times, "X": X, "Y": Y, "mapping": mapping}


# --------------------------------------------------------------------------- windowed dataset
class A3TGCNWindowDataset(Dataset):
    """Windows over time-aligned grids. Item: (X[N, F, W] float32, Y[N, H] float32)."""

    def __init__(self, X: np.ndarray, Y: np.ndarray, window: int, origins: list[int]):
        assert X.ndim == 3 and Y.ndim == 3, "X=[T,N,F], Y=[T,N,H]"
        self.X, self.Y, self.window, self.origins = X, Y, window, list(origins)

    def __len__(self) -> int:
        return len(self.origins)

    def __getitem__(self, i: int):
        t = self.origins[i]
        win = self.X[t - self.window + 1 : t + 1]      # [W, N, F]
        x = np.transpose(win, (1, 2, 0))               # [N, F, W]
        y = self.Y[t]                                  # [N, H]
        return torch.from_numpy(np.ascontiguousarray(x)), torch.from_numpy(np.ascontiguousarray(y))


def _ts(x):
    """Coerce a date/string/Timestamp to a tz-aware (UTC) pandas Timestamp (or None)."""
    if x is None:
        return None
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def time_origins(times, window: int, start, end, embargo: int = 0) -> list[int]:
    """Valid origin indices `t` whose window fits and whose `hour_ts` falls in [start, end).

    Comparison is done with pandas Timestamps (resolution-agnostic) — NOT `.asi8`, which returns the
    array's native unit (parquet → microseconds) and would mismatch nanosecond bounds.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    sel = np.ones(len(idx), dtype=bool)
    s, e = _ts(start), _ts(end)
    if s is not None:
        sel &= np.asarray(idx >= s)
    if e is not None:
        sel &= np.asarray(idx < e)
    lo = window - 1 + embargo  # need >= window-1 history for a full window
    if lo > 0:
        sel[:lo] = False
    return np.nonzero(sel)[0].astype(int).tolist()


def build_datasets(cfg: Config) -> dict:
    """Full pipeline → train/val/test datasets + edge_index + fitted scaler (train-only stats)."""
    panel = load_panel(cfg)
    times, X, Y = panel["times"], panel["X"], panel["Y"]

    # Embargo as a real time gap: train ends `emb` hours before val starts (and val before test),
    # so no train/val label window straddles a split boundary on the autocorrelated series.
    emb = pd.Timedelta(hours=cfg.window + cfg.horizon)
    vs, te_ = _ts(cfg.val_start), _ts(cfg.test_start)

    train_idx = time_origins(times, cfg.window, None, vs - emb)
    scaler = StandardScaler.fit(X[: (train_idx[-1] + 1) if train_idx else len(X)], cfg.feature_cols)
    Xs = scaler.transform(X).astype(np.float32)

    val_idx = time_origins(times, cfg.window, vs, te_ - emb)
    test_idx = time_origins(times, cfg.window, te_, None)

    return {
        "train": A3TGCNWindowDataset(Xs, Y, cfg.window, train_idx),
        "val": A3TGCNWindowDataset(Xs, Y, cfg.window, val_idx),
        "test": A3TGCNWindowDataset(Xs, Y, cfg.window, test_idx),
        "edge_index": load_edge_index(cfg.edges_path),
        "scaler": scaler,
        "mapping": panel["mapping"],
        "times": times,
    }
