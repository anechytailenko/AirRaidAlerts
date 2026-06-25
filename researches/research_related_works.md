# Research: Related Works — Time-Series Forecasting of Air Raid Alerts (and Conflict-Zone Analogues)

_Aggregated from five individual source-extraction files. The sections below are concatenated verbatim from those files (no summarization or alteration). Order: direct air-alert sources first, then analogous conflict-zone forecasting works._

---

# Pavlyshenko & Pavlyshenko (2024) — Predictive Analytics of Air Alerts in the Russian-Ukrainian War

**Source:** D. Pavlyshenko, B. Pavlyshenko (2024). *Predictive Analytics of Air Alerts in the Russian-Ukrainian War.* arXiv:2411.14625. https://arxiv.org/html/2411.14625v1
**Relevance:** Direct — air raid alerts in Ukraine.

**Goal of the work:** Conduct exploratory data analysis and build a predictive model to anticipate air alerts (stated aim: "forecast the duration of air alerts"), in order to understand the structure and patterns of alerts since the start of the full-scale invasion and predict when an alert is about to occur.

**Target to forecast:** A binary indicator of alert status in the near-future window. The target = 1 if an air alert will be active within the specified horizon (5 or 15 minutes ahead) and = 0 otherwise (no alert, or an ongoing alert about to end). Note the gap between the stated aim (alert *duration*) and the operationalized target (binary *occurrence/continuation*) — the work is ultimately framed as supervised classification, not duration regression.

**Data origin & description:** Historical air-alert records for Ukrainian regions (oblasts), drawn from publicly available historical alert logs, covering 25 March 2022 – 6 November 2024. Analysis focuses on a subset of oblasts (Lvivska, Vinnytska, Kyivska, Kharkivska), chosen to contrast regions with different threat exposure.

**Data frequency & Horizon:** 1-minute granularity time series. Two short forecast horizons evaluated: 5 minutes and 15 minutes ahead.

**Exogenous variables:** Cumulative alert durations of neighboring/adjacent oblasts (geospatial dependence); calendar/temporal features — hour, day of week, month; `ndays` (number of days elapsed since the dataset start). The authors emphasize that alert status in a region is highly dependent on the state of adjacent regions.

**Plots used:** Heatmaps of alert durations, correlation heatmaps, boxplots of durations by region, time-series plots of alerts, and daily-median charts.

**Statistics used:** None reported. No stationarity test (ADF/Dickey-Fuller, KPSS), no Ljung-Box, no ACF/PACF autocorrelation diagnostics, no normality/heteroscedasticity tests.

**Model used & Condition verification:** Random Forest classifier (scikit-learn, ~500 trees). *Condition analysis:* By casting the problem as supervised binary classification rather than a classical stochastic-process model, the authors sidestep the strict preconditions of ARIMA-family methods — Random Forest is non-parametric and distribution-free, so it does **not** require stationarity, normality, or homoscedasticity, and on that count the model/data match is acceptable. **However**, the paper presents itself as time-series forecasting yet performs **no** temporal-dependence diagnostics whatsoever: autocorrelation is never quantified, and there is no stated guard against look-ahead leakage when constructing 1-minute-ahead features/splits on a highly autocorrelated minute-level series. So the relevant unverified condition here is not distributional but *temporal validity* (independence of train/test under heavy serial correlation), which is left unaddressed.

**Feature engineering:** Cumulative alert-duration features per region; lagged features from neighboring oblasts; decomposition of the timestamp into calendar components (hour/day-of-week/month) and the `ndays` trend feature.

**Prediction output:** Probabilistic class scores via `predict_proba` (probability that an alert will be active in the window), evaluated with ROC curves and accuracy. Output is a class probability, not a calibrated prediction interval.


---

# Hrytsyna (2022) — What You Don't Know About Air Alerts in Ukraine

**Source:** N. Hrytsyna (2022). *What you don't know about air alerts in Ukraine.* Medium. https://medium.com/@nataliia.hrytsyna/what-you-dont-know-about-air-alerts-in-ukraine-91e2a68fbe78
**Relevance:** Direct — air raid alerts in Ukraine. Included as a descriptive-EDA counterpoint: a practitioner who examined the data and deliberately chose **not** to forecast.

**Goal of the work:** Analyze and communicate air-alert patterns in Ukraine during the early 2022 invasion using exploratory data analysis and visualization (frequency, duration, timing, cumulative shelter time by region).

**Target to forecast:** None. No forecasting target is defined. The variable of interest is air-alert events (frequency / duration / timing) by region, treated descriptively. The author explicitly considered building an ML model to predict the next alerts and decided against it.

**Data origin & description:** A Kaggle dataset sourced from the official Ukrainian air-alarm Telegram channel (`air_alert_ua`), comprising individual alert records with timestamps and region labels.

**Data frequency & Horizon:** Event-level records (timestamp + region) over 15 March – 5 May 2022 (~1.5 months). No forecast horizon — no forecasting is performed.

**Exogenous variables:** None documented.

**Plots used:** Regional ranking chart of alerts by city (Kharkiv, Kyiv, Dnipro lead); time-series distribution of alerts in Kyiv across March–April; histogram of alert duration (minutes) in Kharkiv region.

**Statistics used:** None.

**Model used & Condition verification:** No model is built — the work is purely descriptive EDA. *Condition analysis:* Not applicable, as no model is fitted, so there are no stationarity/homoscedasticity preconditions to verify. This absence is itself the finding: the author reasons that air-alert targeting is driven by adversarial, intentional decisions ("That could work in a normal world") and judged the data-generating process too non-stationary/adversarial to forecast reliably — a useful caution for our own modeling assumptions.

**Feature engineering:** None documented.

**Prediction output:** None — no forecast produced. Output is descriptive insight (e.g., cumulative shelter time of ~4–5 days in Kyiv vs. 12+ days in Kharkiv over the period).


---

# Teagan (2025) — Forecasting Russian Equipment Losses Using Time Series and Deep Learning Models

**Source:** J. Teagan (2025). *Forecasting Russian Equipment Losses Using Time Series and Deep Learning Models.* arXiv:2509.07813. https://arxiv.org/html/2509.07813v1
**Relevance:** Conflict-zone analogue — daily/monthly war attrition counts, Ukraine theatre.

**Goal of the work:** Apply and compare a range of forecasting techniques (classical and deep learning) to model and predict Russian equipment losses during the ongoing war in Ukraine.

**Target to forecast:** Confirmed Russian equipment losses (tanks, infantry fighting vehicles, support vehicles), at daily and monthly aggregation.

**Data origin & description:** WarSpotting — a visually verified open-source intelligence (OSINT) repository in which each loss is backed by photographic or video evidence vetted by the platform's analysts. Represents confirmed (not estimated) destroyed/damaged/abandoned/captured equipment.

**Data frequency & Horizon:** Daily and monthly aggregations. Training window February 2022 – early July 2025; forecasts extended through December 2025 / January 2026. (June–July 2025 excluded due to incomplete reporting.)

**Exogenous variables:** Weekday metadata fed into the LSTM; geographic stratification (Raion/Oblast). Not systematically integrated across all models — most models are essentially univariate on the loss series.

**Plots used:** Time-series plots of tank/equipment losses across 2022–2025; Prophet seasonal-decomposition plots; daily-vs-monthly resolution comparison charts. No histograms or correlation matrices reported.

**Statistics used:** Not reported. No ADF/Dickey-Fuller, KPSS, Ljung-Box, or ACF/PACF diagnostics are presented.

**Model used & Condition verification:** ARIMA(1,1,1) (on a log-transformed, first-differenced series), Prophet, LSTM, TCN, and XGBoost. *Condition analysis:* ARIMA's core precondition is **stationarity** of the modeled series. The authors address this *mechanically* — the log transform stabilizes variance and the `d=1` differencing term removes a unit-root trend — but they never **verify** it: no ADF/KPSS test confirms the differenced series is actually stationary, and no Ljung-Box test confirms the residuals are white noise (the diagnostic that validates an ARIMA fit). Homoscedasticity is assumed via the log transform but not tested. So the stationarity condition is *handled by construction yet statistically unconfirmed* — a common but important gap. The deep-learning models (LSTM/TCN/XGBoost) are non-parametric and impose no stationarity requirement, so for them the missing tests are less critical.

**Feature engineering:** Log transformation and differencing (ARIMA); lagged features and moving averages (XGBoost); weekday indicator features (LSTM).

**Prediction output:** Point forecasts for all models. Prophet additionally reports 95% uncertainty intervals; the other models output deterministic point predictions only.


---

# Hegre et al. (2024) — The 2023/24 ViEWS Prediction Challenge: Predicting Fatalities in Armed Conflict, with Uncertainty

**Source:** H. Hegre et al. (2024). *The 2023/24 VIEWS Prediction Challenge: Predicting the Number of Fatalities in Armed Conflict, with Uncertainty.* arXiv:2407.11045. https://arxiv.org/html/2407.11045v1
**Relevance:** Conflict-zone analogue — the reference benchmark for *probabilistic* conflict forecasting; strongest example of prediction-interval / full-distribution output.

**Goal of the work:** Benchmark and compare methods for predicting the number of fatalities in armed conflict (as coded by UCDP) **with explicit uncertainty estimates**, across 13 participating teams / 24 contributions.

**Target to forecast:** UCDP's coded number of fatalities in state-based armed conflict, expressed as (non-logged) count data.

**Data origin & description:** Uppsala Conflict Data Program (UCDP) — 'best' fatality estimates for the test periods 2018–2023 and UCDP-Candidate data for 2024. Represents state-based armed-conflict deaths aggregated to standardized geographic units.

**Data frequency & Horizon:** Monthly aggregation at two spatial levels — country-month (global) and PRIO-GRID-month (Africa & Middle East). Primary horizon is 12 months forward (July 2024–June 2025), plus retrospective test forecasts for 2018–2023.

**Exogenous variables:** Vary by team (the challenge is method-agnostic). Examples: 15 topics extracted from a large news corpus via Latent Dirichlet Allocation (ConflictForecast); conflict-history variables built from GED state-based events (Dorazio); assorted temporal features and covariates.

**Plots used:** Distribution plot of (logged) observed fatalities highlighting strong skew and zero-inflation (≈87% zeros at country-month, ≈99% at PRIO-GRID level); ensemble-prediction plots and fatality maps.

**Statistics used:** No classical hypothesis tests reported. The challenge deliberately centers on probabilistic *evaluation metrics* — CRPS (Continuous Ranked Probability Score), Ignorance/log score (IGN), and Mean Interval Score (MIS) — rather than stationarity/autocorrelation testing.

**Model used & Condition verification:** A diverse field — quantile regression, negative binomial models, temporal fusion transformers, tree ensembles, random forests, Markov models, transformers, GAMs, hurdle models, and shape-based methods. *Condition analysis:* As a multi-team benchmark, assumption checking is not reported uniformly. The decisive data property is **heavy zero-inflation and skew in count data**, and several teams correctly matched the model family to that property — negative-binomial and hurdle/zero-inflated models are precisely the right conditional distributions for over-dispersed, zero-heavy counts — which is a genuine instance of aligning model assumptions with data statistics. Stationarity/homoscedasticity are not the governing conditions here (these are count/distributional models, not linear-Gaussian time-series models), and are not tested.

**Feature engineering:** Varies by team: rolling averages plus temporal lags of fatalities (Muchlinski & Thornhill); Dynamic Time Warping for clustering/sequence identification (HCD, PaCE); automated ML-pipeline feature selection.

**Prediction output:** Full predictive distributions, submitted as samples (between 15 and 1,000 int32 draws per prediction). This is explicitly probabilistic — uncertainty is the deliverable, scored via CRPS, log score, and interval scores — the clearest contrast to point-forecast studies in this review.


---

# Xue et al. (2025) — Using Machine Learning to Forecast Conflict Events for Use in Forced Migration Models

**Source:** Xue et al. (2025). *Using machine learning to forecast conflict events for use in forced migration models.* Scientific Reports, s41598-025-11812-2. https://www.nature.com/articles/s41598-025-11812-2
**Relevance:** Conflict-zone analogue — peer-reviewed; daily, locality-level conflict-onset forecasting feeding a downstream simulation.

**Goal of the work:** Integrate machine-learning-based conflict forecasting with agent-based modeling to improve predictions of forced-migration patterns during conflicts.

**Target to forecast:** Daily conflict occurrence at locality level (binary: conflict / no-conflict), plus the time until first conflict onset for each locality.

**Data origin & description:** ACLED (Armed Conflict Location and Event Dataset) — conflict events within a 0.1° buffer of each location; PRIO-GRID v2.0 — geographic and socioeconomic covariates; UNHCR database — refugee-camp populations used for downstream validation.

**Data frequency & Horizon:** Daily predictions at locality level; forecast spans of 1–2+ years, evaluated across four African conflicts (Mali, Burundi, South Sudan, Central African Republic).

**Exogenous variables:** Terrain, altitude, GDP per capita, population density, governance quality, ethnolinguistic distributions; spatial-diffusion features (conflict occurrence in the past week/month in neighboring areas); a 31-day autoregressive conflict-history component.

**Plots used:** Recall-vs-accuracy comparison (Fig. 3); confusion matrices (Fig. 4); MSE log-ratio plots (Fig. 5); camp-population predictions over time (Fig. 6).

**Statistics used:** T-tests on whether log-ratio differences differ from zero (p = 0.003 and p = 0.02); ROC-AUC scoring; an Average Relative Difference (ARD) metric.

**Model used & Condition verification:** Random Forest classifier (primary), with XGBoost tested as an alternative. *Condition analysis:* The framing is classification, so Random Forest imposes no stationarity/normality precondition — and the authors correctly identified the **governing data condition for classification, severe class imbalance** (conflict days are rare), and addressed it by downsampling non-events (factor k≈20). That is a sound match of method to data property. Stationarity is **not** explicitly verified; given the 31-day autoregressive sequences over a daily panel, temporal autocorrelation and possible train/test leakage across time are not formally diagnosed, which is the main unaddressed condition.

**Feature engineering:** Downsampling of non-event (majority-class) days; aggregation of spatial-diffusion signals over weekly/monthly windows; encoding of 31-day binary autoregressive conflict sequences.

**Prediction output:** Point forecasts (daily binary predictions and predicted onset day). Ensemble runs (100 replicas) are used to capture aleatoric uncertainty, but the headline output is a point/binary prediction rather than a full predictive distribution.
