# Data Dictionary — airraid analytical export

Every feature is known **as-of `t = hour_ts`**; labels are at `t + lead`. The export is strictly
read-only and out-of-database. Companion files: `edges.parquet` (GNN `edge_index` via `node_idx`),
`oblasts.parquet` (node metadata + `node_idx`).

| Column(s) | Dtype | Source | Meaning / leak-safety |
|---|---|---|---|
| `hour_ts` | timestamptz | hourly_panel/feature_matrix | Decision time t (UTC). Key. |
| `oblast_id` | int | oblasts | Oblast id (1–27). Key. |
| `lead_hours` | int | hourly_panel | Forecast horizon k∈1..6 (LONG only). Key. |
| `y_alert_active` | bool | hourly_panel | LABEL: alert active at t+lead_hours (LONG). |
| `y_lead_1..y_lead_6` | bool | hourly_panel | LABELS at t+k for k=1..6 (WIDE). |
| `oblast_name` | str | oblasts | English oblast name (static). |
| `centroid_lat/lon` | double | oblasts | Oblast centroid (static; GNN/geo). |
| `temp_c/wind_speed/precip_mm/cloud_cover` | double | exogenous_features(open_meteo)→feature_matrix | Target-oblast weather AS-OF t (contemporaneous, leak-safe). |
| `self_alert_active` | bool | raw_alerts→feature_matrix | Was THIS oblast under alert AT t (autoregressive). |
| `neighbor_alert_count` | int | raw_alerts+oblast_adjacency→feature_matrix | # adjacent oblasts under alert AT t. |
| `neighbor_alert_frac` | double | raw_alerts+oblast_adjacency→feature_matrix | Fraction of neighbors under alert AT t. |
| `hour_of_day/dow/month` | int | hour_ts | Calendar parts (UTC), deterministic. |
| `is_weekend` | bool | hour_ts | Sat/Sun (UTC). |
| `hour_sin/cos, dow_sin/cos` | double | hour_ts | Cyclical calendar encodings. |
| `osint_mig31_airborne` | bool | exogenous_features(telegram) | ASOF state: MiG-31K airborne at t (TTL 6h). Leak-safe (event_ts≤t). |
| `osint_tu95_takeoff` | bool | exogenous_features(telegram) | ASOF state: Tu-95 takeoff active at t (TTL 6h). |
| `osint_mass_national` | bool | exogenous_features(telegram) | ASOF state: national mass-attack active at t (TTL 6h). |
| `osint_mass_oblast` | bool | exogenous_features(telegram) | ASOF state: oblast-scoped mass-attack active at t (TTL 6h). |
| `hours_since_mig31/tu95` | int|null | exogenous_features(telegram) | Hours since last MiG-31/Tu-95 event ≤ t (staleness; null if none yet). |
| `year` | int | hour_ts | Partition/CV key (UTC year). |
