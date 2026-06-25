"""Configuration: paths, feature columns, and hyperparameters (plans/06 §1, §3).

The exports directory can be overridden via the `AIRRAID_EXPORTS_DIR` env var — used by the Kaggle
notebook, which mounts `data/exports/` as a read-only dataset at `/kaggle/input/...`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# src/ml/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EXPORTS = REPO_ROOT / "data" / "exports"

# Node feature set (≈21). Order is the model's input channel order — persisted in model_config.json.
FEATURE_COLS: list[str] = [
    # weather (continuous)
    "temp_c", "wind_speed", "precip_mm", "cloud_cover",
    # spatial alert state at t
    "self_alert_active", "neighbor_alert_count", "neighbor_alert_frac",
    # calendar (cyclical + flags)
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "month",
    # OSINT air-tactical flags + staleness
    "osint_mig31_airborne", "osint_tu95_takeoff", "osint_mass_national", "osint_mass_oblast",
    "hours_since_mig31", "hours_since_tu95",
    # static node geography
    "centroid_lat", "centroid_lon",
]

# Columns z-scored with train statistics; everything else (bools, sin/cos) passes through unscaled.
STANDARDIZE_COLS: list[str] = [
    "temp_c", "wind_speed", "precip_mm", "cloud_cover",
    "neighbor_alert_count", "neighbor_alert_frac", "month",
    "hours_since_mig31", "hours_since_tu95", "centroid_lat", "centroid_lon",
]

HORIZONS: list[int] = [1, 2, 3, 4, 5, 6]
NUM_FEATURES = len(FEATURE_COLS)
HORIZON = len(HORIZONS)


def _exports_dir() -> Path:
    return Path(os.environ.get("AIRRAID_EXPORTS_DIR", str(_DEFAULT_EXPORTS)))


def _artifacts_dir() -> Path:
    """Writable + persisted output dir. On Kaggle ONLY `/kaggle/working` is saved to the notebook
    Output, so default there (REPO_ROOT resolves to read-only `/kaggle`, which silently drops files)."""
    env = os.environ.get("AIRRAID_ARTIFACTS_DIR")
    if env:
        return Path(env)
    if Path("/kaggle/working").is_dir():
        return Path("/kaggle/working/artifacts/stgnn")
    return REPO_ROOT / "artifacts" / "stgnn"


@dataclass
class Config:
    # data
    exports_dir: str = field(default_factory=lambda: str(_exports_dir()))
    long_path: str = ""
    edges_path: str = ""
    oblasts_path: str = ""
    feature_cols: list[str] = field(default_factory=lambda: list(FEATURE_COLS))
    horizon: int = HORIZON
    max_hours: int | None = None  # cap timeline for quick local runs; None = full history

    # model
    window: int = 12
    hidden: int = 64
    num_layers: int = 1
    dropout: float = 0.2

    # optimization
    lr: float = 1e-3
    weight_decay: float = 1e-5
    batch_size: int = 64
    epochs: int = 50
    grad_clip: float = 1.0
    patience: int = 8
    seed: int = 42

    # temporal split (walk-forward; held-out 2026 test). Embargo = window + horizon hours.
    train_end: str = "2025-06-30"
    val_start: str = "2025-07-01"
    val_end: str = "2025-12-31"
    test_start: str = "2026-01-01"

    # threshold calibration
    fbeta: float = 1.0  # 1.0 = F1; set 2.0 to favor recall (missing an alert is costlier)

    # outputs (Kaggle: must live under /kaggle/working to be saved to the notebook Output)
    artifacts_dir: str = field(default_factory=lambda: str(_artifacts_dir()))

    def __post_init__(self) -> None:
        d = Path(self.exports_dir)
        self.long_path = self.long_path or str(d / "airraid_analytical_long.parquet")
        self.edges_path = self.edges_path or str(d / "edges.parquet")
        self.oblasts_path = self.oblasts_path or str(d / "oblasts.parquet")

    @property
    def num_features(self) -> int:
        return len(self.feature_cols)
