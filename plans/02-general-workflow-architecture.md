# 02 — General Workflow Architecture

**Purpose.** This document turns the architectural vision for the Ukraine air-raid-alert project into
a concrete, staged engineering plan. It is structured around the **5-stage architecture** the project
owner specified, and for **every stage** it does three things:
- **Judge & Justify** — critically evaluate the proposal; where a component is heavier than the
  problem warrants, substitute a pragmatic Python-centric equivalent that *keeps the same interfaces
  and separation of concerns*.
- **Complement with Research** — map the findings of
  [`01-initial-research-analysis.md`](./01-initial-research-analysis.md) onto the stage.
- **Testing & Verification** — the strict analytical checks / automated Python tests that must pass
  before data or artifacts move to the next stage.

**Two hard constraints (non-negotiable):**
1. **Solely Python**, end to end. No Go / TypeScript / React / Java. Every stage — storage access,
   ETL, EDA, ML, API, UI — is Python, chosen for maximum velocity and a single mental model.
2. **Pydantic is the unified data contract.** The same Pydantic v2 models flow across every stage
   boundary, so "the shape of the data" is defined once and validated everywhere.

**Scale note (important).** The development timeline is **2–3 days**, but the **dataset is multi-year
historical** — years of hourly per-oblast alert logs, with structural breaks and wide
feature-engineering matrices. Architecture choices below optimize for *fast development over large
historical data*, not for a toy sample.

**Locked upstream decisions (from `01` and owner confirmation).** Target = **hourly binary alert
occurrence per oblast**, forecast over a **1–6 h lead-time band** via the **Direct multi-horizon**
strategy (one calibrated model per horizon, features anchored at origin `t`; primary horizon = 1 h;
onset as a secondary target — see `01 §D`); spatial unit = **oblast (~27)**; storage = **PostgreSQL +
SQLAlchemy**; backend = **FastAPI**; frontend = **Dash + Plotly**.

---

## Global Principles & Cross-Cutting Data Contract

These apply to all five stages and are the backbone that makes the stages composable.

- **Pydantic v2 as the inter-stage contract.** A single `schemas` module defines the models that
  cross stage boundaries:
  - `RawAlertEvent` — `oblast_id`, `start_ts` (UTC), `end_ts` (UTC) — the ingested event.
  - `HourlyOblastObservation` — `oblast_id`, `hour_ts`, `alert_active: bool` — the resampled panel row.
  - `FeatureRow` — the leak-safe feature vector for `(oblast, hour)` consumed by the model.
  - `PredictionRequest` / `PredictionResponse` — `oblast_id`, `ts`, `lead_hours ∈ {1..6}` →
    `probability`, `lead_hours`, `model_version`.
  - `AppConfig` via **`pydantic-settings`** — DB URL, paths, seeds, thresholds (one typed config).
- **Repository interface over storage.** All DB access goes through a `AlertRepository` protocol
  (Pydantic-typed in/out). The concrete `SqlAlchemyAlertRepository` is the implementation; this keeps
  SQL out of the analytics/ML/serving code and makes the store swappable without touching callers.
- **Separation of concerns / package layout:**
  `src/airraid/{config, schemas, storage, ingest, eda, features, models, api, ui}` with a mirrored
  `tests/` tree, `pyproject.toml`, and a `Makefile` exposing `make ingest|eda|train|serve|ui|test`.
- **Determinism & reproducibility.** Global seed in `AppConfig`; pinned dependencies; versioned data
  snapshots and model artifacts.
- **`pytest` is the promotion gate.** Nothing moves to the next stage until that stage's test suite
  (plus `mypy` type-checking) is green. The stage gates are detailed per stage below.
- **Deterministic core boundary.** The `features → train → CV → inference` path is strictly
  deterministic (fixed seeds, golden tests). Any LLM agent or workflow orchestration lives **only at
  the edges** (ingestion, reporting) and never inside that core — see *Optional Advanced Automation*
  below. Edge components emit **Pydantic-validated, versioned** outputs; the ML numbers remain
  authoritative. (Data-quality and drift monitoring are handled by deterministic Python checks +
  logging — the per-stage Testing & Verification gates — not by an LLM agent.)

---

## Stage 1 — Data Engineering (PostgreSQL + SQLAlchemy)

### Judge & Justify
A full Cloud/AWS stack (S3 + Glue + Redshift/Athena, IAM, Terraform) is **rejected**: for a
single-developer, 2–3 day build the infrastructure setup cost dwarfs any benefit, and it violates the
"maximum velocity, solely Python" mandate. The pragmatic equivalent that keeps the *same professional
structure* is **PostgreSQL accessed via SQLAlchemy**, hidden behind the Pydantic-typed
`AlertRepository` interface — so we retain a real relational system of record, transactions, and
referential integrity, while keeping storage swappable and SQL contained.

Two same-ecosystem pragmatic notes (no new languages, no architecture change):
- **TimescaleDB** (a Postgres extension) is an optional drop-in if the multi-year hourly panel needs
  hypertable-accelerated range scans — still "just Postgres."
- **Parquet** is used as the *feature-matrix / artifact export* format for the heavy columnar scans in
  Stages 2–3 (and optionally queried in-process with DuckDB), while Postgres remains the **system of
  record**. This is an optimization, not a second source of truth.

### What we ingest & store historically
- **Raw alert events** — `(oblast, start_ts, end_ts)` — from public historical sources
  (e.g. alerts.in.ua / ukrainealarm API / Kaggle air-alert dumps). *Exact source is confirmed at
  ingest, not assumed here.* Unstructured OSINT/Telegram sources, if used, flow through the optional
  extraction agent into a **staging** table first (see *Optional Advanced Automation* below) — never
  directly into the canonical store.
- **Reference tables:** canonical **oblast** table (~27 regions, stable IDs + names + centroids) and
  an **oblast adjacency** table (which oblasts border which) — needed for spatial features.
- **Calendar table:** hour/day-of-week/month/holiday flags over the full historical range.
- **Optional exogenous candidates (stored historically):** coarse war-phase indicators, and — if
  cheaply obtainable — weather windows relevant to drone/missile activity. These are *candidates*; we
  flag that the true drivers are largely **unobserved** (see Research below).
- **Derived hourly per-oblast panel** (`HourlyOblastObservation`) as a materialized view / table — the
  canonical analysis grid for Stages 2–3.

### Complement with Research (→ `01`)
- `01` §2/§4 mark **spatial-neighbor diffusion** (Pavlyshenko, Xue) as the highest-value signal →
  the **adjacency table is engineered now**, in Stage 1, so it is ready for feature building.
- `01` §3.6 (largely unobserved exogenous drivers) → we deliberately keep the exogenous set small and
  honest rather than over-collecting; the schema records *what we have*, and the ceiling is documented.
- `01` §3.5 (data-coverage / protocol changes over the war) → ingest records a `source`/`coverage`
  provenance column so structural breaks in *reporting* are distinguishable from breaks in *reality*.

### Testing & Verification (gate → Stage 2)
`pytest` + Pydantic validation must pass before any analysis runs:
- **Schema/type validation** of every `RawAlertEvent` (Pydantic): timezone-aware UTC, types correct.
- **Temporal integrity:** `end_ts > start_ts`; **no overlapping** intervals within one oblast.
- **Oblast canonicalization:** every event maps to exactly one of the ~27 canonical oblasts (FK
  referential-integrity check; reject unknown region strings).
- **Idempotent upsert:** re-running ingest does not duplicate rows.
- **Coverage & gaps:** row-count / date-range assertions; explicit gap-detection report (missing
  hours flagged, not silently filled).
- **Panel reconciliation:** the derived hourly panel's "active hours" reconcile with raw event spans.

---

## Stage 2 — Analytical Section (EDA via Duration & Count/Frequency)

### Judge & Justify
The proposal to profile with **Duration** and **Count/Frequency** even though the ML target is binary
occurrence is **endorsed and sharpened**. `01` §B concluded those two are *poor ML targets* (duration
has irreducible unobserved variance; count collapses/zero-inflates) — but they are **excellent
descriptive lenses**. Using them here (and *not* as model targets) is exactly the right separation:
deep historical understanding without contaminating the modeling decision.

### What we analyze
- **Trend / historical profiling:** national and per-oblast alert **counts over time** — the primary
  tool for spotting **structural breaks / regimes** across the multi-year span.
- **Duration profiling:** distributions/histograms of alert durations per oblast (the Hrytsyna lens),
  including heavy-tail inspection.
- **Seasonality:** hour-of-day, day-of-week, monthly profiles; calendar heatmaps.
- **Spatial structure:** cross-oblast correlation and **adjacency correlation** heatmaps (the
  Pavlyshenko signal) to confirm neighbor dependence before we engineer neighbor features.
- **Class balance:** quantify the **base rate** of alert-active hours (the imbalance ratio) and its
  drift over time (the ViEWS zero-inflation lens, adapted to a binary base rate).
- **Diagnostics for understanding (not as model prerequisites):** **ADF / KPSS** (stationarity),
  **ACF / PACF** (autocorrelation structure → informs lag choices), and **changepoint / structural-
  break detection** over the long timeline.

### Complement with Research (→ `01`)
- Hrytsyna → duration histograms & descriptive profiling.
- Pavlyshenko → adjacency correlation + calendar seasonality (validates the feature plan).
- ViEWS → visualize skew / base-rate so the imbalance strategy in Stage 3 is evidence-based.
- `01` §3.2/§3.5 → structural-break detection is a *first-class EDA output*, because a multi-year
  conflict series is non-stationary by nature.
- `01`'s "diagnostics for understanding" principle → ADF/ACF are run to *understand the DGP*, not to
  gate a (non-parametric) model.

### Testing & Verification (gate → Stage 3)
- **Reconciliation:** EDA aggregates (e.g. total alert hours per oblast) must **match Stage-1 raw**
  exactly — guards against silent aggregation bugs.
- **Determinism:** all figures/summary tables regenerate identically under the fixed seed.
- **Cleanliness:** assert no NaN/timezone drift introduced by resampling.
- **Typed EDA summary:** emit a Pydantic `EdaSummary` (detected seasonality periods, breakpoints,
  base rate per oblast) that Stage 3's feature config **consumes** — making EDA findings a machine-
  checked input, not just prose.

---

## Stage 3 — ML Workflow

### Judge & Justify
The proposal (several baselines + advanced models, class-imbalance focus, spatial features, strict
verification loops, saved artifacts) is **exactly right** and is the heart of `01`. The only
discipline we add is making the **strict verification loop a hard gate**, not a guideline — because
`01` identifies leakage as the single most likely way this project fools itself.

### Target & features
- **Target (locked):** for each `(oblast, origin hour t)`, predict `alert_active(t+k)` for each
  horizon **`k ∈ {1…6}` hours** — the **Direct multi-horizon** strategy: **one calibrated model
  `f_k` per horizon** (primary `k=1`), each trained directly on ground truth. **Onset** (a *new* alert
  at the target hour given none active at `t`) is a secondary, harder target. Direct is chosen over
  **Recursive** so we never feed predictions back as inputs and never need to forecast exogenous
  values first (full rationale + the future-exogenous paradox in `01 §D`).
- **Feature matrices over the long timeline** (`FeatureRow`, persisted as a Parquet feature store),
  governed by the **feature-availability taxonomy** (`01 §D`) so every model is leak-safe:
  1. **Known-future deterministic** — calendar + **Fourier seasonal terms**; known for all future
     hours → evaluated at the *target* hour `t+k`.
  2. **Lagged endogenous & spatial** — lag/rolling/decay summaries of the oblast's own and
     **neighbor-oblast** alert state; used only with values **≤ t**.
  3. **Truly-exogenous unknown-future** (weather/ops) — dropped or last-known-at-`t` (largely
     unobserved per `01 §3.6`).
  General rule: a feature for origin `t` / horizon `k` may use information only up to and including
  `t`. The horizon lives in the target, not the features.

### Models
- **Baselines (per horizon):** **persistence** ("alert now → alert at `t+k`"), **seasonal-naive**
  (same hour/day-of-week history), a **climatology / seasonal-mean** baseline (the harder bar at
  longer leads, per `01 §D`), and **logistic regression**.
- **Advanced (per horizon):** **Random Forest** (the Pavlyshenko reproduction baseline) and
  **gradient boosting** (XGBoost/LightGBM). Trained as the Direct family `{f_k}` (independent fits, or
  a multi-output wrapper) — small enough at 6 horizons to fit in parallel.
- **Class imbalance:** class weights and/or **downsampling** of the majority (no-alert) class — the
  Xue technique.

### Strict verification loop (core of `01`)
- **Time-ordered / blocked cross-validation with an embargo gap** — never shuffled.
- **Calibrated probabilities** (e.g. isotonic/Platt) — required because the UI colors by probability.
- **Metrics:** **PR-AUC, Brier, log-loss**, and **reliability curves** — never raw accuracy.
- **Skill over baseline, per horizon** is the promotion bar: a model is only "better" if it beats the
  persistence / seasonal-naive / climatology baselines on proper scores **at that horizon `k`** —
  with skill expected to decay toward the base rate as `k` → 6 h (reported, not hidden).

### Artifacts
**One artifact per horizon** `k`: serialized `f_k` + fitted feature pipeline + a metadata/metrics
record (model version, **horizon `k`**, CV scheme, per-horizon skill-vs-baseline, calibration),
versioned, carrying the Pydantic prediction schema.

### Complement with Research (→ `01`)
Imbalance handling (Xue), spatial-diffusion features (Pavlyshenko/Xue), calibrated probabilities &
proper scoring (ViEWS), time-ordered CV & leakage guards (the Pavlyshenko/Xue failure they did *not*
fix), RF reproduction baseline (Pavlyshenko), and Hrytsyna's predictability-ceiling expectation.

### Testing & Verification (gate → Stage 4)
- **Leakage guards (the critical tests):** assert each feature for origin `t` / horizon `k` uses only
  data `≤ t` (taxonomy class 2/3 never read `> t`; only class-1 deterministic terms may reference the
  target hour); assert CV folds are strictly chronological with the embargo gap (a test that fails if
  any future row enters a training fold); assert each `f_k` predicts exactly `t+k`.
- **Inference-I/O schema tests** against `PredictionRequest/Response` (including `lead_hours`).
- **"Must beat baseline" gate, per horizon:** the suite fails the promotion if any chosen horizon's
  model does not exceed its persistence/climatology baseline on Brier/PR-AUC at horizon `k`.
- **Calibration check:** reliability within tolerance.
- **Artifact round-trip / reproducibility:** reload artifact → identical predictions under fixed seed.

---

## Stage 4 — Backend Layer (FastAPI)

### Judge & Justify
**FastAPI over Flask.** The owner mandated Pydantic everywhere; FastAPI is **Pydantic-native**, so the
request/response models *are* the same `schemas` used in Stages 1–3 — zero contract duplication. It is
async, typed, and emits an **OpenAPI** spec for free. Flask would require bolting on validation that
FastAPI gives natively. The API is a **thin, stateless wrapper** around the saved artifacts (loaded
once at startup) — no business logic leaks into serving.

### Endpoints
- `GET /health` — liveness.
- `GET /metadata` — model version, CV scheme, **available horizons (1–6 h)** and **per-horizon
  skill-vs-baseline** (transparency).
- `POST /predict` — `PredictionRequest (oblast, ts, lead_hours ∈ {1..6})` → `PredictionResponse
  (probability, lead_hours, version)`. Routes to the Direct model `f_k` for `k = lead_hours`.
- `POST /predict/batch` — many `(oblast, ts, lead_hours)` in one call.
- `GET /predictions?ts=...&lead_hours=...` — serve the **precomputed historical prediction grid** for
  the UI scrubber (fast path; see Stage 5).

### Complement with Research (→ `01`)
- Serve **calibrated probabilities**, not hard labels (ViEWS / `01` honesty caveat).
- Expose **model version + skill metadata** so the consumer can see the leakage-safe provenance —
  reproducibility as a first-class API concern.

### Testing & Verification (gate → Stage 5)
`pytest` + **FastAPI `TestClient`**:
- **Schema/contract validation** — responses always conform to `PredictionResponse`.
- **Model-load smoke test** — app starts and loads the artifact.
- **Golden-prediction regression** — a fixed known input yields the expected probability within a
  tolerance (catches silent model/feature drift).
- **Error handling** — unknown oblast or out-of-range timestamp returns a clean 4xx, not a 500.
- **OpenAPI ↔ Pydantic** consistency; basic **latency** sanity check.

---

## Stage 5 — Frontend Layer (Dash + Plotly, oblast-level map)

### Judge & Justify
**Dash + Plotly**, per owner choice — its **callback model** is well suited to the "real-time feel"
requirement: dragging the timestamp slider triggers partial updates of the choropleth without a full
page rerun. Solely Python (no JS/React written by us). The map is **oblast-level (~27)**, matching the
locked ML target so the visualization is coherent with what the model actually predicts (district/raion
granularity is explicitly out of scope — it would require a different target than `01` fixed).

### Build
- **Plotly choropleth** of Ukraine's ~27 oblasts (oblast GeoJSON), each colored by the model's
  **alert probability** at the selected lead time.
- A **historical timestamp slider** (the "scrollbar") scrubs through the multi-year history, giving a
  "real-time" replay feel as the user drags it, plus a **lead-time selector (1–6 h)** that chooses
  which Direct horizon `f_k` to display — so the map shows `P(alert at selected_ts + lead)`.
- **Performance pattern (key for large history):** **precompute** the historical prediction grid
  (`oblast × hour × lead → probability`) into Postgres/Parquet during/after Stage 3; the slider +
  lead selector **index** this grid for instant repaint, while `POST /predict` is used for the live
  "current selection" path. This avoids recomputing predictions on every slider tick.
- **Fixed probability color scale** + legend (so colors are comparable across timestamps); tooltip
  shows the probability and, optionally, the **actual** alert state — making *skill vs persistence*
  visually honest.

### Complement with Research (→ `01`)
- Color by **probability** (uncertainty surfaced), not a binary label — the ViEWS / `01` principle.
- Optional actual-vs-predicted overlay operationalizes Hrytsyna's caution: the user can *see* when the
  model merely tracks persistence versus when it adds genuine lead-time skill.

### Testing & Verification
- **Data-contract tests:** every oblast in the GeoJSON maps to exactly one prediction series; no
  missing or extra oblasts (set-equality check against the canonical ~27).
- **Slider bounds == data time range** (no scrubbing into empty space).
- **Lead-selector tests:** lead options are exactly `{1..6}`; the precomputed grid is complete across
  every `(oblast, hour, lead)` requested by the UI.
- **Color-mapping correctness:** probability → color is monotonic and uses the fixed scale.
- **Callback smoke tests:** Dash callbacks import and execute on a tiny fixture without error.
- **Gap handling:** timestamps with missing predictions render a neutral "no data" state, not a crash.

---

## Optional Advanced Automation — LangGraph Agents (Python, at the deterministic boundary)

**Principle.** LLM agents and workflow orchestration add value **only at the edges** of the pipeline
(ingestion, reporting). They **never** touch the `features → train → CV → inference` core, so
reproducibility (fixed seeds, golden tests, leakage guards) is untouched. Every agent output is
**Pydantic-validated and versioned**; the deterministic ML numbers remain authoritative.
*Data-quality and drift monitoring are intentionally **not** agent-driven* — they are handled by
standard, lightweight **deterministic Python scripts + logging** (the per-stage Testing & Verification
gates), which is cheaper, fully reproducible, and sufficient for our timeline.

**Tooling — solely Python.** Agentic reasoning uses **LangGraph** (Python); scheduling/orchestration
uses a **Python-native scheduler (Prefect / Dagster / APScheduler)**. **n8n is deliberately not used**
— it is Node-based and would break the solely-Python constraint; the Python schedulers above give the
same cron/glue capability inside our stack. Agents live in `src/airraid/agents/`, importable in
isolation from `features/` and `models/`.

### Use case A — Stage 1: Static OSINT insert (one-time, frozen dataset)
OSINT/Telegram-derived flags (`mig_31_airborne`, `tu_95_takeoff`) are treated as a **frozen historical
dataset**, NOT a live feed. A single **insert-once** script **Pydantic-validates** a real OSINT export
and writes it to `exogenous_features` (source=`telegram`) via an idempotent UPSERT. **No daily scraper,
cron, scheduler, or dynamic LangGraph pipeline** — the data is static and never time-updated. If a raw
export needs parsing into the frozen file, a **local Ollama** model may be run **once, offline** to
produce it (not part of the live pipeline).
- *Determinism preserved:* a fixed frozen input → a fixed table state; re-running is a no-op (idempotent UPSERT).
- *No synthetic data:* if no real OSINT export is present, the script inserts nothing and logs it — flags are never fabricated.

### Use case B (flagship) — Reporting / Stage 5: narrative "analyst" layer (LangGraph)
**Now elevated into the full Narrative Analyst Agent — see
[`07-narrative-analyst-agent.md`](./07-narrative-analyst-agent.md)** (containerized, read-only,
self-extending MCP + LangGraph). The sketch below is the original boundary design; `07` is the
authoritative spec.

**This is the project's highest-value agent — its "superpower."** It turns the deterministic model
outputs into **decision-grade narrative**: compelling for project demonstrations, and genuinely useful
for internal decision-making (a human reads *"elevated P(alert) across eastern oblasts at +3 h; skill
vs persistence +X"* far faster than a probability grid). Given the model's **calibrated probabilities
+ metadata** (deterministic inputs), the agent generates natural-language situational summaries for
the UI or a daily digest, with an optional **schema-constrained text-to-SQL** tool over a read replica
for ad-hoc EDA questions.
- *Determinism preserved:* read-only over authoritative pipeline outputs; all numbers come from the
  ML layer, the agent only narrates.
- *Testing:* numeric claims must **match the source predictions** (the agent quotes pipeline values
  via tool-use that returns exact numbers; assert agreement) — guards against hallucinated figures.

**MCP-ready architecture (forward-looking).** This agent is deliberately designed against a clean
**tool-interface boundary** so it is **Model Context Protocol (MCP)-ready**. Today it narrates over
precomputed outputs; in the future, when we need complex ad-hoc analytics or want to **verify the test
statistics behind specific ML methods**, we will *not* hardcode that math into the LLM (which would
risk hallucinated or subtly wrong statistics). Instead, we **expose our deterministic Python
statistical functions as MCP Tools** — the same authoritative implementations reused from
`src/airraid/{eda, models}` (e.g. ADF/KPSS stationarity, Ljung-Box, calibration / skill-vs-baseline
scoring). The LangGraph agent then **dynamically** chooses which tool to call, queries the data, runs
the *rigorous, deterministic* test, receives exact numbers back, and synthesizes the narrative around
them.
- *Why this is the right boundary:* the statistics stay in authoritative, version-controlled,
  unit-tested Python; the LLM only orchestrates *which* analysis to run and *how* to explain it. This
  **strengthens** the deterministic-core guarantee rather than eroding it — and is solely-Python (the
  MCP tools are Python functions served over a Python MCP server).
- *Scope:* the MCP tool layer is **now specified in [`07`](./07-narrative-analyst-agent.md)** — a
  containerized, read-only, **self-extending** MCP + LangGraph agent (it can synthesize a new analytical
  tool on demand, sandboxed). The tool-interface boundary designed here plugs into `07` without a redesign.
- *Containment (`07` §4):* the agent runs in an **isolated container with duplicated, read-only copies of
  `data/exports` + `artifacts`**, so the dynamic code generator can never delete or corrupt the real
  training data or model weights — physically reinforcing the deterministic-core guarantee above.

---

## Cross-Cutting Verification & Stage Gates

- **`pytest` is the promotion gate at every boundary** — data/artifacts move forward only when the
  current stage's suite (plus **`mypy`**) is green. The per-stage gates above are concrete.
- **Pydantic schemas enforce inter-stage contracts** — a change to a shared model breaks the tests of
  every stage that depends on it, surfacing drift immediately.
- **Determinism everywhere** — fixed seeds; versioned data snapshots and model artifacts.
- **End-to-end smoke test** — a tiny synthetic fixture flows the *entire* chain (ingest → panel →
  features → train → API response → UI data frame), proving the stages compose before any real run.
- **Leakage is the headline risk** (`01`): the Stage-3 leakage-guard tests are the most important in
  the repository and are treated as release-blocking.

---

*Cross-references:* target/granularity rationale and all research citations live in
[`01-initial-research-analysis.md`](./01-initial-research-analysis.md). This document defines **how**
we build; `01` defines **what** we predict and **why**.
