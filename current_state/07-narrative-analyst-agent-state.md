# Stage 5 — Narrative Analyst Agent: Execution State

> **Living document.** Single source of truth for the Narrative Analyst phase. Records what was
> implemented, what passed, what is deferred, and every placeholder/edge case needing future
> resolution. Implements [`plans/07-narrative-analyst-agent.md`](../plans/07-narrative-analyst-agent.md).

---

## Current Status (as of 2026-06-25T17:00Z)

| Component | State | Evidence |
|---|---|---|
| **Payload contract** `AnalystResponse` | ✅ DONE | `src/airraid/schemas.py`; validator: numbers ⇒ must carry a plot |
| **EDA read-only data layer** | ✅ DONE | `src/airraid/eda/data.py` — `read_parquet` only, no write path; oblast/column resolution |
| **Metrics-in-plot helpers** | ✅ DONE | `src/airraid/eda/plots.py` — `metrics_textbox`, `finalize`, `Analysis.plot_texts`, `fmt_metric` |
| **5 baseline tools** | ✅ DONE | `src/airraid/eda/stats.py` — seasonality, acf/pacf, stationarity (ADF+KPSS), summary, distribution |
| **Security sandbox** | ✅ DONE | `src/airraid/eda/sandbox.py` — AST allow-list + constrained subprocess (timeout + rlimits) |
| **Orchestrator** `NarrativeAnalyst` | ✅ DONE | `src/airraid/analyst/agent.py` — router, deterministic narrator, dynamic synthesizer |
| **LangGraph wiring** | ✅ DONE | `src/airraid/analyst/graph.py` — router→{baseline\|dynamic\|safety}→validate→END |
| **MCP server** (`airraid-analyst`) | ✅ DONE | `MCP/Narrative_Analyst/server.py` — 6 tools; `selftest` lists all |
| **Container** (read-only) | ✅ AUTHORED | `Dockerfile` + `docker-compose.yml` — :ro data+artifacts, tmpfs, non-root, caps drop, mem/pids limits |
| **Test suite** | ✅ 25/25 PASS | `tests/test_narrative_analyst.py` |
| **ML regression** | ✅ 15/15 PASS | `tests/test_ml_components.py` unaffected |

**Architecture (one core, two entrypoints).** All cognition + statistics live in importable, unit-tested
`src/airraid/{eda,analyst}`; `MCP/Narrative_Analyst/server.py` is a thin FastMCP wrapper (mirrors
`MCP/OSINT_agent/`). The agent is **read-only at the deterministic boundary** (plans/02) and **never
fabricates numbers** — the narrator interpolates the exact values a tool produced. The dynamic synthesizer
is wrapped in **AST validation → subprocess sandbox → read-only container**.

**Data access:** parquet + artifacts only (owner decision) — `AIRRAID_EXPORTS_DIR` →
`data/exports/airraid_analytical_wide.parquet`. No Postgres in the container.

---

## ✅ Successfully Processed (implemented, verified, passing)

**Components**
- `AnalystResponse` payload (description always; `test_result` ⇒ requires `plot_image`; `tool_used`,
  `is_dynamic_tool`).
- `eda/data.py`: cached read-only wide-parquet loader; `resolve_oblast` (name/id/national), `series`,
  `hourly_series` (regular grid), `feature_frame` (the sandbox `df`).
- `eda/plots.py`: `fmt_metric` (one canonical formatter shared by the plot box, the narrator, and the
  tests), `metrics_textbox`, `finalize` (captures drawn text + base64), `Analysis`.
- `eda/stats.py`: the **5** baseline tools, each returning exact numbers + a base64 plot **with the
  metrics drawn on it**.
- `eda/sandbox.py`: `validate_code` (AST allow-list) + `run_tool_body` (subprocess, wall-time timeout,
  CPU/AS rlimits, minimal `__builtins__`, injected read-only data handles, scratch-only PNG output).
- `analyst/agent.py`: `NarrativeAnalyst` — regex/keyword router (safety → complex/dynamic → baseline →
  default dynamic), deterministic narrator, baseline/dynamic/safety handlers, `SYSTEM_PROMPT` carrying the
  verbatim metrics-in-plot rule, `_ollama_code_generator` (host Ollama, temp 0, injectable).
- `analyst/graph.py`: LangGraph `StateGraph` with a final Pydantic **validate** node.
- `MCP/Narrative_Analyst/`: `server.py` (5 tools + `ask_analyst`), `mcp_config.json`, `Dockerfile`,
  `docker-compose.yml`, `README.md`.

**Tests (25/25)** — `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_narrative_analyst.py -q`
| Plan §6 test | Implementation |
|---|---|
| Payload schema | `test_payload_schema_validation` (numbers-without-plot rejected) |
| Baseline values + plot (×5) | `test_baseline_tool_returns_values_and_plot` |
| **Metrics-in-plot** (×5) | `test_metrics_rendered_inside_plot` (asserts headline metric string is a drawn text artifact) |
| Standard routing | `test_router_routes_seasonality_without_synthesizer`, `test_parse_oblast_picks_specific_name` |
| **Read-only-FS safety** | `test_router_flags_destructive_requests` (×3), `test_safety_request_returns_refusal_not_crash`, `test_readonly_dir_blocks_writes` |
| Determinism / anti-hallucination | `test_determinism_anti_hallucination` (quotes 0.042 & 15.3, invents nothing) |
| Container / sandbox security | `test_ast_validator_blocks_malicious_code`, `test_ast_validator_allows_clean_fragment`, `test_sandbox_timeout_kills_runaway` |
| Dynamic-generation E2E | `test_dynamic_generation_end_to_end` (stub LLM → validated → sandboxed → payload with plot+numbers) |
| Dynamic safety | `test_dynamic_generation_rejects_unsafe_code` (malicious body → refusal, no crash) |
| LangGraph wiring | `test_langgraph_runs_baseline_end_to_end` |

**Manual verification**
- `server.py selftest` → 6 tools registered.
- `ask_analyst("Run an ADF stationarity test for Kharkiv")` → `test_stationarity`, 52 KB plot,
  `adf_pvalue=0.0`, narrative quotes the exact stats.
- Rendered samples reviewed visually: baseline `analyze_distribution` (Odesa·wind_speed —
  regime=multiplicative, full metric box) and the dynamic tool (`rolling_mean = 766.4` on the image).

---

## ⚠️ Failed / Blocked (bypassed)

- **None bypassed.** One bug surfaced and was fixed within the loop: the subprocess runner template was
  built with `str.format`, which collided with the literal `{}` in the runner body (`KeyError: 'k'`).
  Fixed by switching to a `__REPO_SRC__` placeholder `.replace()` (brace-safe). All 25 tests green after.

---

## ⏳ Pending / Waited (deferred to a later phase)

- **Production frontend** (Dash/Plotly surface, plans/02 Stage 5) — out of scope here per owner; the
  agent core + output contract are fixed so the UI plugs in later.
- **Live Ollama dynamic synthesis** — `_ollama_code_generator` is implemented but not exercised in tests
  (they inject a deterministic stub). End-to-end LLM codegen needs a running host Ollama + pulled model.
- **Tool *promotion*** to a persistent `dynamic_tools/` registry (plans/07 §4.4) — only **ephemeral
  one-shot** execution is built; promotion + optional human approval are deferred (by design, safer default).
- **Container `up`-verification** — `Dockerfile`/`docker-compose.yml` authored and reviewed but not yet
  built/run here (Docker not invoked in the test loop).
- **Model-narration tool** — reading the read-only `artifacts/` bundle to narrate calibrated A3T-GCN
  probabilities (the `:ro` artifacts mount exists; a dedicated tool is not built yet).
- **Text-to-SQL / Postgres read replica** — explicitly out of scope (parquet+artifacts only, owner
  decision); the tool-interface boundary leaves room to add it later without redesign.

---

## 🔧 Unresolved Issues (placeholders / env / edge cases)

- **Hardcoded absolute paths** in `MCP/Narrative_Analyst/mcp_config.json`
  (`/Users/annanechytailenko/...`) — same pattern as the OSINT config; must be templated per machine.
- **`OLLAMA_BASE_URL`** = `http://localhost:11434` locally / `http://host.docker.internal:11434` in the
  container. Real model availability is **not** verified — if Ollama is down, dynamic synthesis returns a
  graceful `dynamic_tool_unavailable` (no fabrication), but no live codegen happens.
- **`settings.llm_model`** default `llama3.1:8b`; `.env` may hold an external name (e.g. `claude-*`). The
  analyst's `_ollama_code_generator` uses it **directly** (unlike the OSINT agent's `resolve_ollama_model()`)
  → a non-local name would fail and fall back to "unavailable". TODO: reuse local-model resolution.
- **`RLIMIT_AS`** is not enforced on macOS (raises/ignored) — wall-time timeout + `RLIMIT_CPU` still apply;
  hard memory capping is the container's `mem_limit` in production.
- **Safety routing is heuristic** (destructive-verb + data-noun regex). A benign prompt mixing both
  (e.g. "why did alerts drop across the records") could false-positive into a refusal. Acceptable; flagged.
- **`analyze_distribution` regime verdict** is a heuristic (per-month mean↔std corr > 0.4), descriptive —
  not a formal multiplicative-vs-additive hypothesis test.
- **Read-only-FS enforcement** is verified at the **code layer** (AST blocks `open(...,'w')`/`os`/`shutil`;
  destructive NL → refusal) plus an OS-permission unit test; true `:ro` **mount** enforcement is a
  container-runtime guarantee, not exercised by unit tests.
- **Default "alerts" series** = `self_alert_active` (contemporaneous alert state at `t`), not the lead
  targets `y_lead_1..6`. Documented choice; a future flag could let the user pick the horizon series.

---

## Run Cheat Sheet (from repo root)

```bash
export PYTHONPATH=src

# tests (deterministic; no network / no Ollama needed — dynamic synth uses a stub)
./.venv/bin/python -m pytest tests/test_narrative_analyst.py -q          # 25 passed

# MCP server
./.venv/bin/python MCP/Narrative_Analyst/server.py selftest              # lists 6 tools
claude mcp add airraid-analyst --scope local \
  --env PYTHONPATH=$PWD/src --env AIRRAID_EXPORTS_DIR=$PWD/data/exports \
  -- $PWD/.venv/bin/python $PWD/MCP/Narrative_Analyst/server.py

# one-shot programmatic use
./.venv/bin/python -c "from airraid.analyst import NarrativeAnalyst as A; \
  print(A().answer('seasonality of alerts in Kyiv').tool_used)"          # analyze_seasonality

# containerized (read-only data + artifacts, host Ollama)
docker compose -f MCP/Narrative_Analyst/docker-compose.yml up --build
```

**Dependencies added this phase:** `statsmodels 0.14.6`, `seaborn 0.13.2`, `langgraph` (+ `matplotlib`
from the eval phase). `mcp`, `pandas`, `numpy`, `pyarrow`, `pydantic` already present.

**Next phase (resume point):** (a) wire the agent behind the FastAPI/Dash frontend (plans/02 Stage 5);
(b) exercise live Ollama codegen + add local-model resolution; (c) build/run the container and verify the
`:ro` mounts end-to-end; (d) add the `artifacts/` model-narration tool.
