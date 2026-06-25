# 04 — Analytics & EDA: the unified, leak-safe analytical export

> **Status:** ✅ Built & verified (2026-06-25). This document is the bridge from Stage 1 (ingestion,
> `03`) to Stage 2/3 (EDA + ML, `02 §"Stage 2/3"`). It defines **how all Postgres data is compiled into
> one unified, leak-safe analytical artifact** for time-series / GNN / RL workflows.
> Pipeline: `src/airraid/export_dataset.py`. Output bundle: `data/exports/` (gitignored).

---

## 1. Objective & constraints
Compile every analytical record from the 7-table PostgreSQL database into a single flat dataset (plus
minimal companions) that ML/EDA tools consume directly — **without touching the database**.

- **Strictly read-only.** The DB session is opened `default_transaction_read_only = on`; only `SELECT`s
  run; **no** persistent or temp objects are created in Postgres. All alignment is **out-of-database**.
- **Autonomous technical judgment** on format + engine (below).
- **Leak-safe join grain** with a clean, runnable, idempotent script.

## 2. Source inventory & "all data used" coverage matrix
Every analytical table is represented; the only exclusion is the operational dead-letter, documented.

| Table | Rows | In export? | How |
|---|---|---|---|
| `hourly_panel` | 6,150,978 | ✅ | grain `(hour_ts, oblast_id, lead_hours)` + label `y_alert_active` (at `t+lead`). |
| `feature_matrix` | 1,025,163 | ✅ | weather@t, spatial@t (self/neighbor), calendar@t — reused as-is (no recompute). |
| `oblasts` | 27 | ✅ | static `oblast_name, centroid_lat/lon` joined on `oblast_id`; full table → `oblasts.parquet`. |
| `oblast_adjacency` | 106 | ✅ | (a) `neighbor_alert_count/frac` features; (b) `edges.parquet` GNN `edge_index`. |
| `raw_alerts` | 101,876 | ✅ | labels (via panel) + self/neighbor alert state (via feature_matrix). |
| `exogenous_features` · open_meteo | 4,113,504 | ✅ | weather columns (via feature_matrix). |
| `exogenous_features` · telegram (OSINT) | 1,021 | ✅ **NEW** | **as-of forward-filled** flag-states — see §5. |
| `ingest_errors` | 5 | ⬜ documented exclude | Operational dead-letter (malformed source rows); not analytical signal. Surfaced as an EDA data-quality figure instead. |

**Why the OSINT join is the crux.** `feature_matrix` was materialized *before* the OSINT scrape and its
weather CTE filters `source='open_meteo'` only (`src/airraid/build_features.py`). So the 1,021 real
Telegram flags live **only** in `exogenous_features`. A naive `panel ⋈ feature_matrix` would silently
drop them; the export adds them via a leak-safe ASOF merge (§5), making "all data used" literally true
(verified: **366,144** export rows carry an active OSINT state).

## 3. File-format judgment → **Parquet + zstd** (the autonomous call)
| Format | Verdict | Rationale |
|---|---|---|
| **Parquet (zstd)** | ✅ **Chosen** | Columnar; dtype-preserving; column/predicate pushdown; streaming/out-of-core; partitionable; first-class in pandas/polars/pyarrow/duckdb/torch-geometric. |
| CSV | ❌ main / ✅ tiny preview | ~1.5–2.5 GB, slow, lossy dtypes, no pushdown. Only a 10k-row `sample_preview.csv` is emitted for eyeballing. |
| Feather/Arrow IPC | ❌ | Weaker compression; archival/portability worse than Parquet. |
| HDF5 | ❌ | Heavier, fading ecosystem, concurrency pain. |
| DuckDB/SQLite file | ❌ as deliverable | Excellent as the **engine**, but a DB ≠ a portable flat analytical file. |
| npy/npz | ❌ | Loses schema + heterogeneous dtypes. |

**Measured result (not an estimate):** `long` 6,150,978 rows × 29 cols = **18.2 MB**; `wide` 1,025,163
rows = **6.2 MB**. zstd crushes the repeated as-of-`t` features and boolean/small-int columns (~80–130×
smaller than the CSV equivalent). **Memory/I-O:** the only 6M-row input is the 4-column panel; DuckDB
streams the join to Parquet — peak RSS stays well under ~1 GB. `year` is a column (UTC) for walk-forward
CV / out-of-core GNN/RL slicing; an optional `--partition-by year` Hive dataset is a trivial extension.

## 4. Engine judgment → **DuckDB, read-only, native `ASOF JOIN`**
Base tables are pulled read-only into an **in-memory DuckDB** (registered as relations); DuckDB performs
the assembly, including its native **`ASOF JOIN`** for the leak-safe OSINT merge, then `COPY … TO`
Parquet in one low-memory pass. This keeps the right engine for as-of merges **without** depending on the
DuckDB↔Postgres extension's network install. (Fallback if ever needed: `pandas.merge_asof` + `pyarrow`.)

**Read-only guarantees (enforced & proven):**
- Postgres session `SET default_transaction_read_only = on` → any write raises.
- Only `SELECT`s; **zero** PG temp/persistent/view objects (assembly is entirely in DuckDB memory).
- Output only to local `data/exports/` (gitignored); never written back to PG.
- **Catalog snapshot identical before/after** (7 tables, unchanged) — a verification assertion.

## 5. Join grain & leak-safety mechanics
- **Decision time `t = hour_ts`.** Every feature is known **as-of `t`**; the label is at `t + lead_hours`
  (lead ≥ 1, strictly future). Proven last stage: feature grid == panel grid, 0 orphans → no feature can
  encode the target.
- **LONG (primary, 6.15M):** `hourly_panel ⋈ feature_matrix ON (hour_ts, oblast_id)`; features repeat
  across the 6 leads; one label per lead. Matches the Direct multi-horizon design (`01 §D`).
- **WIDE (1.02M):** labels pivoted to `y_lead_1…y_lead_6` per `(hour_ts, oblast_id)`; features once.
- **OSINT as-of merge (the new, leak-safe part):**
  - National flags (`mig_31_airborne`, `tu_95_takeoff`, `mass_attack_active@national`): `ASOF` on time
    only (`hour_ts >= event_ts`), resolved per distinct hour then broadcast to all oblasts.
  - Oblast flag (`mass_attack_active@oblast`): `ASOF` partitioned by `oblast_id`.
  - Events are takeoff(`true`)→all-clear(`false`) pairs, so forward-fill = current state; default before
    the first event = `false`. **TTL guard** (`TTL_HOURS=6`): a stale `true` with no closing event older
    than 6 h reverts to `false` (a sortie doesn't last longer). `hours_since_*` columns expose staleness.
    Strictly `event_ts ≤ hour_ts` → leak-safe.
- **Weather** is contemporaneous@t (unambiguously leak-safe). The legitimate known-future forecast
  (`t+1..6h`, `01 §D`) is a documented *optional, lead-keyed* extension — not in the base export.

## 6. The export bundle (`data/exports/`)
| File | Rows | Purpose |
|---|---|---|
| `airraid_analytical_long.parquet` | 6,150,978 | **Primary** training/EDA table (Direct grain). |
| `airraid_analytical_wide.parquet` | 1,025,163 | Per-`(t,oblast)` with 6 label columns; compact. |
| `edges.parquet` | 106 | GNN `edge_index` (`src_idx`,`dst_idx` 0-based + oblast ids). |
| `oblasts.parquet` | 27 | Node metadata (id, name, centroid, `node_idx`). |
| `data_dictionary.md` | — | Per-column meaning, dtype, source table, leak-safety note. |
| `sample_preview.csv` | 10,000 | Human-eyeball sample (the only CSV). |
| `manifest.json` | — | Row counts, file sizes + sha256, build UTC, `source_db_max_ingested_at`, git rev. |

**LONG schema (29 cols):** keys `hour_ts, oblast_id, lead_hours` · label `y_alert_active` · static
`oblast_name, centroid_lat, centroid_lon` · weather@t `temp_c, wind_speed, precip_mm, cloud_cover` ·
spatial@t `self_alert_active, neighbor_alert_count, neighbor_alert_frac` · calendar@t `hour_of_day, dow,
month, is_weekend, hour_sin/cos, dow_sin/cos` · OSINT@t `osint_mig31_airborne, osint_tu95_takeoff,
osint_mass_national, osint_mass_oblast, hours_since_mig31, hours_since_tu95` · `year`.

## 7. Runnable execution path
```bash
./.venv/bin/pip install duckdb pyarrow                                   # one-time (in requirements.txt)
PYTHONPATH=src ./.venv/bin/python -m airraid.export_dataset --grain both --bundle --out data/exports
PYTHONPATH=src ./.venv/bin/python -m airraid.export_dataset --verify     --out data/exports
```
Idempotent: re-running overwrites the bundle deterministically. If `feature_matrix` is ever rebuilt,
re-run the export.

## 8. Verification (all PASS, against the live DB — read-only)
```
[PASS] long rows == hourly_panel                 6150978 == 6150978
[PASS] wide rows == feature_matrix grid          1025163 == 1025163
[PASS] edges == 106 · oblasts == 27
[PASS] long positives == panel positives         1052610 == 1052610   (reconciliation)
[PASS] OSINT states present                      366144 rows flagged   (the 1,021 flags landed)
[PASS] no NULL in non-weather features           0
[PASS] long/wide weather NULLs                    3888 (648×6) / 648, ALL pre-ERA5 (2022-02-24)
[PASS] catalog unchanged (7 tables)              read-only proof
```

## 9. Next steps → EDA (Stage 2, on the Parquet — never the live DB)
1. **Class-imbalance & base rates** per oblast / hour-of-day / lead (base rate ≈ 17.1%; per-oblast skew).
2. **Seasonality** (hour/dow/month cycles) and **structural-break** detection over the multi-year span
   (war-phase shifts) — a first-class EDA output (`01 §3.2/§3.5`).
3. **Spatial diffusion**: lift of `neighbor_alert_*` and the OSINT national flags on `y` by lead.
4. **Weather/OSINT association** with alert occurrence (mind the launch-site vs target-oblast paradox,
   `researches/exogenous-variables-research.md`).
5. **Reconciliation gate**: EDA aggregates must match Stage-1 raw (e.g. total alert hours per oblast).
6. **Emit the typed `EdaSummary`** (Pydantic: seasonality periods, breakpoints, per-oblast base rate)
   that Stage-3's feature config consumes — making EDA findings machine-readable for ML, with
   time-ordered CV + the release-blocking leakage-guard tests (`02 §"Stage 3"`).

*Cross-refs:* target/horizon rationale → [`01`](./01-initial-research-analysis.md); stage architecture →
[`02`](./02-general-workflow-architecture.md); ingestion → [`03`](./03-data-ingestion-engineering.md).
