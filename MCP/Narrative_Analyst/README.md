# Narrative Analyst Agent (MCP + LangGraph)

The project's flagship analytical agent — see [`plans/07-narrative-analyst-agent.md`](../../plans/07-narrative-analyst-agent.md)
for the full spec. It turns the deterministic ML pipeline into **decision-grade narrative + visual
evidence**, and is **dual-purpose**: an MCP server dev agents call to understand data distributions,
and a natural-language interface for on-demand analytics.

## What it guarantees
- **Read-only & no hallucinated numbers.** Every figure comes from executed Python over the read-only
  parquet export; the narrator only quotes numbers a tool actually produced.
- **Metrics inside the plot.** Every analytical plot renders its key metrics *on the image* (title +
  in-axes text box) — the frontend has no numbers-only pane (plans/07 §2, `scripts/evaluate_horizons.py`
  precedent).
- **Self-extending, safely.** Unknown requests are answered by synthesizing a new tool with the local
  LLM, then **AST-validating** and running it in a **constrained subprocess** inside a **read-only
  container** (plans/07 §4).

## Layout (logic lives in `src/`, this dir is the thin entrypoint)
| Path | Role |
|---|---|
| `src/airraid/eda/{data,plots,stats,sandbox}.py` | authoritative read-only stats + plot helpers + the security sandbox |
| `src/airraid/analyst/{agent,graph}.py` | `NarrativeAnalyst` (router/narrator/synthesizer) + the LangGraph wiring |
| `src/airraid/schemas.py::AnalystResponse` | the standardized payload contract |
| `MCP/Narrative_Analyst/server.py` | FastMCP stdio server exposing the 5 baseline tools + `ask_analyst` |
| `Dockerfile` · `docker-compose.yml` | the isolated, read-only container |

## Tools
1. `analyze_seasonality` · 2. `plot_acf_pacf` · 3. `test_stationarity` ·
4. `get_summary_statistics` · 5. `analyze_distribution` — plus `ask_analyst(prompt, oblast, column)`
(NL entrypoint that routes to a baseline tool or synthesizes one).

## Run

```bash
# 1. Smoke-test the server (lists tools, exits)
PYTHONPATH=src ./.venv/bin/python MCP/Narrative_Analyst/server.py selftest

# 2. Register with Claude Code (stdio)
claude mcp add airraid-analyst --scope local \
  --env PYTHONPATH=$PWD/src --env AIRRAID_EXPORTS_DIR=$PWD/data/exports \
  -- $PWD/.venv/bin/python $PWD/MCP/Narrative_Analyst/server.py

# 3. Run the tests
PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_narrative_analyst.py -q

# 4. Containerized (read-only data + artifacts, host Ollama)
docker compose -f MCP/Narrative_Analyst/docker-compose.yml up --build
```

## Dynamic tool contract
The synthesizer LLM writes a **fragment** (no imports). It is handed `df` (time-indexed numeric
features for the oblast), `pd, np, plt, sns, load(column, oblast)`, and statsmodels
`acf,pacf,adfuller,kpss,seasonal_decompose`. It must assign `test_result` (a dict of exact numbers)
and build a `fig` that draws those numbers on the image. The fragment is AST-allow-list-validated and
executed in a subprocess with a wall-time timeout + CPU/memory rlimits and a minimal `__builtins__`.

## Local LLM (Ollama)
Ollama stays on the **host**. Locally it is reached at `http://localhost:11434`; in the container at
`http://host.docker.internal:11434` (`OLLAMA_BASE_URL`), reusing `airraid.config.settings`. Tests inject
a stub generator, so they need **no** network or Ollama.
