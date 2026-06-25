# 06 — Model Architecture: A3T-GCN Engineering Blueprint

> **Strict engineering blueprint** for implementing, training, evaluating, explaining, and shipping the
> model selected in [`05 §5`](./05-ml-model.md): **A3T-GCN** (Attention Temporal Graph Convolutional
> Network). Consumes the `data/exports/` bundle (`04`); reads **Parquet only — no DB access at train
> time**. Target & leakage rules from [`01`](./01-initial-research-analysis.md); gates from
> [`02 §Stage 3`](./02-general-workflow-architecture.md). Module home: `src/airraid/models/stgnn.py`
> + the shared `src/airraid/eval/` harness (`05 §4.4`).

**Task recap:** binary air-alert occurrence per oblast, **Direct multi-horizon** `k=1..6 h`; one shared
spatio-temporal encoder → 6 calibrated probabilities per `(oblast, t)`. Dataset spans **2022-02-24 →
2026-06-25**, 27 oblasts, base rate ≈ 17.1 %.

---

## 1. Model Architecture Specification

### 1.1 Inputs
| Symbol | Shape | Source | Notes |
|---|---|---|---|
| `X` (node features × time) | `[N=27, F≈21, W]` | `airraid_analytical_wide.parquet` | Sliding window of the **W** past hours `[t-W+1 … t]`, all features **as-of `t`**. |
| `edge_index` | `[2, 106]` | `edges.parquet` (`src_idx`,`dst_idx`) | Static directed oblast adjacency. |
| `edge_weight` (optional) | `[106]` | `oblasts.parquet` centroids | Distance-decayed `exp(-d/σ)` from `centroid_lat/lon`; default `None` (uniform). |
| node mapping | 27 rows | `oblasts.parquet` (`oblast_id↔node_idx`) | Fixes row order of `X`/outputs to `node_idx`. |
| labels `Y` | `[N=27, 6]` | wide `y_lead_1..6` at origin `t` | Truth at `t+1 … t+6`. |

### 1.2 Node feature set `F` (≈21, from the wide parquet)
Drop keys/labels/`oblast_name`/`year`. Use:
- **Weather (4):** `temp_c, wind_speed, precip_mm, cloud_cover`.
- **Spatial alert state (3):** `self_alert_active, neighbor_alert_count, neighbor_alert_frac`.
- **Calendar (6):** `hour_sin, hour_cos, dow_sin, dow_cos, is_weekend, month`.
- **OSINT (6):** `osint_mig31_airborne, osint_tu95_takeoff, osint_mass_national, osint_mass_oblast,
  hours_since_mig31, hours_since_tu95`.
- **Static node (2):** `centroid_lat, centroid_lon`.

> *Ablation note:* `neighbor_alert_count/frac` are partly **redundant** once GCN message passing is on
> (the graph learns neighbor effects). Keep them in the first run; ablate to measure the graph's marginal
> contribution.

### 1.3 Layers & data flow
```
X[N,F,W]  ──standardize(per-feature, train stats)──►  Xn[N,F,W]
                                                       │   edge_index[2,106] (+edge_weight)
                                                       ▼
                        ┌──────────── A3TGCN block ────────────┐
                        │  per period w=1..W:                  │
                        │    TGCN cell = GCNConv(spatial) ⊕ GRU │   ──► H_w[N, hidden]
                        │  temporal attention α over {H_1..H_W} │
                        └──────────────────────────────────────┘
                                                       ▼
                                            Z[N, hidden]   (attention-weighted node embedding)
                                                       ▼
                                                  Dropout(p)
                                                       ▼
                                          Linear(hidden → 6)  ──► logits[N,6]
                                                       ▼
                                       sigmoid ──► P(alert | oblast, t+k), k=1..6
```
1. **Standardization** — per-feature z-score using **train-only** mean/std; booleans + cyclical sin/cos
   pass through unscaled; `hours_since_*` clipped/standardized (null→sentinel handled at export already).
2. **`A3TGCN(in_channels=F, out_channels=hidden, periods=W)`** — at each of the `W` periods a **TGCN cell**
   applies a **GCN spatial convolution** over `edge_index` then a **GRU** gate; a learned **temporal
   attention** weights the `W` hidden states into one node embedding `Z[N, hidden]`. (PyG-Temporal
   `A3TGCN`.)
3. **Dropout(p)**.
4. **Classification head** `Linear(hidden → 6)` → `logits[N, 6]`; `sigmoid` gives the 6 per-horizon
   probabilities. **Single shared encoder, multi-output head = Direct multi-horizon** (one forward pass
   predicts all of `t+1..t+6`).

### 1.4 Leak-safety (enforced)
Input window covers only hours **≤ `t`**; labels are at **`t+k`**; this reuses the export's proven as-of
guarantee (feature grid == label grid, 0 orphans, `04`). A leakage-guard test asserts no window row has
`hour_ts > t` and that head output `k` is scored against `y_lead_k` (`02 §Stage 3`).

---

## 2. Training, Validation & Test Strategy

### 2.1 Walk-forward (expanding-window) blocked CV with embargo
Chronological over **2022-02 → 2026-06**; the validation block always **follows** training in time:

| Fold | Train (expanding) | Validation |
|---|---|---|
| 1 | 2022-02 → 2023-12 | 2024-01 → 2024-06 |
| 2 | 2022-02 → 2024-06 | 2024-07 → 2024-12 |
| 3 | 2022-02 → 2024-12 | 2025-01 → 2025-06 |
| 4 | 2022-02 → 2025-06 | 2025-07 → 2025-12 |
| **TEST (hold-out)** | 2022-02 → 2025-12 | **2026-01 → 2026-06** *(untouched during tuning/selection)* |

- **Embargo gap = `W + 6 h`** dropped between train end and validation start, so no training window/label
  overlaps a validation window/label (kills boundary leakage on the autocorrelated series).
- Refit scaler + `pos_weight` on **each fold's train block only**.

### 2.2 Loss (class imbalance)
- **Primary:** per-horizon **`BCEWithLogitsLoss(pos_weight_k)`**, with `pos_weight_k = neg_k / pos_k`
  computed on the **train** block (base rate ~17 % → ≈ 4.8; recomputed per horizon, since positives thin
  out as `k` grows). Total loss = mean over the 6 horizons × 27 nodes (optionally horizon-weighted).
- **Alternative (named):** **Focal loss** (`γ≈2`) for the rarer **onset** target / extreme imbalance.

### 2.3 Metrics & selection (per horizon `k`)
- **PR-AUC (primary)**, **Brier**, **log-loss**, **reliability curve / ECE** — never raw accuracy.
- **Skill vs baselines** (persistence, seasonal-naive, climatology) per `k`; report the **skill-decay
  curve** over `k=1..6`.
- **Calibration:** fit **isotonic regression** per horizon on the validation block; report pre/post ECE.
- **Model selection / early stopping:** best **mean val PR-AUC** across horizons, patience ≈ 8 epochs.
- **Promotion gate (`02 §Stage 3`):** A3T-GCN ships only if it beats the baselines **and** the Tier-1
  tabular model on per-horizon PR-AUC/Brier under this identical split; otherwise log and keep the
  simpler model.

---

## 3. Hyperparameters

| Hyperparameter | Initial | Tune range | Notes |
|---|---|---|---|
| `window W` (periods) | **12** | {6, 12, 24} | Hours of history per sample. |
| `hidden` (out_channels) | **64** | {32, 64, 128} | A3TGCN embedding width. |
| `A3TGCN blocks` | **1** | {1, 2} | Stack a 2nd block only if it earns it. |
| `dropout p` | **0.2** | {0.1, 0.2, 0.3} | Before the head. |
| `learning_rate` | **1e-3** | {3e-4, 1e-3} | **AdamW**. |
| `weight_decay` | **1e-5** | {0, 1e-5, 1e-4} | L2. |
| `batch_size` | **64** | {32, 64} | Time-window snapshots per batch. |
| `epochs` | **50** | + early-stop (patience 8) | |
| `grad_clip` | **1.0** | {0.5, 1.0} | Norm clipping. |
| `lr_scheduler` | **ReduceLROnPlateau(val PR-AUC)** | cosine | factor 0.5, patience 4. |
| `pos_weight` | per-horizon from train | — | `neg_k/pos_k`. |
| `edge_weight` | None (uniform) | distance-decay | from centroids. |
| `seed` | **42** | — | full determinism. |

---

## 4. Engineering & MLOps Requirements

### 4.1 Experiment tracking — **Weights & Biases (`wandb`), mandatory**
- `wandb.init(project="airraid-stgnn", config=<all hyperparameters>)`.
- Log **per training step:** train loss, LR, gradient norm.
- Log **per epoch:** train/val **PR-AUC, Brier, log-loss per horizon `k`**, mean val PR-AUC, reliability
  plots, calibration ECE, epoch time.
- `wandb.watch(model, log="all")`; log best metrics + the final skill-vs-baseline table; store the run id
  in `run_metadata.json` (§6).

### 4.2 Progress visualization — **`tqdm`, mandatory**
- **Outer bar across epochs** (`for epoch in tqdm(range(epochs), desc="epochs")`).
- **Inner bar across batches** (`for batch in tqdm(loader, leave=False, desc=f"epoch {e}")`), with
  `set_postfix(loss=…, lr=…)` updated each batch — batch-level progress is required, not just epoch-level.

### 4.3 Checkpointing
- **Every single epoch** → `checkpoints/epoch_{n:03d}.pt` containing `model_state`, `optimizer_state`,
  `scheduler_state`, `epoch`, `val_metrics`, and **RNG states** (torch/numpy/python) → fully resumable.
- Maintain **`checkpoints/best_model.pt`** = the epoch with the best **mean val PR-AUC** (overwritten on
  improvement).
- Determinism: set all seeds; record `data/exports/manifest.json` sha + git rev with each checkpoint.

---

## 5. Explainability (XAI) — mandatory

We must trust *and narrate* predictions (Stage 5 analyst agent), so every shipped model emits
explanations in terms of **node features** (weather / OSINT / calendar) and **edges** (neighboring
oblasts):
- **Temporal attention extraction** — dump the A3T-GCN attention weights `α` per node → *which past hours*
  drove the forecast.
- **GNNExplainer** (`torch_geometric.explain.Explainer` + `GNNExplainer`) — per prediction, a **node-
  feature mask** (top features) and an **edge mask** (which neighbor-oblast connections mattered).
- **Integrated Gradients** (Captum `IntegratedGradients`) over the standardized node features → signed
  per-feature attributions (e.g. "high `osint_mig31_airborne` + low `cloud_cover` raised P(alert)").
- **Outputs:** a global aggregate (`global_feature_importance.json`) **and** sampled per-`(oblast, t, k)`
  explanations as JSON + PNG, written to the artifacts dir (§6).

---

## 6. Inference Artifacts (training-pipeline deliverables)

All written under `artifacts/stgnn/<run_id>/` so the model loads and runs in the inference / analyst
stages without the training code:

| Artifact | Contents / purpose |
|---|---|
| `best_model.pt` | Model `state_dict` (best val PR-AUC). |
| `model_config.json` | `F`, `W`, `hidden`, `blocks`, `dropout`, horizons `1..6`, **ordered feature-column list**, edge_weight flag — everything needed to reconstruct the architecture. |
| `feature_scaler.{pkl,json}` | Per-feature train mean/std (+ which columns are pass-through) for inference normalization. |
| `edge_index.pt` | Static `[2,106]` adjacency tensor (mirror of `edges.parquet`). |
| `node_mapping.json` | `oblast_id ↔ node_idx ↔ oblast_name` (output row order). |
| `calibrators.pkl` | Per-horizon isotonic calibrators (logit/prob → calibrated prob). |
| `metrics.json` | Per-horizon **val + held-out-test** PR-AUC/Brier/log-loss/ECE + skill-vs-baseline + decay curve. |
| `xai/global_feature_importance.json`, `xai/samples/*.{json,png}` | Aggregated + per-prediction explanations (§5). |
| `run_metadata.json` | `wandb` run id, git rev, seed, `data/exports/manifest.json` sha, timestamps. |
| `requirements.lock` | Pinned env (torch, torch-geometric, torch-geometric-temporal, captum, wandb, …). |
| `prediction_schema.py` (or `.json`) | The **Pydantic** request/response contract carrying `lead_hours` — the Stage-4 (FastAPI) inference interface; numeric outputs must round-trip identically under fixed seed. |

**Acceptance:** reload `best_model.pt` + `model_config.json` + `feature_scaler` + `edge_index.pt`,
reproduce identical probabilities on a fixed sample (artifact round-trip test, `02 §Stage 3`), and serve
them through `prediction_schema`.

---

## 7. Threshold Calibration (post-training decision threshold)

Probability **calibration** (isotonic, §2.3) fixes *how accurate the probabilities are*; **threshold
calibration** picks *the operating point* that turns a calibrated probability into a binary alert
decision (the UI badge / downstream policy). With a **17 % base rate** the default `0.5` cut-off is far
from optimal — it over-suppresses the minority (alert) class.

- **Procedure (per horizon `k`, on the validation block — never test):**
  1. Collect calibrated probabilities `p_k` and ground truth `y_k`.
  2. Sweep candidate thresholds `τ ∈ {0.01, 0.02, …, 0.99}`.
  3. Choose `τ_k* = argmax_τ F_β(τ)` where `F_β` is computed on `(p_k ≥ τ)` vs `y_k`.
- **Objective:** **F1 (β = 1, macro over {alert, no-alert})** by default; provide **F-beta with β = 2**
  as the recall-weighted option (a *missed* alert is operationally costlier than a false alarm, so
  favoring recall is defensible). The chosen β is logged.
- **Outputs / reporting:** persist `thresholds.json` = `{k: τ_k*, beta, val_precision, val_recall, val_f}`
  (an inference artifact, §6); report precision/recall/F at `τ_k*` per horizon.
- **Discipline:** thresholds are fit on validation, **frozen**, then applied unchanged to the held-out
  **2026 test**. The **calibrated probability remains the primary output**; threshold-free scores
  (PR-AUC, Brier) stay the headline metrics so the operating-point choice never inflates them.

## 8. Testing Strategy (strict, pre-training gate)

A **mandatory test phase runs before any training** (TDD): `tests/test_ml_components.py`, executed with
`PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_ml_components.py`. It validates the cheap-but-
critical contracts so we never burn a Kaggle GPU run on a shape bug:

- **Data loaders (batch shapes):** a `DataLoader` batch yields node features `X` of shape
  **`[batch, num_nodes, num_features, seq_len]`**, `edge_index` of shape **`[2, num_edges]`**, and
  targets `Y` of shape **`[batch, num_nodes, horizon]`**; node order follows `node_idx`; tensors are
  `float32`; no NaN/Inf after standardization.
- **A3T-GCN forward pass (no dimension mismatch):** the model maps a batch to logits **`[batch,
  num_nodes, horizon]`** for `batch = 1` and `batch > 1`; a backward pass populates gradients (loss is
  differentiable end-to-end).
- **Loss behavior / edge cases:** `MultiHorizonBCE` returns a finite, non-negative scalar for all-zero
  and all-one targets; near-perfect logits → ≈ 0; raising `pos_weight` increases the penalty on positive
  targets; mismatched shapes raise.

Tests use tiny **synthetic fixtures** (a small grid with the real schema) for speed + determinism, and
smoke-test the real `data/exports/` files when present. **The training notebook is not built/run until
this suite is green.**

## 9. Kaggle Export Workflow

Training runs on **Kaggle** (free GPU). The model code lives **only** under `src/ml/` — that is the
single source of truth, the exact code the tests import. We do **not** hand-maintain a parallel notebook;
instead `scripts/build_notebook.py` generates a **self-contained** notebook by base64-embedding the
`src/ml/` sources into cells that decode them to the Kaggle working directory and then run training.
`data/exports/` is uploaded as a Kaggle **Dataset** (mounted read-only at `/kaggle/input/...`); the
notebook reads the parquet bundle from there.

> `build_notebook.py` regenerates the **self-contained** notebook from the `src/ml/` sources (base64-embedded, so there is a single source of truth — the same code the tests use). **Re-run it after any change under `src/ml/`.** You upload exactly two things to Kaggle: the `data/exports/` folder and `notebooks/train_a3tgcn.ipynb`.

---

*Cross-references:* model verdict & rationale → [`05 §5`](./05-ml-model.md); target/horizon/leakage →
[`01`](./01-initial-research-analysis.md); stage gates → [`02 §Stage 3`](./02-general-workflow-architecture.md);
data bundle this consumes → [`04`](./04-analytics-eda.md).


## Task 5 — Commands for you to run

1. Run the tests yourself:
PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_ml_components.py -v

2. Build the Kaggle notebook (re-run after any change under src/ml/):
./.venv/bin/python3 scripts/build_notebook.py

Then on Kaggle, upload exactly two things — the data/exports/ folder (as a Dataset) and notebooks/train_a3tgcn.ipynb — enable GPU, and run all cells.