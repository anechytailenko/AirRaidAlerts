# 05 — ML Model Architecture (Advanced, Adaptable Framework)

> **Status:** design (Stage 3 of `02`). EDA (`Stage 2`) is *intentionally deferred*; this document
> defines the modeling architecture against the already-compiled export bundle (`04`).
> **Stance:** an **adaptable, tiered framework** governed by a shared leak-safe verification harness —
> **not** a commitment to one model. We climb from baselines to ST-GNN / RL only when each rung *earns*
> promotion. Cross-refs: target/horizon/leakage rationale → [`01`](./01-initial-research-analysis.md);
> stage gates → [`02 §Stage 3`](./02-general-workflow-architecture.md); data artifact → [`04`](./04-analytics-eda.md);
> evidence → [`researches/`](../researches/).

---

## 1. Problem Definition & Data Context

### 1.1 Target variable
For each `(oblast, origin hour t)` we predict **`y_alert_active` ∈ {0,1}** — whether an air-raid alert is
**active** in that oblast during a future hour. This is **binary air-alert occurrence per oblast**
(continuation *or* fresh onset), the task locked in `01 §"anchored task"` and `02 §Stage 3`. It is a
supervised **classification** problem, not duration regression — matching the operationalized target of
Pavlyshenko & Pavlyshenko (2024) while avoiding their stated/operational drift (they claimed "duration"
but modeled binary occurrence; see `research_related_works.md`).

- **Primary target:** `y_alert_active` (occurrence). Base rate ≈ **17.1 %** (`04`).
- **Secondary, harder target:** **onset** — a *new* alert at the target hour given **none active at `t`**.
  Onset removes the trivial "already-on → still-on" persistence signal and is the genuinely useful
  early-warning case. Reported separately so persistence does not flatter the headline metric.

### 1.2 Forecasting horizon — Direct multi-horizon, k = 1..6 h
We use the **Direct** strategy: **one calibrated model `f_k` per horizon** `k ∈ {1,2,3,4,5,6}` hours
(primary **k = 1**), each trained directly on ground truth `alert_active(t+k)`. Rationale (`01 §D`):

- **Direct vs Recursive.** Recursive feeds its own predictions back as inputs and would force us to
  **forecast exogenous values first** (the *future-exogenous paradox*). Direct never does — the horizon
  lives in the **target**, not the features, so every `f_k` only ever reads information ≤ `t`.
- **Multi-step taxonomy** (TS book Ch.18: Recursive/Direct/DirRec/RecJoint/Rectify): Direct is the
  cleanest leak-safe choice for a 6-step band; DirRec/Rectify are noted as future refinements.
- **Expected skill decay.** Skill should fall toward the base rate as `k → 6` (Hrytsyna's
  predictability-ceiling caution). We **report** the decay curve, never hide it.

### 1.3 Available data — the `data/exports/` bundle (`04`)
All features are **as-of `t`** (leak-safe by construction; feature grid == label grid, 0 orphans):

| Artifact | Rows | Grain / content |
|---|---|---|
| `airraid_analytical_long.parquet` | **6,150,978** | `(hour_ts, oblast_id, lead_hours)` + `y_alert_active` (label at `t+k`). Direct training table. |
| `airraid_analytical_wide.parquet` | **1,025,163** | `(hour_ts, oblast_id)` + `y_lead_1..y_lead_6`; features once. Sequence/graph snapshots. |
| `edges.parquet` | **106** | Directed oblast adjacency as GNN `edge_index` (`src_idx`,`dst_idx`). |
| `oblasts.parquet` | **27** | Node metadata: `oblast_id`, name, `centroid_lat/lon`, `node_idx`. |

**Feature families** (per `data_dictionary.md`), mapped to the `01 §D` availability taxonomy:

| Family | Columns | Taxonomy class | Leak-safety |
|---|---|---|---|
| Calendar (known-future) | `hour_of_day, dow, month, is_weekend, hour_sin/cos, dow_sin/cos`, `year` | Class 1 — deterministic, known for all future hours | May reference target hour `t+k` |
| Spatial alert state | `self_alert_active`, `neighbor_alert_count`, `neighbor_alert_frac` | Class 2 — lagged endogenous/spatial | Only values **≤ t** |
| Weather | `temp_c, wind_speed, precip_mm, cloud_cover` | Class 3 — truly-exogenous | As-of `t` (last-known); ERA5-archive |
| OSINT (air-tactical) | `osint_mig31_airborne, osint_tu95_takeoff, osint_mass_national, osint_mass_oblast, hours_since_mig31/tu95` | Class 2/3 — observed flags | ASOF forward-fill, `event_ts ≤ t`, TTL 6 h |
| Static node | `oblast_name, centroid_lat, centroid_lon` | Class 1 — static | Constant |

> **Key property for graph models:** the bundle is *already* node-aligned — `oblasts.parquet.node_idx`
> indexes both the flat tables (via `oblast_id`) and `edges.parquet`, so flat features and topology
> merge without re-keying.

---

## 2. Task Challenges (documented in `researches/` + `plans/`)

1. **Temporal leakage — the headline risk.** The series is heavily autocorrelated; Pavlyshenko (2024)
   and Xue (2025) both built minute/day models with **no leakage diagnosis** (`research_related_works.md`).
   `01` names this "the single most likely way this project fools itself." → **time-ordered/blocked CV
   with an embargo gap**, and leakage-guard tests as release blockers (`02 §Stage 3`).
2. **Class imbalance (~17 % positive; onset far rarer).** Mirrors ViEWS's zero-inflation (≈87–99 % zeros)
   and Xue's rare conflict days. → class weights and/or **majority downsampling** (Xue's k≈20), scored on
   **PR-AUC/Brier**, never accuracy.
3. **Spatial dependence is dual-natured.** Alert status depends strongly on adjacent oblasts
   (Pavlyshenko's neighbor cumulative durations; Xue's spatial-diffusion features) — a **signal to
   exploit** (neighbor features + the graph) **and** a **leakage hazard** (a neighbor's *future* must
   never enter features). Controlled by the same ≤ `t` rule.
4. **Adversarial, non-stationary DGP + predictability ceiling.** Hrytsyna examined the data and
   **deliberately declined to forecast** (targeting is an intentional adversarial decision). Multi-year
   **structural breaks** across war phases break stationarity (`01 §3.2/§3.5`). → expect a ceiling;
   define a **stop rule**; treat regime as a feature/segmentation, not noise.
5. **Future-exogenous & weather paradoxes.** Weather/OSINT for `t+k` are unknown at `t`
   (`01 §D`); the **two opposite-sign weather mechanisms** (launch-site gating vs target-oblast
   interception) must stay **separate features**, never blended (`exogenous-variables-research.md`).
6. **Calibration is mandatory.** The UI colors by probability, so outputs must be **calibrated**
   (isotonic/Platt) and scored with **proper scores** (Brier, log-loss, PR-AUC) + reliability curves —
   the ViEWS discipline (CRPS/IGN/MIS), adapted to a binary target.
7. **OSINT sparsity.** Only 1,021 real events forward-filled (TTL 6 h) → mostly-static, bursty flags;
   useful but low-frequency, with staleness exposed via `hours_since_*`.

---

## 3. Comprehensive Model Research

Surveyed as **capability tiers** — each mapped to the challenges it addresses, drawing on the five
related works, both book TOCs (`research_literature.md`: a TS-forecasting text and a GNN text), and
wider literature. *(Tiers describe the search space, not a commitment — §4 governs selection.)*

### Tier 0 — Baselines (the bar every model must clear)
- **Persistence** ("alert now → alert at `t+k`"), **seasonal-naive** (same hour-of-day / day-of-week),
  **climatology / seasonal-mean** (per-oblast, per-hour base rate — the harder bar at long leads), and
  **logistic regression** on the flat features. (TS book Ch.4 "Setting a Strong Baseline"; `02 §Stage 3`.)
- *Addresses:* establishes skill reference; persistence exposes the autocorrelation trap; climatology is
  the honest long-lead competitor as skill decays.

### Tier 1 — Tabular ML, Direct per-horizon (the workhorse)
- **Random Forest** — the **Pavlyshenko reproduction baseline** (non-parametric, distribution-free, no
  stationarity precondition). **Gradient boosting** — **LightGBM / XGBoost** (Teagan; Xue's XGBoost
  alternative), typically the strongest tabular learner on this kind of panel.
- **Imbalance:** class weights and/or downsampling (Xue k≈20). **Calibration:** isotonic/Platt on a
  held-out time block. **Interpretability:** SHAP / impurity importances → which features (neighbor,
  OSINT, weather, calendar) actually drive skill. (TS book Ch.6 feature engineering, Ch.8 ML models.)
- *Addresses:* imbalance, spatial signal (via neighbor features), calibration, cheap leak-safe iteration.

### Tier 2 — Sequence deep learning (temporal depth)
- **LSTM/GRU**, **TCN** (Teagan used both), **Transformers**, **N-BEATS / N-HiTS**, and the **Temporal
  Fusion Transformer** — TFT is notable because it **natively separates known-future vs observed-past
  covariates** (exactly our taxonomy) and emits **quantile/probabilistic** outputs; ViEWS teams used
  TFTs successfully. (TS book Ch.11–18.)
- *Addresses:* long-range temporal dependence beyond hand-built lags; probabilistic outputs; honest
  treatment of known-future calendar vs as-of exogenous. *Cost:* heavier, more leakage surface, needs
  more discipline — justified only if it beats Tier 1.

### Tier 3 — Spatio-Temporal GNN (the natural structural fit)
Nodes = 27 oblasts, edges = `edges.parquet`; node features = the flat per-`(t,oblast)` vectors.
- **Spatial encoders:** GCN, **GAT** (attention over neighbors), **GraphSAGE** (inductive, scalable) —
  GNN book Ch.6–8.
- **Spatio-temporal models:** **A3T-GCN** (attention temporal GCN, GNN book Ch.15 traffic forecasting —
  a close analogue), **STGCN**, **DCRNN**, **Graph WaveNet**, **MTGNN**, and **TGN** for dynamic graphs
  (GNN book Ch.13). Tooling: **PyTorch Geometric / PyG-Temporal**.
- *Addresses:* the spatial-diffusion challenge **explicitly** — message passing learns cross-oblast
  propagation that Tier 1 only approximates with `neighbor_*` scalars. *Cost:* highest complexity +
  leakage surface; gated hardest.

### Tier 4 — Reinforcement learning (framing, honest caveats)
- RL fits a downstream **alerting/resource policy** (when to warn / pre-position) **over** calibrated
  forecasts — **not** a forecaster itself. Risks: reward specification, **off-policy evaluation** on
  logged data, non-stationarity. (GNN book Ch.11 pairs RL with graph generation.) Kept as an explicit
  *future* tier, not an early target.

### Cross-cutting — uncertainty & scoring
- **Calibration / uncertainty:** conformal prediction, MC-dropout, quantile/probabilistic heads
  (TS book Ch.17). **Proper scores:** Brier, log-loss, **PR-AUC** (the binary analogue of ViEWS's CRPS),
  + reliability curves. Validation: **blocked/walk-forward CV with embargo** (TS book Ch.20).

---

## 4. Strategic Conclusion & Adaptable Framework

**Synthesis.** The literature points in different directions — RF (Pavlyshenko/Xue), DL sequence models
(Teagan), probabilistic transformers (ViEWS), and an explicit *don't-forecast* caution (Hrytsyna) — and
our data is uniquely spatial (adjacency graph) **and** adversarial (structural breaks). No single model
is obviously correct a priori. **Therefore we deliberately do NOT lock into one.** The architecture *is*
the framework that selects among models with evidence.

### 4.1 The promotion ladder (no premature lock-in)
Models are organized Tier 0 → 4. A model is **promoted only if** it beats **both** (a) the **baselines**
and (b) the **previous tier**, on **per-horizon proper scores** (PR-AUC / Brier / log-loss + reliability),
under an **identical** blocked-CV/embargo split — otherwise it is **rejected and logged** (negative
results are kept). We **start at Tier 0–1** and climb only when justified. A documented **stop rule**
(per Hrytsyna): if added complexity yields no per-horizon skill over climatology beyond a set tolerance,
we stop and declare the predictability ceiling for that horizon.

### 4.2 The shared verification harness (the real architecture)
Every tier plugs into one fixed harness so iterations are robust and directly comparable:
- **One leak-safe split scheme** — time-ordered/blocked CV with an **embargo gap**; a leakage-guard test
  fails the build if any feature for origin `t` reads `> t`, if any future row enters a training fold, or
  if `f_k` does not predict exactly `t+k` (`02 §Stage 3` "Testing & Verification").
- **One metrics + calibration suite** — proper scores + reliability; calibration fit on a held-out block.
- **One "must-beat-baseline" gate, per horizon** — release-blocking.
- **One Pydantic prediction contract** carrying `lead_hours` — identical I/O for every model, so Stage 4
  (FastAPI) and the UI are model-agnostic.
- **Versioned artifacts** — one per `(model, horizon k)`: serialized `f_k` + fitted pipeline + a metrics
  record (CV scheme, per-horizon skill-vs-baseline, calibration), reproducible under fixed seed.

### 4.3 Maximal data utilization — flat ⋈ graph
The framework consumes the **entire** `data/exports/` bundle, scaling how it's read by tier:
- **Tiers 0–1 (tabular):** read `airraid_analytical_long.parquet` **directly** — each row is already a
  Direct `(t, oblast, k)` training example with leak-safe features + label.
- **Tier 2 (sequence):** assemble per-oblast hourly **sequences** from `wide`/`long` histories (windowed
  inputs), labels per lead.
- **Tier 3 (ST-GNN):** **merge flat node features (long/wide) with `edges.parquet` topology and
  `oblasts.parquet` metadata** into **spatio-temporal graph snapshots** — at each hour, a 27-node graph
  whose node vectors are the flat features and whose edges are the adjacency `edge_index`; `centroid_lat/
  lon` enable distance-weighted edges. This is the explicit "merge flat features with graph topology"
  step. Neighbor leakage is held off by the same as-of/≤ `t` rule already baked into the export.
- **Exogenous discipline:** OSINT/weather/calendar enter under the `01 §D` taxonomy (calendar may touch
  `t+k`; everything else only ≤ `t`); the two weather mechanisms stay as separate features.

### 4.4 Implementation scaffolding (forward-looking — not built in this doc)
- **Module layout:** `src/airraid/models/{baselines,tabular,sequence,stgnn}.py` + a shared
  `src/airraid/eval/` harness (splitter, metrics, calibration, skill-vs-baseline gate) + leakage-guard
  tests under `tests/`. Reuses the export bundle; **no DB access at train time** (read Parquet only).
- **Per-tier dependencies (staged):** Tier 0–1 `scikit-learn` + `lightgbm`/`xgboost`; Tier 2+ `torch`;
  Tier 3 `torch-geometric` + `torch-geometric-temporal` (deferred until a tier earns it — avoids heavy
  installs before they pay off).
- **Maps to `02 §Stage 3` gates** (leakage guards, must-beat-baseline, calibration, artifact round-trip)
  and feeds Stage 4/5 (FastAPI + Dash) through the single Pydantic contract.

### 4.5 First concrete iteration (when execution begins)
1. Build the `eval/` harness + leakage-guard tests **first** (the gate must exist before any model).
2. Fit Tier 0 baselines per `k`; record the skill table (k = 1..6).
3. Fit Tier 1 RF + LightGBM per `k`, calibrated; promote only what beats baselines; inspect SHAP.
4. Only then consider Tier 2/3 — each as a *hypothesis tested against the same harness*, with results
   (win or loss) logged. Stop when the ceiling is hit.

---

## 5. Final Verdict — Designated Advanced Architecture

**Decision: `A3T-GCN` — Attention Temporal Graph Convolutional Network** (`torch_geometric_temporal.nn.recurrent.A3TGCN`).
Of the Tier-3 candidates, this is the **one** advanced model committed as the **apex of the promotion
ladder**: the model the framework climbs toward and which must beat the baselines to be promoted.

**Why A3T-GCN (it leverages the maximum extent of `data/exports/`):**
- **Uses BOTH modalities by construction — the explicit "flat ⋈ graph" goal (`§4.3`).** Per-hour
  **node-feature sequences** from the flat parquets are the temporal input; a **GCN spatial conv over the
  `edges.parquet` adjacency** propagates state across neighboring oblasts; a **GRU + temporal attention**
  models the hourly dynamics. Both the *temporal node features* and the *spatial graph topology* are
  first-class inputs — neither is discarded.
- **Right-sized & robust for our graph.** Our topology is a **small, static, real 27-node** oblast graph.
  A3T-GCN consumes that given adjacency directly — unlike Graph WaveNet / MTGNN (which *learn* an
  adjacency we already have) or TGN (built for *dynamic* topology we don't need). Lower variance, fewer
  ways to overfit, a proven traffic-forecasting analogue (`research_literature.md`, GNN-book Ch.15).
- **Built-in temporal attention → explainability.** Attention weights expose *which past hours* drove a
  prediction, complementing GNNExplainer/Integrated-Gradients (see `06 §5`) — essential because we must
  trust and narrate the forecast (Stage 5 analyst agent).
- **Clean Direct multi-horizon.** A single shared spatio-temporal encoder + a `Linear(H→6)` head emits one
  calibrated probability per horizon `k=1..6` — the Direct strategy of `§1.2`, without forecasting
  exogenous values first.
- **Low implementation risk.** A first-class `A3TGCN` layer exists in PyTorch-Geometric-Temporal (`§4.4`
  Tier-3 deps), so engineering effort goes into the leak-safe harness and evaluation, not reinventing the
  cell.

**This does not abandon the "don't lock in prematurely" discipline (`§4.1`).** Tier 0/1 baselines still
run first and define the promotion bar; A3T-GCN is promoted only if it beats persistence / seasonal-naive
/ climatology (and Tier 1) on **per-horizon proper scores** under the **same** blocked-CV/embargo split —
otherwise the result is logged and the simpler model ships. The full engineering blueprint
(architecture, walk-forward CV, loss/metrics, hyperparameters, MLOps, XAI, inference artifacts) is in
[`06-model-architecture.md`](./06-model-architecture.md).

---

*Cross-references:* what we predict & why → [`01`](./01-initial-research-analysis.md); how the pipeline
is staged + gates → [`02`](./02-general-workflow-architecture.md); the analytical artifact this consumes
→ [`04`](./04-analytics-eda.md); evidence base → [`researches/research_related_works.md`](../researches/research_related_works.md),
[`researches/research_literature.md`](../researches/research_literature.md),
[`researches/exogenous-variables-research.md`](../researches/exogenous-variables-research.md).
