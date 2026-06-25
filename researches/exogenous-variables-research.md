# Exogenous Variables Research — Air Raid Alerts (Ukraine)

**Purpose.** Stage 1 (Data Ingestion) requires a *finalized feature matrix before any ETL code is
written*. This document (1) researches external sources on exogenous variables that correlate with
Ukrainian air alerts, (2) merges them with the spatial/exogenous baselines already validated in
[`research_related_works.md`](./research_related_works.md), and (3) concludes with a definitive
**Adopt vs Avoid matrix**, judged against our locked architectural constraints:

- **Direct forecasting** — every feature must be available at the forecast origin `t` (no future
  values; see `../plans/01-initial-research-analysis.md §D`).
- **Pure-Python automated ingestion** — a feature is only viable if it can be pulled/derived by an
  automated Python pipeline.
- **1–6 h horizon band** — fast signals drive short leads; slow signals stabilize the longer end.

**Integrity note.** Every Section-1 source is a real URL verified this session; recent strike
statistics are quoted *as reported by the source, with their dates* — they are context for variable
selection, not our own measurements. Where a reference is a data resource rather than a correlation
study, it is labelled as such.

---

## 1. External Research & Source Verification

### S1 — MiG-31K takeoff → nationwide ballistic alert (OSINT / news)
- **Source:** *"Nationwide air raid alert declared in Ukraine due to ballistic missile threat and
  MiG-31K takeoff"* — Ukrinform (corroborated by RBC-Ukraine, Kyiv Post, Mezha, UNN).
- **URL:** https://www.ukrinform.net/rubric-ato/4128313-nationwide-air-raid-alert-declared-in-ukraine-due-to-ballistic-missile-threat-and-mig31k-takeoff.html
- **Discovery:** Detection of a **MiG-31K takeoff** (the carrier of the Kh-47M2 *Kinzhal* aero-ballistic
  missile) reliably triggers a **nationwide** air-raid alert. Because ballistic flight time is short,
  the Air Force issues a country-wide warning on *takeoff detection* alone. This is a
  **near-deterministic exogenous precursor** of a nationwide alert — but with very short lead time
  (minutes), so its predictive value is concentrated at the `k=1 h` horizon.

### S2 — ISIS, *Monthly Analysis of Russian Shahed-136 Deployment Against Ukraine*
- **URL:** https://isis-online.org/isis-reports/monthly-analysis-of-russian-shahed-136-deployment-against-ukraine
- **Discovery (verified):** (a) **Launch sites** are a small, stable set inside Russia — Bryansk,
  Kursk, Orel, Shatalovo, Millerovo, Primorsko-Akhtarsk — giving predictable ingress corridors.
  (b) **Time-of-day shifted**: predominantly nocturnal in early 2025 → day *and* night by Jan 2026 →
  "continuous 24-hour strike cycles" by March 2026. (c) **Volume/seasonality**: peaks reported up to
  ~8,161 UAVs in a month (~263/day) vs a ~203/day record in July 2025. (d) **Geographic targeting**
  concentrates on frontline oblasts (Sumy, Chernihiv, Kharkiv, Dnipro, Zaporizhzhia, Odesa) and on
  **energy infrastructure** (330–750 kV stations, CHP plants). (e) **Weather matters**: Jan 2026 saw
  "extremely difficult weather conditions that affected the number of launches." (f) **Data window**:
  Ukrainian Air Force reporting covers ≈18:00 (prev day) → 08:00–09:00.

### S3 — CSIS, *Drone Saturation: Russia's Shahed Campaign*
- **URL:** https://www.csis.org/analysis/drone-saturation-russias-shahed-campaign
- **Discovery (verified):** Strong **temporal cadence** — over a seven-month window there was *"not a
  single uninterrupted three-day period without a Shahed drone launch,"* and **~75% of launches
  occurred on consecutive days**. **Launch corridors map to regional axes** (Primorsko-Akhtarsk ≈312
  launches → Odesa; Kursk ≈248 → Donbas/Kharkiv; Chauda/Crimea ≈160 → circumventing western air
  defenses). Escalation from ~130 launches/week (pre-Sept 2024) to ~1,000/week (Mar 2025). Data from
  the Ukrainian Air Force's official social media.

### S4 — CSIS, *Russian Firepower Strike Tracker* (data resource)
- **URL:** https://www.csis.org/programs/futures-lab/projects/russian-firepower-strike-tracker-analyzing-missile-attacks-ukraine
- **Discovery / value:** An interactive dashboard of **daily aggregated** launches and intercepts
  **by weapon type** (Shahed-136/131, cruise, ballistic…), drawn from official Ukrainian Air Force
  reports. Confirms that a structured, automatable **weapon-mix + daily cadence** signal exists.

### S5 — OpFor Journal, *Situation Report: Russia's 2025 Shahed Drone Offensive*
- **URL:** https://www.opforjournal.com/p/situation-report-russias-2025-shahed
- **Discovery (verified):** Attacks became **"almost daily"** by mid-2025 (only ~two days without air
  attack since January). **Multi-hour, multi-wave assaults** — e.g. 3–4 Jul: 539 drones + 11 missiles;
  8–9 Jul: 728 drones + 13 missiles; June 2025 total 5,438 long-range drones. **Night preference**
  produces "narrow intercept windows," and **drone-then-missile sequencing** means an active alert in
  one hour strongly predicts continuation — supporting the autoregressive/persistence features.

### S6 — ABC News, *Russia hits Ukraine energy targets with hundreds of drones, missiles*
- **URL:** https://abcnews.com/International/russia-hits-ukraine-energy-targets-hundreds-drones-missiles/story?id=129805309
- **Discovery (verified):** A single barrage of **71 missiles + 450 drones** focused on **critical
  energy infrastructure**; DTEK described it as the *"ninth massive attack on thermal power stations
  since October 2025."* **Winter timing is deliberate** — officials describe stockpiling to *"wait for
  the coldest days of the year"* (temperatures to −14 °F). Establishes a **seasonal (heating-season)
  campaign signal**.

### S7 — Gridded monthly temperature & precipitation for Ukraine, 1946–2020 (data resource)
- **URL:** https://www.sciencedirect.com/science/article/pii/S2352340922007600
- **Discovery / value:** A peer-reviewed **gridded historical weather dataset** (min/max/mean
  temperature + precipitation). Not a correlation study — included as the **feasibility anchor** proving
  the macro-weather / season ADOPT variable is programmatically obtainable as a historical series.

---

## 2. Integration of Existing Baselines (from `research_related_works.md`)

Exogenous and spatial-diffusion features **already validated** in our foundational review, extracted
and merged with the sources above:

| Baseline source | Validated exogenous / spatial feature |
|---|---|
| **Pavlyshenko (2024)** | **Neighbor/adjacent-oblast alert state** (spatial diffusion — the *strongest* signal: "alert status is highly dependent on adjacent regions"); **calendar** (hour, day-of-week, month); **`ndays`** = days since dataset start (captures regime/trend drift over time). |
| **Xue (2025)** | **Spatial-diffusion** features (neighbor activity over past week/month); **~31-day autoregressive** own-history. *Static socioeconomic covariates (GDP, population density, ethnolinguistic) are noted **not transferable** to our oblast-timing task.* |
| **Hegre / ViEWS (2024)** | News-topic (LDA) / text features and conflict-history lags. *Text/sentiment noted but flagged hard-to-automate cleanly (see AVOID).* |
| **Teagan (2025)** | **Weekday metadata**; geographic stratification. |
| **`01 §3.2 / §3.5`** | **Structural-break / regime indicators** (war is non-stationary; reporting/protocol coverage changes over time). |

**Merge result.** The literature and the new OSINT/think-tank sources **converge** on the same feature
families: (i) **spatial diffusion from neighboring oblasts**, (ii) **own-history autocorrelation /
persistence**, (iii) **calendar & diurnal seasonality** (night bias), (iv) **campaign-cadence &
regime** signals (days-since-attack, war phase), and (v) **season/weather** (heating-season energy
campaign). New relative to the baselines: the **MiG-31K ballistic precursor**, explicit **launch-site /
weapon-mix** structure, and the **winter energy-campaign seasonality**.

---

## 3. The "Adopt vs Avoid" Matrix

Judged against: available at `t`? · pure-Python automatable? · value across the 1–6 h band? ·
leakage-safe?

### ✅ ADOPT (Fast-Moving) — exist at `t`, programmatically accessible, drive short-horizon (1–6 h) skill
| Variable | Why adopt (availability `t` · ingestion · horizon) |
|---|---|
| **Neighbor-oblast live alert status / spatial-diffusion** | The top validated signal (Pavlyshenko, Xue). Read directly from the alerts API at `t`; pure-Python; dominant at 1–3 h via diffusion of attack waves across adjacent oblasts. |
| **Own-oblast autoregressive lags + rolling alert state (≤ t)** | Pure function of the panel up to `t`; the persistence/cadence backbone (S3 "75% consecutive days", S5 multi-hour waves). Leak-safe by construction. |
| **Nationwide / mass-attack-active flag** | Derived at `t` from the live alert stream (count of oblasts currently active). Cheap, Python-native; strong 1–2 h predictor during saturation waves. |
| **MiG-31K / strategic-aviation takeoff flag** | Near-deterministic ballistic precursor (S1). Available at `t` **via a static one-time OSINT insert** (`02` Use case A; frozen dataset, no live scraper) — must be **lagged leak-safe**. Highest value at `k=1 h`; short lead is its only limit. |
| **Calendar / time-of-day / day-of-week** | Deterministic and **known for all future `t+k`** (taxonomy class 1, `01 §D`). Trivial Python; encodes the strong night-attack diurnal bias (S2, S5). |

### ✅ ADOPT (Slow-Moving) — low-frequency, last-known-at-`t`; stabilize the longer (≤ 6 h) horizons
| Variable | Why adopt |
|---|---|
| **War-phase / campaign-regime indicator** (e.g. "winter energy-targeting active") | Slow, available at `t`; encodes **non-stationarity / structural breaks** (`01 §3.2`, S6). Anchors longer-horizon base rates when fast signals are quiet. |
| **Days since last mass attack + rolling 7/30-day attack intensity (per oblast)** | Computable from history at `t`; captures the documented **cadence** (S3 no-3-day-gap; S5 almost-daily). Strong regime/pressure prior. |
| **Season / macro-weather (month, heating-season & temperature proxy)** | Seasonality is real (S2 weather-limited launches; S6 cold-season energy campaign). Historical weather is automatable (S7); month/season is free and known-future. |
| **`ndays` / long-term trend index** | Pavlyshenko's validated regime-drift feature; deterministic, available at every `t`. |

### ❌ AVOID — correlate in theory but rejected (latency · no automation · non-stationarity · leakage)
| Variable | Why avoid |
|---|---|
| **Air-defense interception outcomes; impact / "explosion" reports** | Known only **at or after** the event → **data leakage** when predicting the same window. (Usable only with a strict backward lag, never contemporaneously.) |
| **Future weapon type / specific strike target** | Unobserved at `t`; drives *duration*, not *occurrence* (`01 §B`). Irreducible. |
| **News sentiment / LDA topics over unstructured news (ViEWS-style)** | High latency, **non-deterministic LLM/NLP extraction**, and leakage risk (coverage may post-date the alert). Not pure-Python-clean for a 1–6 h loop. Defer. |
| **Diplomacy / peace-talk "stockpile-and-wait" timing** (S6) | Real macro driver but **unautomatable**, low-frequency, and highly non-stationary — unusable as a live feature. |
| **Static socioeconomic covariates (Xue: GDP, population, ethnolinguistic)** | Constant per oblast → **no temporal signal** for an hourly timing task; pure noise/identifier. |

---

## 4. Historical Alert Target Backfill (2022 → present)

The live `alerts.in.ua` token serves **only the last ~2 months** (and `ukrainealarm` is pending), so the
2022→present alert-target history must be backfilled from a trusted open-source dataset and then unioned
with the API's trailing window into one continuous `raw_alerts` series.

**Primary — Vadimkin, *Ukrainian Air Raid Sirens Dataset*.**
- **URL:** https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset (`datasets/README.md`).
- **Files & structure:**
  - `official_data_{en,uk}.csv` — coverage from **2022-03-15**; oblast-level until **Dec 2025**, raion-level
    thereafter.
  - `volunteer_data_{en,uk}.csv` — coverage from **2022-02-25** (day 2 of the full-scale war); **oblast-level
    only**; sourced from the **eTryvoga** volunteer channel; carries the most history.
  - **Columns:** region/oblast identifier + name, `started_at` (**UTC**), `finished_at` (**UTC**, nullable),
    `naive` (bool — when `True` and no end message exists, `finished_at = started_at + 30 min`).
  - **Timezone:** UTC. **Update cadence:** daily. **Exclusions:** the two permanent sirens (Luhansk since
    2022-04-04, Crimea since 2022-12-10) are removed.
- **Ingestion notes:** resolve `region → canonical oblast_id`; **roll raion → oblast** for post-Dec-2025
  rows to preserve the oblast grain (our locked target); set `source = vadimkin_official | vadimkin_volunteer`
  and carry `is_naive`. Use `volunteer_data` for the earliest **2022-02-25 → 03-15** window and for
  oblast-grain consistency; overlaps with `official_data` and the live API reconcile via the idempotent
  UPSERT key `(oblast_id, started_at, alert_type, source)`.
- **Fallbacks:** `github.com/Tyrrrz/RaidTrend` (pulls historic data from the `@air_alert_ua` channel);
  Kaggle mirrors (e.g. `dimakyn`, `cashncarry`).

---

## 5. The Weather Variable Paradox — target-oblast vs launch-site

*Does weather correlate with alerts because of conditions over the **target oblast** (Shahed flight path /
interception over Ukraine), or because of the **launch site** (storms grounding Tu-95MS at Olenya / over the
Caspian)?* Answer: **both mechanisms are real, they are geographically distinct, and they have *opposite
signs*** — so they must be modeled as **separate features**, never one blended "weather" column.

**Mechanism A — Launch-site / launch-corridor weather (upstream gate).**
Tu-95MS strategic bombers fly from **Olenya (Kola Peninsula)** and **Engels-2 (Saratov, ~850 km from the
border)** to launch lines over the **northern Caspian / Saratov**, releasing Kh-101 from standoff range;
Shahed sites are **Primorsko-Akhtarsk, Yeysk, Kursk, Bryansk, Oryol, Chauda (Crimea)**. Severe weather at
these sites **reduces/delays launches** (ISIS: "extremely difficult weather conditions affected the number of
launches", Jan 2026). **Sign: bad launch-site weather → fewer launches → fewer alerts.** For our task this is
**weak and largely redundant**: the sites are dispersed and far (Kola ≈ 2000 km), so there is no single
"launch weather"; it is a **national** signal, not per-oblast; and it is **already captured downstream by the
directly-observed `tu_95_takeoff` / `mig_31_airborne` OSINT flags** — once a takeoff is observed, the
launch-site weather gate has already resolved. It therefore only adds marginal *leading* value before takeoff.

**Mechanism B — Target-oblast / flight-path weather over Ukraine (downstream modulator).**
Over Ukraine, weather affects (i) Shahed routing/navigation (wind, icing) and (ii) — decisively —
**interception and visibility**: drones are killable by guns/air defense *"only in daylight and clear
weather"*, so night / low cloud / fog **narrows the intercept window**. **Sign: bad target-oblast weather →
worse interception → more / longer alerts — the *opposite* sign to Mechanism A.** This signal is **per-oblast**,
**contemporaneous and forecastable** (Open-Meteo at the oblast centroid yields the value at `t` *and* the
`t+1..6 h` forecast — a known-future, leak-safe input), and aligned to our oblast-level target.

**Decision — which geographic weather data we adopt:**
- **ADOPT (primary): target-oblast weather** at each oblast centroid via **Open-Meteo** — wind speed/gusts,
  temperature (icing proxy + heating-season), precipitation, cloud cover / visibility. Per-oblast, leak-safe,
  automatable, and tied to the **interception-window mechanism** that actually governs whether *this* oblast's
  alert is declared/sustained over the next 1–6 h.
- **Secondary / optional: launch-site weather** as a small **national** feature set (fixed coordinates for
  Engels-2/Saratov, the northern-Caspian launch box, and the main Krasnodar Shahed sites). **Low priority** —
  the takeoff flags already encode its outcome more directly. If used, keep it a **separate national feature**
  so its opposite sign is not blended with target-oblast weather.
- **Reject blending:** never collapse A and B into one "weather" column — opposite signs would cancel and
  destroy the signal.

This sharpens the "Season / macro-weather" ADOPT (Slow-Moving) row in §3: the *primary* weather signal is
actually **fast-moving, per-oblast target weather** (interception-driven), with season and launch-site weather
as slower / national context.

---

## Final Feature-Matrix Summary

**Ingest in Stage 1:** neighbor-oblast alert state + own autoregressive history (from the alerts API);
calendar/diurnal features; nationwide mass-attack flag; days-since-last-attack & rolling attack
intensity; war-phase/regime flag; season/macro-weather; `ndays`. **Static OSINT (one-time, frozen):**
MiG-31K takeoff flag (leak-safe lag) — inserted once, never scraped live. **Explicitly excluded:** interception/impact outcomes, future weapon
type, live news sentiment, diplomacy timing, static socioeconomics — for leakage, latency,
automation, or non-stationarity reasons. Every adopted feature is available at `t`, pure-Python
ingestible, and leak-safe — satisfying the Direct-forecasting and ingestion constraints before any
ETL code is written.

*Cross-references:* horizon/leakage rationale → `../plans/01-initial-research-analysis.md §D`; ingestion
schema & the static OSINT insert → `../plans/02-general-workflow-architecture.md` (Stage 1, Use case A).
