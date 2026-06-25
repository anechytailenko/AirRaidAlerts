"""Losses + metrics + threshold calibration (plans/06 §2, §7).

`MultiHorizonBCE` is per-horizon `BCEWithLogitsLoss` with an optional per-horizon `pos_weight` to handle
the ~17% base rate. Focal loss is provided as the recall-favoring alternative for the rarer onset target.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class MultiHorizonBCE(nn.Module):
    """BCE-with-logits over `[B, N, H]`; `pos_weight` is a length-H vector (or None)."""

    def __init__(self, pos_weight=None):
        super().__init__()
        if pos_weight is None:
            self.register_buffer("pos_weight", None)
        else:
            if not torch.is_tensor(pos_weight):
                pos_weight = torch.as_tensor(pos_weight, dtype=torch.float32)
            self.register_buffer("pos_weight", pos_weight.float())

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        if logits.shape != targets.shape:
            raise ValueError(f"shape mismatch: logits {tuple(logits.shape)} vs targets {tuple(targets.shape)}")
        pw = self.pos_weight
        if pw is not None:
            pw = pw.view(*([1] * (logits.dim() - 1)), -1).to(logits.device)
        return F.binary_cross_entropy_with_logits(logits, targets.float(), pos_weight=pw)


class MultiHorizonFocal(nn.Module):
    """Focal loss (Lin et al.) for extreme imbalance / onset target."""

    def __init__(self, gamma: float = 2.0, alpha: float = 0.25):
        super().__init__()
        self.gamma, self.alpha = gamma, alpha

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        if logits.shape != targets.shape:
            raise ValueError(f"shape mismatch: logits {tuple(logits.shape)} vs targets {tuple(targets.shape)}")
        targets = targets.float()
        p = torch.sigmoid(logits)
        ce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        p_t = p * targets + (1 - p) * (1 - targets)
        alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
        return (alpha_t * (1 - p_t).pow(self.gamma) * ce).mean()


def pos_weight_from_targets(Y: np.ndarray, horizon: int) -> torch.Tensor:
    """Per-horizon neg/pos ratio from a `[*, H]` target array (clamped to a sane range)."""
    flat = Y.reshape(-1, horizon)
    pos = flat.sum(axis=0)
    neg = flat.shape[0] - pos
    w = np.where(pos > 0, neg / np.maximum(pos, 1.0), 1.0)
    return torch.tensor(np.clip(w, 1.0, 1000.0), dtype=torch.float32)


def fbeta_score(precision: float, recall: float, beta: float) -> float:
    b2 = beta * beta
    denom = b2 * precision + recall
    return float((1 + b2) * precision * recall / denom) if denom > 0 else 0.0


def calibrate_thresholds(probs: np.ndarray, targets: np.ndarray, beta: float = 1.0) -> dict:
    """Per-horizon decision threshold maximizing F-beta on the validation set (plans/06 §7).

    `probs`,`targets`: `[samples, H]`. Returns {horizon_k: {threshold, precision, recall, fbeta}}.
    """
    H = probs.shape[-1]
    grid = np.linspace(0.01, 0.99, 99)
    out: dict[str, dict] = {}
    for k in range(H):
        p, y = probs[:, k], targets[:, k]
        best = {"threshold": 0.5, "precision": 0.0, "recall": 0.0, "fbeta": -1.0}
        for thr in grid:
            pred = p >= thr
            tp = float(np.sum(pred & (y == 1)))
            fp = float(np.sum(pred & (y == 0)))
            fn = float(np.sum((~pred) & (y == 1)))
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fb = fbeta_score(prec, rec, beta)
            if fb > best["fbeta"]:
                best = {"threshold": float(thr), "precision": prec, "recall": rec, "fbeta": fb}
        out[f"k{k + 1}"] = best
    return out
