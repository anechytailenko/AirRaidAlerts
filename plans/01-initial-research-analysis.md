# 01 — Initial Research Analysis: Methodological Meta-Analysis of Related Works

**Purpose.** This document is the methodological foundation for our Ukraine air-raid-alert
time-series project. It is *strictly* a meta-analysis of the five sources captured in
[`research_related_works.md`](../researches/research_related_works.md) — no modeling, no data work. Its job is
to decide what methods to reuse, what to avoid, and what domain difficulties to expect, all judged
against **our anchored task**.

**Our anchored task (the lens for everything below).** We forecast **binary air-alert occurrence per
oblast over a short operational lead-time band of 1–6 hours** — *"will oblast X be under alert k hours
from now, for k = 1…6?"* (primary horizon = 1 h; horizon strategy derived in §D). This is a
**classification** problem in which **severe class imbalance** (alert-active intervals are the rare
class) is the governing statistical condition, the data exhibits **strong temporal autocorrelation**
and **cross-oblast spatial diffusion**, and the data-generating process is **adversarial and
non-stationary**. Sources are evaluated for relevance to *this* task; aspects that belong to a
different workflow are explicitly excluded in Section 4.

**Integrity note.** Every factual claim traces to the extraction text. Where a paper does not report
something (e.g. Hrytsyna builds no model; most papers run no assumption tests), that absence is
stated as a finding rather than filled in.

### One-glance verdict table

| Source | Domain | Model ↔ Data pairing | Fit verdict |
|---|---|---|---|
| **Pavlyshenko & Pavlyshenko (2024)** | Direct — UA air alerts | RF classifier on minute-level per-oblast alerts | **Qualified good fit** — right model class, weak temporal-validation rigor |
| **Hrytsyna (2022)** | Direct — UA air alerts | Descriptive EDA, *no model* | **Fit N/A** — appropriate for its EDA scope; "don't forecast" is a hypothesis, not proof |
| **Teagan (2025)** | Analogue — RU equipment losses | ARIMA + Prophet/LSTM/TCN/XGBoost on counts | **Mixed fit** — DL reasonable; ARIMA questionable (stationarity untested) |
| **Hegre et al. / ViEWS (2024)** | Analogue — conflict fatalities | Count/zero-inflation-aware + probabilistic, CRPS-scored | **Exemplary fit** — the model-condition alignment benchmark |
| **Xue et al. (2025)** | Analogue — conflict onset → migration | RF + downsampling for imbalance | **Good fit with caveat** — imbalance handled; temporal leakage not diagnosed |

---

## Section 1 — Source-by-Source Critical Extraction & Evaluation

### 1.1 Pavlyshenko & Pavlyshenko (2024) — *Predictive Analytics of Air Alerts in the Russian-Ukrainian War*

- **Advantages.** Most directly on-task source: per-oblast air-alert data (25 Mar 2022 – 6 Nov 2024),
  short horizons (5/15 min), and an explicit recognition that **alert status in one oblast depends
  strongly on adjacent oblasts** (geospatial dependence) plus calendar seasonality (hour/day/month).
  Probabilistic class scores via `predict_proba` and ROC-based evaluation.
- **Disadvantages / limitations.** Stated aim ("forecast the *duration* of air alerts") does not
  match the operationalized target (binary *occurrence/continuation*) — a goal–target drift. Only a
  subset of oblasts analyzed. **No** statistical diagnostics whatsoever (no ADF/KPSS, Ljung-Box, or
  ACF/PACF).
- **Failures / risks.** On a 1-minute, heavily autocorrelated series, the paper states **no guard
  against look-ahead leakage** when constructing next-window features/splits — accuracy/ROC can be
  optimistically biased if neighboring minutes leak across train/test.
- **Authors' conclusions.** Air alerts are partly predictable from temporal + neighboring-region
  features; adjacency and seasonality are the most useful signals.
- **How model+data drove results.** Choosing **Random Forest classification** (non-parametric,
  distribution-free) is the *right* move for this data: it imposes **no stationarity/normality/
  homoscedasticity** requirement, so there is no model-condition violation on distributional grounds.
  The strong reported performance is plausibly real *signal* (adjacency + diurnal patterns), but its
  *magnitude* is not trustworthy because the temporal-validity condition (independence of train/test
  under serial correlation) is unverified.
- **Verdict: QUALIFIED GOOD FIT.** Correct model–data class; the weakness is validation rigor, not
  the model choice. This is our blueprint *and* our cautionary tale simultaneously.

### 1.2 Hrytsyna (2022) — *What You Don't Know About Air Alerts in Ukraine*

- **Advantages.** Clean, honest exploratory profiling of the same family of public data (air_alert_ua
  Telegram → Kaggle): regional alert rankings, Kyiv time distribution, Kharkiv duration histogram,
  cumulative shelter-time framing. Useful intuition for what the raw data looks like.
- **Disadvantages / limitations.** Very short window (~1.5 months, Mar–May 2022); no exogenous
  variables; **no statistics, no model, no forecast**.
- **"Failure" (by design).** The author explicitly considered an ML model to predict next alerts and
  **declined** — *"That could work in a normal world"* — judging targeting too adversarial/intentional
  to forecast reliably.
- **Authors' conclusions.** Air-alert timing is driven by deliberate adversary decisions; descriptive
  understanding is valuable but predictive modeling was deemed unreliable for the period studied.
- **How model+data drove results.** No model → no model-condition question. The data supported solid
  description but the author chose not to extrapolate.
- **Verdict: FIT N/A.** Appropriate for its EDA scope. Crucially, her pessimism is a **testable
  hypothesis about a predictability ceiling**, not evidence that occurrence forecasting is futile —
  we treat it as a prior to measure against, not a verdict.

### 1.3 Teagan (2025) — *Forecasting Russian Equipment Losses Using Time Series and Deep Learning Models*

- **Advantages.** Broad model comparison (ARIMA, Prophet, LSTM, TCN, XGBoost) on a real conflict
  count series (WarSpotting OSINT), daily and monthly; sensible feature engineering per model (log +
  differencing for ARIMA; lags + moving averages for XGBoost; weekday indicators for LSTM); honest
  exclusion of incomplete-reporting months.
- **Disadvantages / limitations.** Exogenous signals barely used (mostly univariate); **no** ADF/
  KPSS/Ljung-Box/ACF diagnostics; only Prophet emits uncertainty (95% intervals), the rest are
  point-only.
- **Failure / risk.** ARIMA's **stationarity precondition is handled mechanically** (log to stabilize
  variance, `d=1` differencing to remove trend) **but never verified** — no test confirms the
  differenced series is stationary, and no Ljung-Box confirms white-noise residuals (the diagnostic
  that validates the fit). Homoscedasticity assumed, not checked.
- **Authors' conclusions.** Multiple methods can track attrition trends; deep models and Prophet
  capture trend/seasonality with varying success.
- **How model+data drove results.** For the **non-parametric** models (LSTM/TCN/XGBoost) the missing
  tests are low-stakes — they impose no stationarity requirement, so the model–data pairing is
  reasonable. For **ARIMA**, the pairing is shakier: it is a linear-Gaussian model applied to
  skewed/bursty counts with unconfirmed stationarity, so any clean-looking ARIMA result rests on
  unverified assumptions.
- **Verdict: MIXED FIT.** DL/GBM side = acceptable fit; ARIMA side = questionable fit due to
  assume-don't-verify stationarity. The lesson transfers even though our target is classification.

### 1.4 Hegre et al. / ViEWS (2024) — *2023/24 Prediction Challenge: Fatalities with Uncertainty*

- **Advantages.** The methodological gold standard here: it treats the **data's actual statistical
  shape as a first-class design constraint**. Observed fatalities are heavily skewed and
  **zero-inflated** (~87% zeros country-month, ~99% PRIO-GRID), and several teams chose model families
  *built for that* — negative-binomial, hurdle/zero-inflated, quantile regression. Output is a **full
  predictive distribution** (15–1000 samples), scored with **proper probabilistic metrics** (CRPS,
  Ignorance/log score, MIS).
- **Disadvantages / limitations.** Method-agnostic benchmark → feature sets and assumption-checking
  are inconsistent across the 13 teams; no uniform stationarity testing (not the governing condition
  for count models anyway).
- **"Failures."** Documented field-wide difficulty: many models gravitate to the mean and **miss
  sharp escalations** — conflict spikes are the hardest part.
- **Authors' conclusions.** Honest uncertainty quantification is essential; matching the conditional
  distribution to zero-inflated counts matters more than model exotica; tail/spike prediction remains
  unsolved.
- **How model+data drove results.** This is the cleanest example in the set of **aligning model
  assumptions to data statistics** — count/zero-inflation-aware likelihoods fit zero-heavy counts,
  and probabilistic scoring rewards calibrated uncertainty rather than overconfident points.
- **Verdict: EXEMPLARY FIT.** The reference for *how* to match model conditions to data and how to
  evaluate — even though the target (fatalities) is not ours.

### 1.5 Xue et al. (2025) — *ML to Forecast Conflict Events for Forced-Migration Models*

- **Advantages.** Peer-reviewed; **daily, locality-level binary conflict-occurrence** classification —
  structurally the closest analogue to our per-oblast occurrence target. Correctly identifies **class
  imbalance** as the governing condition and addresses it via **downsampling non-events (k≈20)**.
  Rich spatial/temporal features: **spatial-diffusion** signals (past-week/month neighbor conflict)
  and a **31-day autoregressive** history; evaluated with ROC-AUC and significance tests.
- **Disadvantages / limitations.** Conflict-occurrence ML is one component of a larger agent-based
  migration pipeline (extra machinery irrelevant to us); RF/XGBoost output **point/binary**
  predictions (ensemble replicas give some aleatoric spread, but not a calibrated distribution).
- **Failure / risk.** With 31-day autoregressive sequences over a daily panel, **temporal
  autocorrelation and train/test leakage are not formally diagnosed** — the same exposure as
  Pavlyshenko.
- **Authors' conclusions.** ML conflict-onset forecasts are good enough to improve downstream
  migration simulations; spatial diffusion + recent history are strong predictors; imbalance handling
  is essential.
- **How model+data drove results.** RF + **downsampling** is a sound model–data match for rare-event
  classification (imbalance is the right condition to target, and they targeted it). Reported AUC is
  credible signal, but, as with Pavlyshenko, the absence of explicit temporal-split discipline leaves
  a leakage question over the exact numbers.
- **Verdict: GOOD FIT WITH CAVEAT.** Imbalance handled correctly; temporal-validation rigor is the
  gap. Directly transferable to our problem.

---

## Section 2 — Strategic Synthesis (Adopt vs Avoid)

### ✅ What to apply (extract and reuse)
- **Imbalance handling as a first-class step (Xue).** Our alert-active intervals are the rare class —
  use class weights and/or downsampling, and *evaluate* on imbalance-aware metrics (below). This is
  the single most transferable technique in the set.
- **Spatial neighbor / adjacency features (Pavlyshenko, Xue).** Encode the recent alert state of
  *adjacent oblasts* and broader spatial-diffusion signals — both papers found adjacency among the
  strongest predictors. Highly relevant given Ukraine's threat geography.
- **Calendar + lag/rolling features (all modeling papers).** Hour/day-of-week/month, plus lagged and
  rolling-window summaries of an oblast's own recent alert history.
- **Probabilistic output + proper scoring (ViEWS).** Emit **calibrated probabilities**, not just
  labels, and score with **Brier / log-loss / PR-AUC** (the binary analogues of ViEWS's CRPS) so we
  reward honest uncertainty and handle imbalance correctly.
- **Explicit assumption & dependence diagnostics + strict temporal validation.** Run ADF/ACF/PACF to
  *understand the DGP* and, decisively, use **time-ordered / blocked cross-validation** so we do not
  repeat the leakage exposure left open by Pavlyshenko and Xue.
- **Match the conditional model to the data shape (ViEWS principle).** Even within classification,
  prefer methods/objectives suited to rare, bursty events over off-the-shelf accuracy-optimizing
  defaults.

### ❌ What to avoid (explicit anti-patterns)
- **Assume-don't-verify stationarity (Teagan).** If we ever bring in a classical TS model (e.g. on
  alert *counts*), never difference-and-hope — test stationarity (ADF/KPSS) and residual whiteness
  (Ljung-Box).
- **Random splits / ignored temporal leakage on autocorrelated series (Pavlyshenko, Xue risk).** The
  most likely way we fool ourselves. Forbid shuffled splits; enforce chronological splits with an
  embargo/gap.
- **Accuracy-only evaluation on imbalanced data.** Accuracy is near-useless when one class is rare —
  it would reward a "never alert" predictor. Use PR-AUC / Brier / recall-at-fixed-precision.
- **Point-only forecasts with no uncertainty.** Operationally, calibrated probabilities are far more
  useful than a hard 0/1 for an alerting context.
- **Treating Hrytsyna's "don't model" as a default.** Adopt it as a *measurable performance ceiling*
  to test against, not as a reason to skip modeling.

---

## Section 3 — Domain Challenges & Difficulties (our specific task)

1. **Adversarial, intentional data-generating process.** Unlike weather, alerts follow deliberate
   enemy decisions designed to be unpredictable. Learned historical patterns can break the moment
   tactics change — the core caution Hrytsyna raised and ViEWS observed as missed spikes.
2. **Non-stationarity & regime shifts.** Over the war, attack patterns, weapon mixes (drones vs
   missiles), and alert-issuing policy evolve. The series has structural breaks; a model trained on
   one regime may not transfer — concept drift must be expected and monitored.
3. **Severe class imbalance + bursty clustering.** Alert-active windows are the minority class and
   arrive in temporal clusters (waves), not independently — challenging both estimation and
   evaluation.
4. **Strong autocorrelation & spatial diffusion.** Adjacent minutes/hours and adjacent oblasts are
   highly dependent. This is *signal to exploit* (neighbor features) **and** *a leakage hazard* to
   defend against in validation.
5. **Concept drift & data-coverage changes.** Reporting channels, oblast definitions, and alert
   protocols shift over time; coverage/quality is not constant across the dataset.
6. **Largely unobserved exogenous drivers.** The true causes (launch decisions, military operations,
   weather windows favorable to drones/missiles) are mostly not in our data, capping achievable skill
   and arguing for honest uncertainty over false precision.

---

## Section 4 — Cross-Paper Conclusion & Direct Relevance

### Commonalities across multiple papers
- **Assumption testing is routinely skipped** — Pavlyshenko, Teagan, and Xue all omit stationarity/
  autocorrelation diagnostics; only ViEWS (implicitly, via distribution choice) takes data shape
  seriously.
- **Classification dominates for "will an event occur"** — Pavlyshenko and Xue both frame occurrence
  as supervised classification with Random Forest.
- **Spatial-neighbor + temporal features recur** as the strongest, most reused signal family
  (Pavlyshenko, Xue).
- **Imbalance / zero-inflation is pervasive** in conflict event/severity data (Xue's rare events,
  ViEWS's zero-heavy counts).
- **Point forecasts are the norm; calibrated uncertainty is the exception** (only ViEWS makes
  uncertainty the deliverable).
- **Sharp escalations / spikes are the universal hard part** (explicit in ViEWS; implied by
  Hrytsyna's adversarial caution).

### Unique aspects & how we will face them in *our* project
- **Pavlyshenko (2024) — our direct blueprint.** Same data shape (per-oblast alert logs), same
  feature instincts (adjacency + calendar), same probability output. We will face its **exact leakage
  risk** on autocorrelated minute/hour data → we adopt its features but fix validation with strict
  time-ordered splits.
- **ViEWS (2024) — our evaluation north star.** We will face the same need to express **uncertainty**
  and to **not be fooled by accuracy**; we transfer its proper-scoring philosophy as Brier/log-loss/
  PR-AUC for our binary target.
- **Xue (2025) — our imbalance + spatial-diffusion template.** Its daily binary occurrence + neighbor
  diffusion + downsampling maps almost one-to-one onto our per-oblast imbalanced occurrence problem;
  we will face the identical rare-event and temporal-dependence challenges.
- **Teagan (2025) — secondary, a stationarity cautionary tale.** Relevant only if/when we model alert
  **counts** with classical TS; its lesson is "test, don't assume." Less central because our anchored
  target is classification.
- **Hrytsyna (2022) — expectation calibration.** We will face the same adversarial unpredictability;
  we use her caution to set a realistic **performance ceiling** and to justify probabilistic, not
  overconfident, outputs.

### Explicitly out of scope (aspects we will *not* encounter — excluded to keep relevance sharp)
- **Agent-based forced-migration simulation & UNHCR refugee-camp validation (Xue)** — a downstream
  modeling layer we are not building.
- **Fatalities-as-target and the UCDP / PRIO-GRID country-month machinery (ViEWS)** — different target
  and spatial framework.
- **OSINT photo/video equipment-verification pipeline and attrition counting (Teagan)** — a different
  data-collection problem entirely.

---

## Target Formulation & Granularity Judgment

The assignment fixes only the domain ("Time Series Analysis of air raid alerts in Ukraine", Python
stack) and leaves the **target variable and data granularity to us**. This section derives — rather
than assumes — the best choice given our constraints: a **2–3 day development timeline** working over
a **multi-year historical dataset** (years of air-alert logs, with structural breaks and large
feature-engineering matrices — *not* a short sample). It is judged on the data realities and the
successes/failures in our five sources. (Row-count figures below are illustrative order-of-magnitude
arithmetic for feasibility reasoning, not measured dataset statistics.)

### A. Data Frequency — Minute vs Hourly

The raw data is event-level (alert start/end timestamps per oblast); any frequency is a resampling
choice. The candidates are **minute-level** (as in Pavlyshenko) and **hourly aggregation**.

| Criterion | Minute-level | Hourly aggregation |
|---|---|---|
| **Autocorrelation** | **Near-deterministic.** An alert at 12:01 all but guarantees one at 12:02 — minute-to-minute the target barely changes. | Adjacent hours are correlated but **not** deterministic; real onset/clear transitions occur within the window. |
| **What is actually learned** | Mostly **persistence** ("an alert is currently ongoing"), not forecasting. Trivially high accuracy that masks ~zero genuine skill. | Genuine short-horizon **forecasting** signal (will a *new or continuing* alert cover the next hour). |
| **Temporal-leakage risk** | **Maximal.** With this autocorrelation, any imperfect split leaks; even clean splits are dominated by the "currently-on" signal — exactly the trap left open in Pavlyshenko. | **Reduced.** Coarser bins weaken the trivial carry-over; still requires time-ordered CV, but the easy signal no longer dominates. |
| **Computational feasibility (multi-year data, 2–3 day build)** | ~25 regions × millions of minutes ≈ **tens of millions of rows** — heavy to engineer, cross-validate, and iterate on in Python within the timeline. | ~25 regions × tens of thousands of hours ≈ **~10⁵–10⁶ rows** — comfortable in pandas/scikit-learn; fast iteration. |
| **Practical actionability** | Predicting 12:02 given 12:01 has near-zero value — you are already inside the alert. | "Alert likely in oblast X within the next hour" provides real **lead time** to shelter/prepare. |
| **Label noise** | Sensitive to very short alerts and false starts. | Aggregation smooths sub-minute jitter into a stable hourly label. |

**Verdict — Hourly.** Minute resolution mostly measures alert *persistence* and maximizes both
leakage and compute cost for no practical gain; Pavlyshenko's strong-but-suspect minute results are a
warning, not a target. Hourly aggregation tames the autocorrelation to a level where real skill is
learnable, keeps the multi-year panel computationally tractable within a 2–3 day build, and is the
operationally **actionable** resolution.

### B. Target Variable — Duration vs Binary Occurrence vs Count

- **Duration forecasting (how long an alert lasts once it starts).** The dominant drivers of duration
  — weapon type (drone vs cruise vs ballistic), number of attack waves, target value, all-clear
  policy — are **not in the alert logs**. This is **irreducible unobserved variance**: no feature we
  can build explains it, so regression error is floored high. The empirical red flag is decisive —
  **Pavlyshenko stated duration as the goal but abandoned it for a binary target**, and Hrytsyna
  charted duration histograms but never modeled them. *Weakest choice for a 2–3 day build.*
- **Binary occurrence (is an alert active in a window).** Strongest precedent in our set —
  **Pavlyshenko and Xue both succeeded** with occurrence-style classification. The governing
  condition (class imbalance) is **known and routinely manageable** (class weights / downsampling),
  and evaluation is clean and imbalance-aware (PR-AUC, Brier, log-loss). Best feasibility for a 2–3 day
  Python build and directly actionable. *Strongest choice.*
- **Count / frequency (how many alerts per hour/day).** Feasible, and it connects to the ViEWS/Teagan
  count lessons — but it is awkward at both resolutions. At **hourly** resolution counts are almost
  always 0 or 1, so the target **collapses into the binary problem**. At **daily** resolution it
  loses intra-day actionability, shrinks the sample per oblast, and inherits **zero-inflation /
  over-dispersion** that demands special models (negative-binomial/hurdle) — extra machinery with
  little payoff within the timeline. It is also definitionally noisy (one long alert vs several split alerts).
  *Feasible but second-best.*

**Verdict — Binary occurrence.** It dodges duration's unobserved-variance wall, avoids count's
collapse/actionability problems, has the clearest paper precedent, and fits the timeline.

### C. Definitive Engineering Judgment

**Hourly frequency + Binary occurrence per oblast** is the best combination for our constraints.

- **Exact target.** For each `(oblast, hour h)`, define `y = 1` if an air alert is active at any point
  during hour `h`, else `0`. Predict `y` for the **next hour `h+1`** using only information available
  up to the end of hour `h`.
- **Why this wins.** It tames the minute-level autocorrelation/leakage trap (A), sidesteps duration's
  irreducible unobserved variance and count's hourly-collapse (B), keeps the multi-year panel
  computationally tractable within a 2–3 day Python project, has the strongest precedent (Pavlyshenko, Xue), and is operationally
  actionable.
- **Mandatory honesty caveat.** Hourly binary occurrence still carries real autocorrelation (if an
  alert is on this hour it is likely on next hour). Therefore raw accuracy — even ROC-AUC — will look
  deceptively high. **Genuine skill must be reported as improvement over a persistence and a
  seasonal-naive baseline**, evaluated under strict time-ordered validation. A natural stretch
  refinement is **onset** prediction (a *new* alert starting in `h+1` given none active in `h`), which
  strips out the persistence signal and measures the hard, valuable part — kept as a secondary target
  so the primary remains feasible.

### D. Forecast Horizon & the Future-Exogenous Paradox

**The horizon decision.** We commit to a **short operational lead-time band: `k = 1…6` hours ahead**
(hourly), with `k = 1` as the primary horizon. Beyond ~6 h an adversarial, intentional DGP collapses
toward the climatological base rate (skill → 0), so longer leads buy little but cost calibration and
artifact overhead. 1–6 h is the region where lead time is both *actionable* (time to shelter) and
*learnable*.

**The paradox (well posed by the owner).** Our most valuable predictors — an oblast's own recent
alert state and its **neighbors' recent alert state** (spatial diffusion) — are *co-evolving* series.
To predict horizon `k ≥ 2`, their values at `t+1 … t+k-1` are themselves unknown future quantities.
Naively, it looks like we must *forecast the exogenous inputs before we can forecast the alert*.

**Two canonical multi-step strategies** (the standard Recursive/Direct/DirRec family from the
time-series forecasting literature):

| | **Recursive (iterated)** | **Direct (per-horizon)** |
|---|---|---|
| **Construction** | One `h+1` model, applied repeatedly, feeding its own prediction back in as the next step's input. | A separate model `f_k` for each horizon `k`, each mapping **features known at origin `t`** → `y_{t+k}`. |
| **Future inputs?** | **Required** — must generate the future endogenous/neighbor state, i.e. *forecast your own inputs*. For a coupled system this means a joint recursion over all ~27 oblasts at once. | **None** — the horizon lives in the *target*, not the features; every predictor is anchored at `t`. The paradox dissolves. |
| **Binary/probabilistic fit** | Poor: feed back probabilities → train/serve mismatch (trained on true 0/1 lags); or sample/threshold → lost calibration. | Clean: each `f_k` is an ordinary calibrated classifier. |
| **Error behaviour** | Compounding — small errors snowball on a bursty series. | No accumulation; each horizon trained directly on ground truth. |
| **Leakage safety / cost** | Subtle; fragile 27-oblast joint recursion. | Leak-safe by construction; 6 independent, parallel sklearn fits. |

**Verdict — Direct.** For a **binary, spatially-coupled, adversarial** target on a **2–3 day** budget,
Direct multi-horizon forecasting is decisively the right strategy.

**Literal answer to the owner's question:** *No — we do **not** build models to predict the exogenous
data first.* That requirement is an artifact of the **Recursive** strategy alone. Under **Direct**,
every feature is computed at the forecast origin `t`, the horizon is encoded in which target we
predict, and no future input value is ever needed.

**Feature-availability taxonomy (the precise architectural rule).** Classify every feature by whether
its value at the *target* hour `t+k` is knowable at origin `t`:
1. **Known-future deterministic** — calendar/Fourier time terms (hour, day-of-week, month, holiday).
   Known for *all* future hours → may be evaluated at the target hour `t+k`.
2. **Lagged endogenous & spatial** — own/neighbor alert history, rolling/decay summaries. Unknown in
   future → under Direct we use only their values **≤ t**. No problem.
3. **Truly-exogenous, unknown-future** — weather, military operations. Either **drop** them or use the
   **last-known value at `t`**. Only a genuine *third-party* forecast (e.g. weather NWP) would ever
   justify "predict exogenous first," and even then we'd consume someone else's forecast, not build
   one. Largely moot here, since these drivers are unobserved (§3.6).

**Honesty across horizons.** Skill decays with `k`. We therefore report **skill-vs-baseline per
horizon**, and add a **climatology / seasonal-mean** baseline alongside persistence — because
persistence weakens as `k` grows and climatology becomes the harder bar at longer leads. This mirrors
ViEWS's per-horizon predictive distributions and keeps the per-horizon honesty caveat of §C intact.

---

## Closing — Recommended Starting Approach for Our Project

Operationalizing the adopt-list against our anchored task — **hourly, next-hour binary alert
occurrence per oblast** (judgment derived above):

1. **Problem setup.** Resample the event-level alert logs into an **hourly** per-oblast panel and
   predict `alert_active(oblast, t+k)` for each horizon **`k ∈ {1…6}` hours** using the **Direct**
   strategy — one calibrated model per horizon, **all features anchored at origin `t`** (no future
   inputs; see §D). The label = 1 if an alert is active at any point in target hour `t+k`. (Hourly +
   binary occurrence + 1–6 h Direct band is the committed choice.) Keep **onset** — a new alert
   starting at the target hour given none active at `t` — as a secondary, harder target.
2. **Features.** Lagged + rolling summaries of the oblast's own recent alert state; calendar features
   (hour/day-of-week/month); **neighbor-oblast recent alert state and spatial-diffusion counts**
   (the highest-value signal per Pavlyshenko & Xue).
3. **Imbalance.** Class weights and/or downsampling of the majority (no-alert) class — never optimize
   raw accuracy.
4. **Validation (non-negotiable).** **Time-ordered / blocked CV** with an embargo gap between train
   and test to kill the leakage that Pavlyshenko/Xue left open. No shuffled splits.
5. **Diagnostics for understanding (not as model prerequisites).** Run ADF/ACF/PACF on the alert-rate
   series to characterize autocorrelation/seasonality and motivate lag choices — even though RF needs
   no stationarity.
6. **Output & metrics.** Emit **calibrated probabilities**; evaluate with **PR-AUC, Brier score,
   log-loss, and recall-at-fixed-precision** (the binary analogues of ViEWS's CRPS). Add reliability
   (calibration) curves.
7. **Baselines & skill (per horizon).** Persistence ("currently-alert stays alert"), seasonal-naive
   (same hour/day-of-week history), and a **climatology / seasonal-mean** baseline (the harder bar at
   longer leads); treat the **Pavlyshenko RF as a reproduction baseline**. Because hourly occurrence
   is autocorrelated, report a **skill score relative to these baselines** (improvement in
   Brier/log-loss/PR-AUC) **at each horizon `k`** rather than absolute accuracy — and expect skill to
   decay toward the base rate as `k` → 6 h.
8. **Expectation setting.** Hold Hrytsyna's caution in view: target *useful, calibrated* probabilities
   over a non-stationary, adversarial DGP rather than illusory high accuracy; monitor for drift.




