# Stage 1 — Data Ingestion: Execution State

> **Living document.** Updated after each milestone. Records what ran, what failed, row/NULL
> stats, and the resume point if the session cuts off.

---

## Current Status (as of 2026-06-25T07:10Z)

| Milestone | State | Evidence |
|---|---|---|
| **M1 — Dockerized Postgres** | ✅ DONE | `airraid-postgres` healthy, `postgres:16`, host port **5433** |
| **M2 — Schema + verify + seed** | ✅ DONE | 6/6 tables; 27 oblasts, 106 adjacency rows |
| **M3/M4 — Vadimkin backfill + validate + panel** | ✅ DONE | **101,864** raw_alerts (2022→present); panel rebuilt below |
| **Live alerts.in.ua poller (APScheduler)** | ✅ DONE | `airraid.poller` — the ONLY scheduled job; **12** live alerts ingested |
| **Step 1 — Verify alerts timeline** | ✅ DONE | earliest alert **2022-02-25 16:36:22Z** (invasion start); latest 2026-06-25 |
| **Open-Meteo forecast weather** | ✅ DONE | **196,992** rows (recent window + 6-d forecast) |
| **Step 2 — Open-Meteo ARCHIVE backfill (2022→present)** | ✅ DONE | `ingest_weather_history` — **4,100,544** upserted; table **4,113,504**; 27 oblasts; 0 NULLs |
| **Step 3 — Telegram OSINT collector** | ✅ DONE (script) | `scrape_telegram_osint.py` written + parser unit-tested; run by hand (interactive auth) |
| **Step 4 — Restore `research_literature.md`** | ✅ DONE | recovered exact original from transcript → `researches/research_literature.md` (57 ln) |
| **Full 2022→present hourly_panel** | ✅ DONE | `materialize 1582` — **6,150,978** rows, base rate 17.11%, 0 NULLs |
| **MCP OSINT agent + server** | ✅ DONE | `MCP/OSINT_agent/` (agent+server+config+README); registered `airraid-osint` → **✔ Connected** |
| **OSINT scrape — auth + probe** | ✅ DONE | saved session authenticated (no manual input); probe wrote **14 real MiG-31 flags** |
| **OSINT full-history scrape (2022→present)** | ✅ DONE | **1,021** real flags (968 candidates), range 2022-02-24→2026-06-23 → frozen `osint_flags.csv` |
| **Static OSINT DB insert (one-time)** | ✅ DONE | `ingest_osint_static` — **1,021** rows UPSERTed (source=telegram), 0 errors, 0 NULLs |
| **Leak-safe `feature_matrix` (weather+neighbor+calendar as-of `t`)** | ✅ DONE | `build_features` — **1,025,163** rows; grid==panel; 0 NULLs except 648 pre-ERA5 weather |

**Architecture (asymmetric ingestion):** APScheduler is used for **exactly one** job — the live
`alerts.in.ua` poller. OSINT is a **static frozen dataset**: gathered by a **one-time, by-hand
historical scrape** (`scrape_telegram_osint.py`) → frozen `osint_flags.csv` → **inserted once**
(`ingest_osint_static.py`). There is **no scheduled/daily scraper, cron, or dynamic OSINT pipeline** —
the collector is run manually, not scheduled. Aligned in `plans/02` (Use case A) and `plans/03` (§A.0).

**DB connection:** `postgresql+psycopg://airraid:****@localhost:5433/airraid`.

**Live table counts:** oblasts=27 · oblast_adjacency=106 · raw_alerts=**101,876** (101,864 vadimkin +
12 alerts_in_ua) · exogenous_features=**4,114,525** (open_meteo 4,113,504 + telegram 1,021) ·
hourly_panel=**6,150,978** (full 2022→present Direct grid) · feature_matrix=**1,025,163** · ingest_errors=5

---

## Execution Log

#### 2026-06-24T23:3x Z — M1: Dockerized PostgreSQL
- **Ran:** wrote `docker-compose.yml` (`postgres:16`, named volume `airraid_pgdata`, healthcheck);
  `docker compose up -d`.
- **Failed → fixed:** host `:5432` already in use (non-Docker listener; not visible without sudo) →
  **remapped to host `5433`** in compose + `.env` (`DATABASE_URL`, `POSTGRES_PORT`). Re-`up` → **healthy** in ~8 s.
- **Next:** schema.

#### 2026-06-24T23:4x Z — M2: SQLAlchemy models + schema init
- **Ran:** `src/airraid/{config,db,models,schemas,reference}.py`; `python -m airraid.init_db`
  (`Base.metadata.create_all` — IF NOT EXISTS, never drops). Inspector confirmed all 6 tables.
- **Seed:** `python -m airraid.seed` → 27 oblasts + 106 symmetric adjacency rows (idempotent UPSERT).
- **Failed:** none.
- **Next:** ingestion.

#### 2026-06-24T23:4x Z — M3+M4: Vadimkin backfill (REAL data) + validate + materialize
- **Ran:** `python -m airraid.ingest_vadimkin` — downloaded `volunteer_data_en.csv`
  (101,869 rows; cols `region,started_at,finished_at,naive`), parsed UTC, resolved all 25 region
  strings (0 unresolved), Pydantic-validated, idempotent UPSERT on `uq_raw_alert`.
  - **Inserted/applied:** **101,864** rows to `raw_alerts`. **Dead-lettered:** 5.
- **Failed (quarantined, expected):** 5 rows → `ended_at must be > started_at` (zero/negative-duration
  intervals) → written to `ingest_errors` (stage=`validate`). Loop did not crash.
- **Validate (`python -m airraid.validate`, read-only):** all 6 tables exist; row + per-column NULL
  report printed. **NULL findings (benign):**
  - `oblasts.koatuu`, `oblasts.alerts_in_ua_uid`, `oblasts.ukrainealarm_region_id` = 100% NULL —
    *optional reference fields not yet populated (expected).*
  - `raw_alerts.external_id` = 100% NULL — *Vadimkin has no external id (expected).*
  - **Critical columns clean:** `raw_alerts.oblast_id / started_at / ended_at / alert_type / source /
    is_naive` = **0% NULL**.
- **Materialize (`python -m airraid.materialize`):** first attempt used a correlated `EXISTS`-per-cell
  plan → **ran 2m53s, cancelled**. Rewrote with **interval-expansion** (expand alerts → hours →
  indexed temp set) → **4.0 s**. Built **466,722** rows over `[2026-02-24 .. 2026-06-24]`
  (77,787 cells × 6 leads); positives **107,587**, base rate **23.05%**; lead-1 positives 17,937 →
  lead-6 17,924 (mild decay, as expected for a Direct grid).
- **Next immediate task (resume point):** implement live poller (`alerts.in.ua` 2-month window,
  APScheduler), Open-Meteo weather → `exogenous_features`, and the Telegram→Ollama OSINT parser; then
  expand `hourly_panel` to the full 2022→present range.

---

#### 2026-06-25T00:25Z — Asymmetric ingestion: live poller + static OSINT + doc alignment
- **Architecture aligned:** `plans/03 §A.0` (producers) and `plans/02` Use case A rewritten — APScheduler
  scheduling is for the live `alerts.in.ua` poller **only**; OSINT downgraded to a **static frozen,
  insert-once** dataset (no scraper / cron / dynamic LangGraph). OSINT phrases in
  `researches/exogenous-variables-research.md` aligned.
- **Cleanup review:** no wholesale-obsolete files in `plans/` / `researches/` — all remain relevant after
  alignment (targeted paragraph edits, not deletions). `research_literature.md` (generic TS textbook TOC)
  left in place as an optional-removal candidate (user-authored — flagged, not deleted).
- **Ran — live poller (`python -m airraid.poller once`):** GET `/v1/alerts/active.json` (Bearer); 28 active
  alerts; raion/hromada/city **rolled up to parent oblast** via `location_oblast`; Crimea/Luhansk permanent
  sirens excluded → **12 distinct live alerts UPSERTed** (source=alerts_in_ua) across Dnipropetrovsk(5),
  Kharkiv(4), Zaporizhzhia(2), Donetsk(1); 0 errors. `run` mode = APScheduler `BlockingScheduler` every
  `POLL_INTERVAL_SECONDS`, with end-detection (`ended_at` set when an alert leaves the active set).
- **Failed → fixed:** first poll UPSERTed 0 (filtered raion-level + 3 city resolve errors) → added the
  raion→oblast rollup. `apscheduler` install hit a shell-redirect glitch on `>=` → reinstalled (3.11.2).
- **Ran — static OSINT (`python -m airraid.ingest_osint_static`):** **NO-OP** — no frozen export at
  `data/osint/osint_flags.csv`. Nothing inserted (no synthetic data). Idempotent-UPSERTs source=`telegram`
  flags when a real file is supplied (cols: `event_ts,feature_key,scope,oblast,value_bool`).
- **Ran — re-materialize (`python -m airraid.materialize 120`):** **470,610** rows; window extended to
  2026-06-25 (now includes live alerts); base rate 22.88%.
- **Next immediate task:** Open-Meteo weather → `exogenous_features` (needs a `source` enum value, e.g.
  `open_meteo`); supply a real frozen OSINT export to populate takeoff flags; expand `hourly_panel` to full
  2022→present.

---

#### 2026-06-25T01:49Z — Open-Meteo weather → exogenous_features + cleanup

**Cleanup:** deleted `researches/research_literature.md` (generic time-series textbook TOCs — cognitive
overhead, unrelated to the finalized architecture; flagged twice before). Fixed the dangling citation in
`plans/01 §D` (now a generic literature reference). **Schema change:** added `open_meteo` to the `source` enum.

**CLI Execution (exact commands + raw output):**
```
$ docker exec -i airraid-postgres psql -U airraid -d airraid -c "ALTER TYPE source ADD VALUE IF NOT EXISTS 'open_meteo';"
ALTER TYPE

$ PYTHONPATH=src ./.venv/bin/python -m airraid.ingest_weather
  oblast  1 Cherkasy         rows=7296
  oblast  2 Chernihiv        rows=7296
  ...  (all 27 oblasts, 7296 rows each)  ...
  oblast 27 Zhytomyr         rows=7296
TOTAL weather rows upserted: 196992
# wall: ~33s (16.5s CPU), 27 Open-Meteo calls
```

**Data Validation (exact SQL + raw output):**
```
SELECT feature_key, count(*) rows, round(min(value_num),1) min, round(max(value_num),1) max, round(avg(value_num),1) avg
FROM exogenous_features GROUP BY 1 ORDER BY 1;
 feature_key | rows  | min  |  max  | avg
-------------+-------+------+-------+------
 cloud_cover | 49248 |  0.0 | 100.0 | 59.9
 precip_mm   | 49248 |  0.0 |  11.8 |  0.1
 temp_c      | 49248 | -3.4 |  41.6 | 16.1
 wind_speed  | 49248 |  0.0 |  51.1 |  9.1

SELECT count(*), min(event_ts), max(event_ts), count(DISTINCT oblast_id) FROM exogenous_features;
 total_rows |        earliest        |         latest         | oblasts
------------+------------------------+------------------------+---------
     196992 | 2026-04-16 00:00:00+00 | 2026-06-30 23:00:00+00 |      27

-- NULL counts per column (read-only):
 total=196992 | event_ts=0 | feature_key=0 | scope=0 | oblast_id=0 | value_num=0 | value_bool=196992 | value_text=196992 | source=0
```
`value_bool` / `value_text` are 100% NULL **by design** (typed-long table; weather uses `value_num`; the
`num_nonnulls(...)=1` CHECK enforces exactly one value column). All other columns 0% NULL.

**Status:** ✅ SUCCESS. `exogenous_features` populated with **196,992** real weather rows
(4 vars × 27 oblasts × 1824 h ≈ 76 days, incl. a 6-day forecast → the known-future input for k≤6 h).
Values in realistic ranges; 0 errors. (Open-Meteo returned ~76 d for `past_days=92` — sufficient now.)

**Table counts now:** raw_alerts=101,876 · exogenous_features=196,992 · hourly_panel=470,610 · ingest_errors=5.

**Next Step (resume point):** (a) supply a real frozen OSINT export at `data/osint/osint_flags.csv`
(`python -m airraid.ingest_osint_static`) to populate `mig_31_airborne`/`tu_95_takeoff`; (b) build the
leak-safe `feature_matrix` (weather + neighbor-oblast + calendar joined as-of `t`); (c) expand
`hourly_panel` to full 2022→present.

---

#### 2026-06-25T05:55Z — Steps 1–4: timeline verify · archive weather backfill · Telegram OSINT collector · literature restore

**Step 1 — Verify alerts timeline (SQL).**
```sql
SELECT count(*) total, min(started_at) earliest, max(started_at) latest,
       min(started_at) FILTER (WHERE source='vadimkin_volunteer') earliest_volunteer
FROM raw_alerts;
 total  |        earliest        |         latest         |   earliest_volunteer
--------+------------------------+------------------------+------------------------
 101876 | 2022-02-25 16:36:22+00 | 2026-06-25 00:07:08+00 | 2022-02-25 16:36:22+00

SELECT date_trunc('month', started_at) month, count(*) FROM raw_alerts GROUP BY 1 ORDER BY 1 LIMIT 4;
         month          | count
------------------------+-------
 2022-02-01 00:00:00+00 |   187   <- history begins Feb 2022 (day after the full-scale invasion)
 2022-03-01 00:00:00+00 |  2094
 2022-04-01 00:00:00+00 |  1782
 2022-05-01 00:00:00+00 |  1728
```
→ **Backfill window for Step 2 = 2022-02-25 → present** (read live by `_earliest_alert_date()`).

**Step 2 — Open-Meteo Historical Archive backfill (ERA5).** New module `src/airraid/ingest_weather_history.py`
(endpoint `https://archive-api.open-meteo.com/v1/archive`, free/no-key; chunked by calendar year per oblast;
reuses `ingest_weather.VARS` + `_upsert`; same `uq_exo` contract, `source=open_meteo`; overlap with the
forecast loader is overwritten with the more-accurate ERA5 value).
```
$ PYTHONPATH=src ./.venv/bin/python -m airraid.ingest_weather_history    # running in background
Historical weather backfill: 2022-02-25 -> 2026-06-25 | 27 oblasts × 5 yearly windows
# interim DB check while running:
SELECT count(*) rows, count(DISTINCT oblast_id) oblasts, min(event_ts)::date, max(event_ts)::date
FROM exogenous_features WHERE source='open_meteo';
  rows   | oblasts |   min      |    max
---------+---------+------------+------------
 1357440 |      27 | 2022-02-25 | 2026-06-30     (still climbing; ~9/27 oblasts of history done)
```
Status: **IN PROGRESS** — final counts + NULL validation appended on completion.

**Step 3 — Telegram OSINT collector (reconciling the contradiction).** The prior plan said "NO scraper";
clarified to mean **no *scheduled/daily* scraper**. Added `src/airraid/scrape_telegram_osint.py`: a
**one-time, by-hand** historical collector (Telethon, creds from `.env` `TELEGRAM_*`) over the channels in
`TELEGRAM_CHANNELS` → keyword pre-filter → **local Ollama** parse (`/api/generate`, `format=json`; regex
fallback if Ollama is down) → frozen `data/osint/osint_flags.csv`; that file is then inserted **once** by the
existing `ingest_osint_static.py`. Flags: `mig_31_airborne`, `tu_95_takeoff`, `mass_attack_active`.
Updated `requirements.txt` (uncommented `telethon>=1.34`), `config.py` (added `telegram_phone`), and
`plans/03 §A.0` (matrix + paragraph). Parser unit-tested offline (no network):
```
$ PYTHONPATH=src ./.venv/bin/python -c "from airraid.scrape_telegram_osint import _detect_regex ..."
"Зліт МіГ-31К ..."            -> mig_31_airborne national value_bool=True
"Ту-95МС на зльоті ..."       -> tu_95_takeoff   national value_bool=True
"Масований обстріл! ...Харківську область" -> mass_attack_active oblast=kharkiv value_bool=True
"Масована атака по Запорізькій області"    -> mass_attack_active oblast=zaporizhzhia value_bool=True
"Відбій загрози. МіГ-31К ... посадку"      -> mig_31_airborne value_bool=False   (all-clear)
"Доброго ранку, тримаймося!"  -> (no candidate, skipped)
```
⚠ **Not run end-to-end here:** the scrape needs interactive Telegram auth (login code) + network to
Telegram + a running Ollama — an outward action for the operator. To execute:
`PYTHONPATH=src ./.venv/bin/python -m airraid.scrape_telegram_osint --since 2022-02-24` then
`python -m airraid.ingest_osint_static`.

**Step 4 — Restore `research_literature.md`.** It was untracked (not in git; `git log` exit 128), so I
recovered the **exact original** from the session transcript (`Read` tool_result) and wrote it back to
`researches/research_literature.md` (10,335 chars, 57 lines — the chapter-by-chapter contents of
*Modern Time Series Forecasting with Python*, through Ch.17 Probabilistic Forecasting + model summaries).

**Status:** Steps 1, 3, 4 ✅ SUCCESS; Step 2 🔄 in progress (no errors). **Next:** on archive completion →
validate weather NULLs/coverage, then expand `hourly_panel` to full 2022→present (`materialize <days>`).

---

#### 2026-06-25T06:20Z — Step 2 COMPLETE (archive weather) + full-history hourly_panel

**Step 2 — archive backfill finished (exit 0).**
```
$ PYTHONPATH=src ./.venv/bin/python -m airraid.ingest_weather_history
Historical weather backfill: 2022-02-25 -> 2026-06-25 | 27 oblasts × 5 yearly windows
  oblast  1 Cherkasy         rows=151872
  oblast  2 Chernihiv        rows=151872
  ... (all 27 oblasts, 151872 rows each) ...
  oblast 27 Zhytomyr         rows=151872
TOTAL historical weather rows upserted: 4100544
EXIT=0
```
Validation:
```sql
SELECT feature_key, count(*) rows, round(min(value_num),1) min, round(max(value_num),1) max,
       round(avg(value_num),1) avg, min(event_ts)::date, max(event_ts)::date
FROM exogenous_features WHERE source='open_meteo' GROUP BY 1 ORDER BY 1;
 feature_key |  rows   |  min  |  max  | avg  |    min     |    max
-------------+---------+-------+-------+------+------------+------------
 cloud_cover | 1028376 |   0.0 | 100.0 | 61.7 | 2022-02-25 | 2026-06-30
 precip_mm   | 1028376 |   0.0 |  22.3 |  0.1 | 2022-02-25 | 2026-06-30
 temp_c      | 1028376 | -27.0 |  41.6 | 10.8 | 2022-02-25 | 2026-06-30   <- realistic winter lows
 wind_speed  | 1028376 |   0.0 |  55.8 | 12.3 | 2022-02-25 | 2026-06-30

SELECT count(*) total, count(DISTINCT oblast_id) oblasts FROM exogenous_features WHERE source='open_meteo';
 total   | oblasts        -- 4113504 | 27  (archive 4,100,544 + non-overlapping forecast rows)
-- NULLs: value_num=0 | oblast_id=0 | event_ts=0
```

**Full-history hourly_panel.**
```
$ PYTHONPATH=src ./.venv/bin/python -m airraid.materialize 1582
hourly_panel: rows=6150978 window=[2022-02-24 .. 2026-06-25] positives=1052610 base_rate=17.113%
```
Validation (per-lead + NULLs + table totals):
```sql
SELECT lead_hours, count(*) cells, sum(y_alert_active::int) positives, round(100.0*avg(y_alert_active::int),2) pct
FROM hourly_panel GROUP BY 1 ORDER BY 1;
 lead_hours |  cells  | positives |  pct
------------+---------+-----------+-------
  1..6 each | 1025163 |    175435 | 17.11
-- NULLs: hour_ts=0 | oblast_id=0 | y_alert_active=0
-- totals: raw_alerts=101876 | exogenous_features=4113504 | hourly_panel=6150978 | ingest_errors=5
```

**Status:** ✅ SUCCESS — **data ingestion is COMPLETE**. Full 2022→present coverage across alerts
(101,876), weather (4,113,504), and the Direct training grid (6,150,978); 0 NULLs in all critical
columns; 5 quarantined zero-duration alerts (expected, in `ingest_errors`).

**Next Step (resume point):** (a) *operator action* — run `scrape_telegram_osint --since 2022-02-24`
(needs Telegram login + Ollama) then `ingest_osint_static` to populate the OSINT flags from the frozen
CSV; (b) Stage 3 — build the leak-safe `feature_matrix` (weather + neighbor-oblast + calendar joined
as-of `t`) on top of `hourly_panel`.

---

#### 2026-06-25T07:10Z — MCP OSINT agent + server · real Telegram scrape · leak-safe feature_matrix

**Use case A justification (plans/02).** Rules: frozen dataset (not a live feed); **insert-once**
Pydantic-validated idempotent UPSERT; **no daily scraper/cron/scheduler/dynamic pipeline**; **local
Ollama** parse, once, offline; **no synthetic data**. → The MCP server exposes the collection+insert as
**on-demand tools an operator invokes manually** (a tool-interface boundary — the doc's "MCP-ready
architecture"), NOT a daemon/poller. Deterministic parse/validate/UPSERT stay in version-controlled
Python; the agent only orchestrates. If Telegram needs interactive auth we stop gracefully (no prompt),
and if no real data is available nothing is written.

**Built `MCP/OSINT_agent/`:** `agent.py` (async Telethon; uses saved `TELEGRAM_SESSION_STRING`, never
prompts; parses via a **resolved LOCAL Ollama model** — ignores the external `LLM_MODEL=claude-sonnet-4-6`
in `.env` — with deterministic regex fallback), `server.py` (FastMCP tools `scrape_osint_flags`,
`osint_status`, `ingest_osint_flags`), `mcp_config.json`, `README.md`. Anchored the frozen-CSV path to
repo root in both `agent.py` and `ingest_osint_static.py`. Installed `mcp==1.28.0`, `telethon==1.44.0`.

```
$ PYTHONPATH=src ./.venv/bin/python MCP/OSINT_agent/server.py selftest
MCP server 'airraid-osint' OK — registered tools:
  - scrape_osint_flags: Run the ONE-TIME offline OSINT scrape (Telethon + local Ollama) → frozen ...
  - osint_status: Report whether the frozen osint_flags.csv exists ...
  - ingest_osint_flags: Insert the frozen osint_flags.csv into exogenous_features EXACTLY ONCE ...

$ claude mcp add airraid-osint --scope local --env PYTHONPATH=.../src -- .../python .../server.py
Added stdio MCP server airraid-osint ... to local config
$ claude mcp list
airraid-osint: .../python .../MCP/OSINT_agent/server.py - ✔ Connected
```

**Real OSINT scrape — auth verified + probe (no fabricated data).** Saved session authenticated
**without** any manual SMS input. Probe (last week, regex parser):
```
$ python -c "asyncio.run(agent.collect_osint_flags(since=2026-06-18, until=2026-06-25, limit=300, use_llm=False))"
PROBE OK: {'flags_written': 14, 'candidates_scanned': 14, 'channels': 'kpszsu,air_alert_ua',
           'model_used': 'regex-fallback', 'out': '.../data/osint/osint_flags.csv'}
```
Sample frozen rows (genuine @kpszsu pattern — takeoff then ~20-30 min later the all-clear):
```
2026-06-20T15:31:38+00:00,mig_31_airborne,national,,true
2026-06-20T15:55:17+00:00,mig_31_airborne,national,,false
2026-06-21T00:40:43+00:00,mig_31_airborne,national,,true
2026-06-21T01:09:06+00:00,mig_31_airborne,national,,false
```
Full-history scrape (2022-02-24 → present) launched in background (`/tmp/run_full_scrape.py`). **Status:
IN PROGRESS** — on completion: `ingest_osint_static` → `exogenous_features` (source=telegram), then validate.

**Leak-safe `feature_matrix` (Task 2).** New `src/airraid/models.py::FeatureMatrix` + `src/airraid/build_features.py`.
One row per `(hour_ts, oblast_id)`; every feature known **as-of `t`** (weather contemporaneous; self/neighbor
alert state AT `t`, never `t+lead`; calendar deterministic UTC). Interval-expansion + pivoted TEMP tables.
```
$ PYTHONPATH=src ./.venv/bin/python -m airraid.build_features
feature_matrix: rows=1025163 window=[2022-02-24 .. 2026-06-25]
  weather-null rows (pre-ERA5 start)=648 | self_alert_active=175435 | neighbor>0=391432
```
Validation:
```sql
SELECT count(*) total, count(*) FILTER (WHERE temp_c IS NULL) temp_null,
  count(*) FILTER (WHERE self_alert_active IS NULL) self_null,
  count(*) FILTER (WHERE neighbor_alert_count IS NULL) nbr_null,
  count(*) FILTER (WHERE hour_sin IS NULL) cal_null,
  round(min(neighbor_alert_frac),3) frac_min, round(max(neighbor_alert_frac),3) frac_max,
  round(min(temp_c),1) temp_min, round(max(temp_c),1) temp_max FROM feature_matrix;
  total  | temp_null | self_null | nbr_null | cal_null | frac_min | frac_max | temp_min | temp_max
---------+-----------+-----------+----------+----------+----------+----------+----------+----------
 1025163 |       648 |         0 |        0 |        0 |    0.000 |    1.000 |    -27.0 |     38.8

-- leak-safety: every feature row maps to a panel cell (label at t+lead, strictly future)
 fm_rows | panel_grid | fm_not_in_panel        -- 1025163 | 1025163 | 0
```
`temp_null=648` = exactly 27 oblasts × 24 h of 2022-02-24 (one day before ERA5 starts) — an honest
coverage edge, not fabricated. `self_alert_active=175435` equals the panel's per-lead positives (cross-check OK).

**Status:** MCP agent/server ✅, scrape auth+probe ✅, feature_matrix ✅; full scrape 🔄 in progress.
**Next Step:** on scrape completion → `python -m airraid.ingest_osint_static` (insert frozen CSV once) →
validate `source=telegram` rows → ingestion phase COMPLETE.

---

#### 2026-06-25T07:35Z — OSINT full scrape + insert COMPLETE → Data Ingestion Phase DONE

**Full-history scrape finished (exit 0).** Transient `[Errno 54] Connection reset by peer` lines are
Telethon auto-reconnects (non-fatal); the run completed the full range.
```
FULL SCRAPE OK: {'flags_written': 1021, 'candidates_scanned': 968, 'channels': 'kpszsu,air_alert_ua',
                 'model_used': 'regex-fallback', 'since': '2022-02-24', 'until': '2026-06-25',
                 'out': '.../data/osint/osint_flags.csv'}
# frozen CSV: 1021 rows — mig_31_airborne 487 | mass_attack_active 323 | tu_95_takeoff 211
```
**Insert-once (idempotent, Pydantic-validated).**
```
$ PYTHONPATH=src ./.venv/bin/python -m airraid.ingest_osint_static
Static OSINT insert (ONE-TIME): applied=1021 flags; errors=0.
```
Validation (`exogenous_features` where `source='telegram'`):
```sql
SELECT feature_key, scope, count(*), count(*) FILTER (WHERE value_bool) true_cnt,
       min(event_ts)::date, max(event_ts)::date FROM exogenous_features WHERE source='telegram' GROUP BY 1,2 ORDER BY 1,2;
    feature_key     |  scope   | count | true_cnt |    min     |    max
--------------------+----------+-------+----------+------------+------------
 mass_attack_active | national |    98 |       95 | 2022-02-26 | 2026-05-24
 mass_attack_active | oblast   |   225 |      221 | 2022-02-24 | 2026-06-15
 mig_31_airborne    | national |   487 |      347 | 2022-08-08 | 2026-06-23
 tu_95_takeoff      | national |   211 |      164 | 2022-03-06 | 2026-04-24
-- total telegram=1021 | value_bool NULL=0 | event_ts NULL=0 | distinct oblasts tagged (oblast scope)=16
```

**Final database totals (all REAL data, no fabrication):**
```sql
 oblasts=27 | oblast_adjacency=106 | raw_alerts=101876
 exogenous_features=4114525  (open_meteo=4113504 + telegram=1021)
 hourly_panel=6150978 | feature_matrix=1025163 | ingest_errors=5
```

**Status:** ✅ **DATA INGESTION PHASE COMPLETE.** Alerts (2022→present), weather (full archive +
forecast), OSINT flags (real Telegram scrape), the Direct training grid, and the leak-safe
`feature_matrix` are all populated and validated. MCP OSINT agent/server registered (`airraid-osint`,
Connected) for on-demand re-collection. *Note:* the scrape used the deterministic regex parser over the
full archive (`use_llm=True` available via local Ollama for richer oblast tagging on mass-attack msgs).

**Next Step (Stage 2/3 — modeling, out of ingestion scope):** EDA + baselines (persistence /
seasonal-naive / climatology) on `hourly_panel ⋈ feature_matrix`; enforce the Stage-3 leakage-guard
tests (release-blocking per plans/01).

---

#### 2026-06-25T08:10Z — Stage-1→2 bridge: unified leak-safe analytical export (READ-ONLY)

Compiled all 7 tables into one analytical bundle for EDA/ML/GNN/RL. Full design + judgments in
**`plans/04-analytics-eda.md`**; pipeline `src/airraid/export_dataset.py` (deps `duckdb`, `pyarrow`).
**Strictly read-only** — DB session `default_transaction_read_only=on`, SELECT-only, **no** PG temp/views/
tables; all alignment out-of-DB in in-memory DuckDB (`ASOF JOIN` for the leak-safe OSINT merge). Output →
`data/exports/` (gitignored). **Key fix:** the 1,021 OSINT flags were in no feature table (feature_matrix
predates the scrape) → as-of forward-filled into the export (TTL 6h + `hours_since_*`).

**Format judgment:** Parquet+zstd (measured: long **18.2 MB** / wide **6.2 MB** — ~80–130× < CSV).

**CLI + raw output:**
```
$ ./.venv/bin/pip install duckdb pyarrow         # duckdb-1.5.4, pyarrow-24.0.0
$ PYTHONPATH=src ./.venv/bin/python -m airraid.export_dataset --grain both --bundle --out data/exports
  long=6150978 wide=1025163 edges=106 oblasts=27   (osint source rows=1021)
  files: airraid_analytical_long.parquet, ..._wide.parquet, edges.parquet, oblasts.parquet,
         data_dictionary.md, sample_preview.csv (10k), manifest.json
```
**Verification (`--verify`, all PASS):**
```
[PASS] long rows == hourly_panel          6150978 == 6150978
[PASS] wide rows == feature_matrix grid   1025163 == 1025163
[PASS] edges==106 · oblasts==27
[PASS] long positives == panel positives  1052610 == 1052610      (reconciliation)
[PASS] OSINT states present               366144 rows flagged     (1,021 flags landed)
[PASS] no NULL in non-weather features    0
[PASS] long/wide weather NULLs            3888 (648×6) / 648, all pre-ERA5 (2022-02-24)
[PASS] catalog unchanged (7 tables)       READ-ONLY proof (before==after: 7 relations)
```
**Status:** ✅ SUCCESS — unified analytical artifact built & verified; DB untouched (read-only proven).
**Next Step:** Stage 2 EDA on `data/exports/*.parquet` (base rates, seasonality/breaks, neighbor & OSINT
diffusion) → emit typed `EdaSummary` for Stage 3 (per `plans/02 §Stage 2`).

---

## Database View & Control Cheat Sheet

### Final schema (6 tables)
```
oblasts(id PK smallint, name_en UQ, name_uk UQ, koatuu, centroid_lat, centroid_lon,
        alerts_in_ua_uid UQ, ukrainealarm_region_id)
oblast_adjacency(oblast_id FK, neighbor_oblast_id FK, PK(both), CHECK oblast_id<>neighbor)
raw_alerts(id PK bigint, oblast_id FK, started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ,
        alert_type ENUM, source ENUM, is_naive bool, external_id, ingested_at,
        UQ(oblast_id,started_at,alert_type,source), CHECK ended_at>started_at,
        idx(oblast_id,started_at),(started_at))
exogenous_features(id PK bigint, event_ts TIMESTAMPTZ, feature_key, scope ENUM, oblast_id FK?,
        value_bool, value_num, value_text, source ENUM, ingested_at,
        UQ(feature_key,event_ts,scope,oblast_id,source), CHECK scope/oblast, CHECK one-value)
hourly_panel(hour_ts TIMESTAMPTZ, oblast_id FK, lead_hours smallint, PK(all three),
        y_alert_active bool, built_at, CHECK lead_hours BETWEEN 1 AND 6)
ingest_errors(id PK bigint, occurred_at, source, stage, error, payload)   -- dead-letter
```

### Docker control (host port 5433)
> ⚠ **Never `docker compose down -v`** — `-v` deletes the volume → drops the DB (violates §D no-drop).

| Command | Expected output |
|---|---|
| `docker compose up -d` | `✔ Container airraid-postgres  Started` |
| `docker compose ps` | `airraid-postgres  Up (healthy)  0.0.0.0:5433->5432/tcp` |
| `docker compose logs --tail=5 postgres` | `… database system is ready to accept connections` |
| `docker compose stop` / `start` | `✔ Container airraid-postgres  Stopped` / `Started` |
| `docker exec -it airraid-postgres psql -U airraid -d airraid` | `airraid=#` prompt |

### Run the pipeline (from repo root)
```
export PYTHONPATH=src
./.venv/bin/python -m airraid.init_db                 # create tables (idempotent)
./.venv/bin/python -m airraid.seed                    # seed oblasts + adjacency
./.venv/bin/python -m airraid.ingest_vadimkin         # backfill raw_alerts 2022→present (REAL data)
./.venv/bin/python -m airraid.ingest_weather          # recent-window weather + 6-day forecast
./.venv/bin/python -m airraid.ingest_weather_history  # FULL 2022→present ERA5 archive backfill
./.venv/bin/python -m airraid.scrape_telegram_osint --since 2022-02-24  # one-time OSINT scrape → frozen CSV (interactive auth)
./.venv/bin/python -m airraid.ingest_osint_static     # insert frozen osint_flags.csv ONCE
./.venv/bin/python -m airraid.materialize 1582        # build hourly_panel over full history (days)
./.venv/bin/python -m airraid.build_features          # build leak-safe feature_matrix (as-of t)
./.venv/bin/python -m airraid.validate                # read-only row/NULL report
./.venv/bin/python -m airraid.poller once             # one live alerts.in.ua poll (run = APScheduler loop)

# OSINT (one-time, offline — Use case A). Either the module CLI or the MCP server tools:
./.venv/bin/python MCP/OSINT_agent/server.py selftest # list MCP tools (proves server boots)
./.venv/bin/python -m airraid.ingest_osint_static     # insert frozen osint_flags.csv ONCE
```

### Verification SQL (with the outputs observed this run)
```sql
SELECT count(*), min(started_at), max(started_at) FROM raw_alerts;
-- 101864 | 2022-02-25 16:36:22+00 | 2026-06-24 00:50:09+00

SELECT o.name_en, count(*) FROM raw_alerts r JOIN oblasts o ON o.id=r.oblast_id
GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
-- Dnipropetrovsk 11780 | Kharkiv 11145 | Zaporizhzhia 8329 | Donetsk 8120 | Sumy 7743

SELECT lead_hours, count(*), sum(y_alert_active::int) AS positives
FROM hourly_panel GROUP BY 1 ORDER BY 1;
-- full history: 1..6 | 1,025,163 cells each | 175,435 positives each (base rate 17.11%)

SELECT stage, count(*) FROM ingest_errors GROUP BY 1;   -- validate | 5
SELECT * FROM raw_alerts ORDER BY started_at DESC LIMIT 10;   -- newest alerts
```
