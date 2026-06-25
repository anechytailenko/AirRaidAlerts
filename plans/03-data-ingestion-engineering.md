# 03 — Data Ingestion Engineering (Stage 1)

## Hard Constraints
- **Dockerized infrastructure (mandatory).** All PostgreSQL infrastructure runs via **`docker-compose`**
  — a `postgres:16` service with a named volume and a published port; `DATABASE_URL` targets the
  container. No host-native Postgres, no cloud DB.
- **100% real data (mandatory).** The pipeline relies entirely on real ingested data. **No synthetic,
  mock, fixture, or fabricated data anywhere** — not in ingestion, not in tests (see §D).
- **Local LLM only — Ollama (mandatory).** The LangGraph OSINT parser is powered by a **local `ollama`
  model**. **No external LLM providers** (Anthropic, OpenAI, etc.).

## A. Step-by-Step Pipeline Flow

The pipeline is **one scheduled live poller** plus **one-shot loaders**, feeding one
validation→transform→load core, then a materialization step. All code is Python; all timestamps are
UTC; Pydantic v2 is the gate before any DB write.

### A.0 Producers (Extraction) — Asymmetric Ingestion Strategy
**Scheduling is used for exactly ONE job — the live `alerts.in.ua` poller** (APScheduler
`BackgroundScheduler`, Python-native, no broker). Everything else is a **one-shot** script. Each job
is idempotent and independently restartable:

| Job | Trigger | Source | Notes |
|---|---|---|---|
| `poll_active_alerts` | **APScheduler** interval, `POLL_INTERVAL_SECONDS` (default 45 s) | `GET https://api.alerts.in.ua/v1/alerts/active.json` | The **only** scheduled job. Soft 8–10 req/min/IP (hard 12 → 429); token serves ~2 months. |
| `backfill_history` | **one-shot** script | Vadimkin CSVs (2022→present) | Bulk seed; raion→oblast rollup. Already loaded. |
| `scrape_osint` | **one-shot collector**, run by hand | Telegram (Telethon, creds in `.env`) → frozen `data/osint/osint_flags.csv` | Historical scrape of pinned channels; keyword pre-filter → local Ollama parse (regex fallback). **NOT a cron/daemon/scheduled pipeline** — produces the frozen file once. |
| `osint_static` | **one-shot, run exactly ONCE** | Frozen `osint_flags.csv` → `exogenous_features` (source=`telegram`) | Inserts the frozen export idempotently. Flags (`mig_31_airborne`, `tu_95_takeoff`, `mass_attack_active`). No synthetic data. |
| `pull_weather` | **one-shot** / periodic refresh | Open-Meteo (history archive + forecast) | No key; per-oblast centroid lat/lon. `ingest_weather` = recent window + forecast; `ingest_weather_history` = full 2022→present ERA5 archive. |

**OSINT is static (frozen historical dataset), collected once.** We do **not** run a *daily/scheduled*
Telegram scraper or any time-changing OSINT pipeline. The flags are gathered in a **single, by-hand
historical scrape** (`scrape_telegram_osint.py`, Telethon over the channels pinned in
`TELEGRAM_CHANNELS`) that writes a **frozen** `data/osint/osint_flags.csv`; that file is then ingested
**exactly once** (`ingest_osint_static.py`, idempotent UPSERT → `exogenous_features`). Message parsing
is done **offline** with a **local Ollama** model (`OLLAMA_BASE_URL=http://localhost:11434`, e.g.
`llama3.1:8b`), behind a cheap keyword pre-filter, with a deterministic regex fallback if Ollama is
unreachable — never a live consumer, never an external LLM provider. If neither the scrape nor a real
export is present, `ingest_osint_static` inserts nothing (flags are never fabricated).

**API data window:** `poll_active_alerts` uses `ALERTS_IN_UA_TOKEN` to fetch **only the last ~2 months**
of data; the full **2022→present** history is loaded by `backfill_history` from the open-source Vadimkin
dataset (see `../researches/exogenous-variables-research.md §4`). `UKRAINEALARM_API_TOKEN` is **pending
response** and currently inactive — alerts.in.ua is the sole live source until it arrives.

**Error-handling policy (uniform across jobs)** — implemented with `tenacity`:
- **Transient** (DNS/connection/read timeout, HTTP 5xx, **HTTP 429**): retry with
  `wait_exponential(multiplier=1, max=60) + wait_random(0,2)` jitter, `stop_after_attempt(5)`; on 429
  honor the `Retry-After` header. After exhaustion → log `WARNING`, skip this tick (next tick recovers);
  a per-source **circuit breaker** opens after N consecutive failures to stop hammering a down endpoint.
- **Permanent / schema** (HTTP 4xx ≠ 429, JSON shape change, Pydantic `ValidationError`,
  unresolved oblast): **do not retry** — write the raw payload + error to the `ingest_errors`
  dead-letter table and emit a structured `ERROR` log. The scheduler loop **never crashes**; one bad
  record cannot stop the stream.
- **Idempotency** makes every retry safe (see Loading); re-running any job is a no-op on already-stored rows.

### A.1 Validation (raw → Pydantic v2)
Each producer converts its raw payload to a dict, then into a **strict** Pydantic v2 contract *before*
touching the DB:

```
raw bytes/json ──parse──▶ dict ──RawAlertEvent.model_validate(d, strict=True)──▶ typed event
                                   │ ValidationError
                                   └────────────────▶ ingest_errors (dead-letter) + ERROR log
```
- `RawAlertEvent`: `oblast_raw: str`, `started_at: AwareDatetime`, `ended_at: AwareDatetime | None`,
  `alert_type: AlertType`, `source: SourceEnum`, `external_id: str | None`, `is_naive: bool = False`.
  Field validators enforce **tz-aware** datetimes and `ended_at is None or ended_at > started_at`.
- `ExogenousFlagEvent`: `event_ts: AwareDatetime`, `feature_key: str`, `scope: Literal["national","oblast"]`,
  `oblast_raw: str | None`, `value_bool/value_num/value_text` (exactly one set), `source`.
- A model-level validator rejects events whose `oblast_raw` cannot be resolved (see Transformation),
  routing them to the dead-letter rather than guessing.

### A.2 Transformation
1. **Timestamps → UTC.** Parse incoming time (alerts.in.ua is ISO-8601; Vadimkin CSV already UTC;
   Telegram text parsed by LangGraph to ISO). Naive datetimes are interpreted as `Europe/Kyiv`
   (`zoneinfo.ZoneInfo`) then `.astimezone(UTC)`. Stored as `TIMESTAMP WITH TIME ZONE`. Volunteer
   records lacking an end time keep `is_naive=True` (consumer assumes 30-min duration; never fabricated
   into `ended_at`).
2. **Region string → canonical `oblast_id`.** `resolve_oblast(name) -> int | None` uses the `oblasts`
   table plus an **alias/transliteration map** covering variants: `"м. Київ"`, `"Київ"`, `"Kyiv City"`,
   `"Київська область"`, `"Kyivska oblast"`, `"Kyiv Oblast"` → distinct canonical IDs; case-fold +
   strip + NFC-normalize before lookup. Unresolved → **quarantine** in `ingest_errors` (never a silent
   drop, never a default oblast).
3. **Raion → oblast rollup.** Since Dec 2025 alerts.in.ua emits raion-level events; map each raion to
   its parent oblast so the canonical grain stays **oblast** (target is oblast-level). Multiple
   concurrent raion alerts collapse to a single oblast-active interval (union of spans).
4. **Exclusions.** Drop the two permanent sirens (Luhansk since 2022-04-04, Crimea since 2022-12-10) —
   they carry no temporal signal and would bias the base rate.

### A.3 Loading (idempotent UPSERT, Repository pattern)
- SQLAlchemy 2.0; all DB access via `AlertRepository` (Pydantic-typed in/out) — no raw SQL in
  producers. `SqlAlchemyAlertRepository` is the only implementation.
- UPSERT via `sqlalchemy.dialects.postgresql.insert(RawAlert).values(...).on_conflict_do_update(
  index_elements=[...unique key...], set_={...})`. The natural unique key
  `(oblast_id, started_at, alert_type, source)` guarantees re-ingest is a no-op/refresh, not a duplicate.
- Writes are batched in one transaction per producer tick; the backfill uses `execute(insert, rows)`
  bulk mode. `exogenous_features` upserts on `(feature_key, event_ts, scope, oblast_id, source)`.

### A.4 Materialization (→ `hourly_panel`)
Incremental `INSERT … SELECT … ON CONFLICT DO UPDATE`, run after each load tick (and fully on backfill):
1. **Hourly alert state.** For every `(oblast_id, hour_ts)` over the covered range, `alert_active =
   EXISTS(raw_alert overlapping [hour_ts, hour_ts+1h))` — an interval-overlap join (`tstzrange &&`).
2. **Feature matrix (as-of `t`, leak-safe).** Build `feature_matrix(hour_ts, oblast_id, …)` once per
   cell: own lags/rolling alert state, neighbor-oblast state via `oblast_adjacency`, calendar/Fourier
   terms, and exogenous features joined **as-of** (`LATERAL` "last value with `event_ts <= hour_ts`").
   No column may read data after `hour_ts`.
3. **Direct grid.** Expand to `hourly_panel(hour_ts, oblast_id, lead_hours ∈ {1..6})` and set the label
   `y_alert_active = alert_active(oblast_id, hour_ts + lead_hours)`. **Only the label references the
   future**; features come from `feature_matrix` at `hour_ts`. Features are stored once per
   `(hour_ts, oblast_id)` and joined at train time — `hourly_panel` itself holds only the key + label
   (avoids 6× duplication of wide feature rows).

---

## B. Database Schema Specifications

SQLAlchemy 2.0 declarative (`Mapped[...]` / `mapped_column`), PostgreSQL types. DDL intent shown
alongside each table.

### B.1 `oblasts` — canonical regions
```python
class Oblast(Base):
    __tablename__ = "oblasts"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)           # canonical 1..27, app-assigned
    name_en: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_uk: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    koatuu: Mapped[str | None] = mapped_column(String(12))                    # official admin code
    centroid_lat: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    centroid_lon: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)  # for Open-Meteo lookup
    alerts_in_ua_uid: Mapped[int | None] = mapped_column(Integer, unique=True)    # maps to {uid} endpoints
    ukrainealarm_region_id: Mapped[str | None] = mapped_column(String(16))
```
- PK `id`; UNIQUE `name_en`, `name_uk`, `alerts_in_ua_uid`. Seeded once from a static reference list.

### B.2 `oblast_adjacency` — self-referencing border map (spatial features)
```python
class OblastAdjacency(Base):
    __tablename__ = "oblast_adjacency"
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    neighbor_oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    __table_args__ = (CheckConstraint("oblast_id <> neighbor_oblast_id", name="ck_adj_no_self"),)
```
- Composite PK `(oblast_id, neighbor_oblast_id)`; both FK→`oblasts.id`. Stored **symmetrically** (both
  directions) so a neighbor lookup is a single indexed `WHERE oblast_id = :id`.

### B.3 `raw_alerts` — event log (historical + live)
```python
class RawAlert(Base):
    __tablename__ = "raw_alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)             # surrogate (identity)
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   # TIMESTAMPTZ
    ended_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))            # NULL = ongoing/unknown
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), nullable=False, default=AlertType.AIR_RAID)
    source:     Mapped[Source] = mapped_column(Enum(Source), nullable=False)
    is_naive:   Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)        # volunteer 30-min assumption
    external_id: Mapped[str | None] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("oblast_id", "started_at", "alert_type", "source", name="uq_raw_alert"),  # idempotency key
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_alert_interval"),
        Index("ix_raw_alert_oblast_time", "oblast_id", "started_at"),
        Index("ix_raw_alert_time", "started_at"),
    )
```
- `AlertType` enum: `air_raid, artillery, urban_combat, chemical, nuclear, info`.
- `Source` enum: `alerts_in_ua, ukrainealarm, vadimkin_official, vadimkin_volunteer, telegram`.

### B.4 `exogenous_features` — typed-long store (macro + atomic flags)
A single typed-long table holds heterogeneous signals: national boolean flags from LangGraph
(`mig_31_airborne`, `tu_95_takeoff`, `mass_attack_active`), per-oblast numerics (`temp_c`,
`wind_speed`), and macro categoricals (`war_phase`). This avoids a sparse 50-column wide table.
```python
class ExogenousFeature(Base):
    __tablename__ = "exogenous_features"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_ts:   Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(48), nullable=False)     # 'mig_31_airborne','temp_c','war_phase'
    scope:      Mapped[Scope] = mapped_column(Enum(Scope), nullable=False)    # 'national' | 'oblast'
    oblast_id:  Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("oblasts.id"))  # NULL when national
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_num:  Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    value_text: Mapped[str | None] = mapped_column(Text)
    source:     Mapped[Source] = mapped_column(Enum(Source), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("feature_key", "event_ts", "scope", "oblast_id", "source", name="uq_exo"),
        CheckConstraint("(scope = 'national') = (oblast_id IS NULL)", name="ck_exo_scope"),
        CheckConstraint("num_nonnulls(value_bool, value_num, value_text) = 1", name="ck_exo_one_value"),
        Index("ix_exo_key_time", "feature_key", "event_ts"),
        Index("ix_exo_oblast_time", "oblast_id", "event_ts"),
    )
```

### B.5 `hourly_panel` — analytical Direct grid (`timestamp × oblast_id × lead_hours`)
```python
class HourlyPanel(Base):
    __tablename__ = "hourly_panel"
    hour_ts:    Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)   # UTC, hour-truncated
    oblast_id:  Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    lead_hours: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    y_alert_active: Mapped[bool] = mapped_column(Boolean, nullable=False)     # label at hour_ts + lead_hours
    built_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("lead_hours BETWEEN 1 AND 6", name="ck_panel_lead"),
        Index("ix_panel_time", "hour_ts"),
    )
```
- Composite PK `(hour_ts, oblast_id, lead_hours)`. **Features are NOT duplicated here** — they live once
  per `(hour_ts, oblast_id)` in the leak-safe `feature_matrix` (table or materialized view) and are
  joined at train/serve time. This keeps the grid 6× smaller and makes the label the only future-aware column.

---

## C. Data Sources Matrix

| Need | Primary (URL · auth · limits) | Fallback(s) | Format | Notes / leakage |
|---|---|---|---|---|
| **Live alert target** | `https://api.alerts.in.ua/v1/iot/active_air_raid_alerts.json` · `Authorization: Bearer <ALERTS_IN_UA_TOKEN>` (or `?token=`) · soft 8–10/min, hard 12/min→429 · **token fetches only the last ~2 months** | `https://api.ukrainealarm.com` (form token) — **pending response, inactive** | JSON | Raion-level since Dec 2025 → roll up to oblast. 2022→present comes from the Historical-alerts backfill below. |
| **Per-oblast status** | `…/v1/iot/active_air_raid_alerts/{uid}.json` (`uid` = `oblasts.alerts_in_ua_uid`) | ukrainealarm region status (**pending**) | JSON | — |
| **Historical alerts (2022→present)** | `github.com/Vadimkin/ukrainian-air-raid-sirens-dataset` (`official_data_*.csv` ≥2022-03-15; `volunteer_data_*.csv` ≥2022-02-25, oblast-only, `naive`→30 min) | alerts.in.ua `…/v1/regions/{uid}/alerts/{period}.json` (**2 req/min**, ~2-month token window); `github.com/Tyrrrz/RaidTrend`; Kaggle mirrors | CSV / JSON | All **UTC**; exclude permanent Luhansk/Crimea sirens. **Canonical backfill** — the live API only serves ~2 months; see `../researches/exogenous-variables-research.md §4`. |
| **OSINT air-tactical flags** (`mig_31_airborne`,`tu_95_takeoff`,`mass_attack_active`) | Telegram **`@kpszsu`** (official Air Force ЗСУ) + **`@air_alert_ua`** via Telethon → LangGraph parser | Vetted community monitors (**verify handle before use**) | Telegram text | ⚠ **Fake Air Force channels exist** (disinfo.detector.media) — pin the official numeric `channel_id`, not the handle. Short lead → `k=1h` feature; lag leak-safe. Genre backing: Springer *Digital War* (25 channels). |
| **Weather** (`temp_c`, wind, precip, cloud/visibility) | **Open-Meteo** `https://archive-api.open-meteo.com` (history) + `https://api.open-meteo.com` (forecast) · **no key** · ~10k calls/day · CC-BY-4.0 | OpenWeatherMap (`OPENWEATHER_API_KEY`) | JSON | **Primary = target-oblast** weather at centroid (interception-driven); launch-site weather is secondary/national. Forecast = known-future input for `k≤6h`. See `../researches/exogenous-variables-research.md §5`. |
| **Macro conflict phase** (`war_phase`, attack cadence) | **Derived internally** from `raw_alerts`/strike cadence (rolling intensity, changepoints) | ACLED API `https://acleddata.com` (`ACLED_API_KEY`+`ACLED_EMAIL`, optional enrichment) | derived / JSON | Avoid news-sentiment (latency + leakage, per `../researches/exogenous-variables-research.md`). |

---

## D. Testing Strategy & State Tracking

**Hard rules — idempotent and non-destructive:**
1. **NEVER drop the database or tables.** Tests run **strictly read-only** against the real Docker
   PostgreSQL — no `DROP`, no `CREATE/DROP` fixtures, no `TRUNCATE`, no schema teardown. The structural
   test only **verifies that the required tables exist** via `sqlalchemy.inspect(engine).get_table_names()`
   (or `information_schema.tables`): `oblasts`, `oblast_adjacency`, `raw_alerts`, `exogenous_features`,
   `hourly_panel`, `ingest_errors`. A missing table **fails** the test; the test never creates or drops it.
2. **Non-sparsity / silent-failure check.** For **every table**, print the **total row count** and, for
   **every column**, the **exact number of NULLs** — columns introspected via the SQLAlchemy inspector,
   counted with `SELECT count(*) AS n, count(*) FILTER (WHERE "<col>" IS NULL) AS nulls__<col>, …`. This
   proves data actually landed and that no column is silently all-NULL. Emit a readable per-table report.
3. **Real data only.** Every assertion runs against the genuinely ingested DB — **no synthetic/mock
   fixtures** (per Hard Constraints). An **empty table (row count 0) is a FAILURE**, not a pass.

**State tracking — `current_state/03-data-ingestion-engineering-state.md`.** We maintain a living state
file. On **any** error during execution or data assertion (API failure, schema drift, empty/sparse table,
Docker issue), it must be updated to record **exactly what ran successfully and what failed** (step ·
command · error · what succeeded before · remediation). It also carries a **Cheat Sheet** of Docker
controls and verification SQL with their expected outputs. It is the first place to read and to update
whenever something breaks.

---

*References:* feature rationale → `../researches/exogenous-variables-research.md`; horizon/leakage → `01 §D`;
storage/contracts & OSINT staging → `02` (Stage 1, Use case A).
