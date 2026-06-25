# 07 — Narrative Analyst Agent (LangGraph + MCP)

**Purpose.** This document specifies the project's flagship feature — the **Narrative Analyst Agent** —
the interactive, self-extending analytical layer that turns the deterministic ML pipeline into
**decision-grade narrative + visual evidence**. It refines and supersedes the "forward-looking, not built
now" sketch of **Use Case B** in [`02-general-workflow-architecture.md`](./02-general-workflow-architecture.md)
(§ *Reporting / Stage 5: narrative "analyst" layer*), which is now **elevated into this full agent**.

This is a **design document**. It reuses authoritative, version-controlled Python (it does not duplicate
statistics into the LLM), stays **read-only at the deterministic boundary** (`02` Global Principles), and
remains **solely Python** end to end (`02` hard constraint #1) with **Pydantic v2 as the data contract**
(`02` hard constraint #2).

---

## 0. Context & Rationale — why we are building this

### The Problem
Predicting hourly binary air-raid occurrence across a **1–6 h** horizon requires strict time-series
distributional validation — **stationarity** (ADF/KPSS), **additive vs multiplicative regime changes**,
**autocorrelation structure** (ACF/PACF), seasonality, and base-rate drift. In early work this was done
by *manually prompting a single LLM* to write → execute → verify these statistical scripts. That created:
- a **human-in-the-loop bottleneck** (every analysis needed hand-holding),
- **chat-history bloat** that degraded model performance as transcripts grew, and
- **"analysis paralysis"** — aimlessly profiling features without advancing the ML goal.

### The Insight
**"Value" is subjective.** An *AI coding assistant* needs specific internal data distributions to make
**architecture decisions** (e.g. "is the alert series stationary per oblast? what lags matter?"), while an
*end-user* seeks completely different **behavioral trends** ("when are alerts most likely this week?").
A single tool must serve **both** audiences without rework.

### The Solution — a dual-purpose Narrative Analyst Agent
1. **For development (MCP mode):** an **MCP server** that dev agents (e.g. Claude Code, exactly like the
   existing [`MCP/OSINT_agent`](../MCP/OSINT_agent/README.md)) call on-demand to **understand the
   underlying data distributions** while making modeling decisions.
2. **For production (interactive mode):** a **natural-language interface** for end-users to run **on-demand
   analytics** over the same authoritative data.

Same deterministic core, **two entrypoints** (see §1, §5).

### Output rule (critical)
Every analytical answer returns a **Description**, exact **Metrics**, and a **Plot**. **The key numerical
metrics MUST be rendered *inside* the generated plot image itself.** The frontend that displays these
answers is intentionally simpler than [`demo/web_01.png`](../demo/web_01.png) /
[`demo/web_02.png`](../demo/web_02.png) — it has **no numbers-only display panes** — so the plot is the
*only* surface carrying the metrics. A plot without its numbers is an incomplete answer. (This is already
demonstrated in the repo: [`scripts/evaluate_horizons.py`](../scripts/evaluate_horizons.py) renders PR-AUC
/ F1 / ROC-AUC inside each subplot title and an in-axes text box.)

---

## 1. Architecture & Justification

The Narrative Analyst Agent uses a **Dynamic MCP-Tool Architecture orchestrated by LangGraph**.

- **Separation of concerns.** **LangGraph** handles *cognition* — understanding the request, routing,
  validating, and formatting the output. The **MCP server** handles *execution* — running deterministic
  Python over the data and returning exact numbers + a plot. The LLM never does arithmetic; it orchestrates
  *which* analysis runs and *how* to narrate it.
- **Self-extending capability.** If a user asks for a bespoke metric with no matching tool (e.g.
  *"bivariate distribution of `wind_speed` vs `osint_tu95_takeoff`"*), the agent does not fail: a **local
  LLM** writes a new Python tool against the standard tool interface, the tool is **validated, sandboxed,
  and executed**, and LangGraph proceeds with its exact output (§3, §4, §5 Phase 3).
- **Strict determinism (clarified).** The agent is **read-only** and **never fabricates numbers** — every
  figure in the narrative comes from executed Python over the frozen read-only replica. Note the nuance:
  code *generation* is inherently non-deterministic, but code *execution is deterministic* (same code +
  same frozen data → same numbers), code-gen runs at **temperature 0**, and a number is only ever quoted
  *after* it is produced by an executed, validated tool. This **preserves** `02`'s deterministic-core
  guarantee: the agent lives at the **reporting edge** and never touches the
  `features → train → CV → inference` core.

**Two consumption modes, one core:**
| Mode | Consumer | Transport | Purpose |
|---|---|---|---|
| **Dev / MCP** | Claude Code & dev agents | MCP stdio (mirrors `MCP/OSINT_agent/server.py`) | understand data distributions for architecture decisions |
| **Production** | End-users | LangGraph agent behind FastAPI/Dash (`02` Stages 4–5) | on-demand NL analytics |

**Placement (consistent with the repo).** The MCP server lives at `MCP/Narrative_Analyst/`
(`server.py`, `agent.py`, `graph.py`, `mcp_config.json`, `README.md`) — mirroring `MCP/OSINT_agent/`.
The **authoritative deterministic statistics + plot helpers** live in a new `src/airraid/eda/` package
(unit-tested in isolation), and the **payload models** go in the existing `src/airraid/schemas.py`. The
server stays *thin* — it wraps `src/airraid/eda/`, it does not re-implement statistics (DRY; `02` MCP-ready
principle).

---

## 2. Standardized Output Payload

Every response conforms to a Pydantic v2 model `AnalystResponse` (defined in `src/airraid/schemas.py`),
validated before it leaves the agent:

```python
class AnalystResponse(BaseModel):
    description: str                      # ALWAYS present — the narrative
    plot_image: str | None = None        # base64 PNG (or file path); REQUIRED for analytical answers
    test_result: dict | None = None      # exact numbers: p-values, statistics, metrics; REQUIRED for analytical answers
    tool_used: str                       # which MCP tool ran (audit/provenance)
    is_dynamic_tool: bool = False        # True if served by a synthesized tool
```

1. **`description` (always):** a natural-language narrative summarizing the findings, calibrated
   probabilities, or historical insights — **quoting the exact numbers** returned by the tool.
2. **`plot_image` (mandatory for analytical answers):** a base64-encoded PNG (or file path) from
   matplotlib/seaborn. **Only** pure clarification/greeting turns may omit it.
3. **`test_result` (mandatory for analytical answers):** a JSON object of exact numerical outputs
   (p-values, test statistics, model metrics). Same omission rule as `plot_image`.

> **The "always return Description + Metrics + Plot" rule:** for **any** analytical/statistical request,
> `description`, `plot_image`, **and** `test_result` are **all required and must agree** (the narrative's
> numbers == `test_result` == the numbers printed on the plot). The agent may drop `plot_image` /
> `test_result` *only* for non-analytical turns (a greeting, a clarification question).

### CRITICAL system-prompt rule — metrics live *inside* the plot
The agent's system prompt MUST enforce, verbatim:

> **"Every plot you produce MUST render the key numerical metrics directly inside the image** — as the
> title, an annotation, or an in-axes text box — **alongside clear legends and axis labels.** The frontend
> has no separate numbers pane; if a metric is not drawn on the plot, the user will never see it. A plot
> that omits its metrics is an invalid answer and must be regenerated."

This rule is enforced in **three** places: (a) the system prompt above, (b) the payload contract (analytical
answers must carry `test_result` whose values appear on the image), and (c) an automated test (§6.6).
Plot helpers reuse the convention already proven in
[`scripts/evaluate_horizons.py`](../scripts/evaluate_horizons.py) (metric in the title + an in-axes text
box, headless `matplotlib.use("Agg")`).

---

## 3. Core MCP Tools (pre-built baseline — **5** tools)

The server ships with **five** foundational tools that cover ~80% of standard requests with **no** dynamic
generation. Each tool **wraps an authoritative function in `src/airraid/eda/`** (version-controlled,
unit-tested), returns **exact values** + a **base64 plot with the metrics drawn on it**, and reads only the
read-only parquet replica (§4).

1. **`analyze_seasonality`** — decomposes a series (e.g. alerts for an oblast) into trend / seasonal /
   residual (statsmodels STL/`seasonal_decompose`).
   *Returns:* a decomposition plot (peak-hour/day annotated **on the figure**) + peak-hour metrics.
2. **`plot_acf_pacf`** — Autocorrelation & Partial-Autocorrelation of the target, to identify
   autoregressive lags.
   *Returns:* ACF/PACF plot with significance bands + **significant-lag indices labeled on the figure**.
3. **`test_stationarity`** — Augmented Dickey-Fuller (and KPSS as complement, per `02` Stage 2) on a
   specified series.
   *Returns:* ADF statistic, p-value, critical values — **printed in the plot's text box** over the series.
4. **`get_summary_statistics`** — mean, median, variance, percentiles for a feature across a time window.
   *Returns:* exact JSON **and** a small stats-table/box rendered as an image (numbers on the figure).
5. **`analyze_distribution`** *(the 5th tool — directly serves §0's "additive vs multiplicative changes")* —
   histogram/KDE of a feature with an **additive-vs-multiplicative regime check** (log / variance-
   stabilizing transform comparison) and **base-rate / mean drift across periods**.
   *Returns:* distribution plot with the transform verdict + drift metrics **annotated on the image**.

> Feature/column names for these tools come from
> [`data/exports/data_dictionary.md`](../data/exports/data_dictionary.md) (e.g. `y_alert_active`,
> `self_alert_active`, `neighbor_alert_frac`, `temp_c`, `wind_speed`, `osint_tu95_takeoff`,
> `hours_since_mig31`).

---

## 4. Security & Containerization (mandatory)

The dynamic code generator (§5 Phase 3) executes **LLM-written Python**. This is the headline risk and is
contained by **defense in depth**.

### 4.1 Container isolation (the owner constraint)
The agent runs in an **isolated Docker container** with **duplicated, read-only copies** of the data and
model so generated code **physically cannot delete or corrupt** the real training data or weights:
- `data/exports/*.parquet` and `artifacts/` are bind-mounted **`:ro`** (or copied into the image) — the
  process literally cannot write them. **No Postgres in the container** (owner decision; data access is
  parquet + artifacts only).
- Runs as a **non-root** user; **no network egress** except to the host Ollama endpoint; **CPU / memory /
  wall-time `ulimit`s**; a **`tmpfs` scratch** dir is the *only* writable location (for the output PNG).

### 4.2 Static validation before any execution
Generated code passes an **AST allow-list** validator first — reject on:
`import os|sys|subprocess|socket|shutil|requests` (and other I/O/net modules), `open(...)` in write/append
mode, `eval` / `exec` / `__import__`, and dunder-attribute access. Only a curated import set
(`pandas`, `numpy`, `statsmodels`, `matplotlib`, `seaborn`, the `src/airraid/eda` helpers) is permitted.

### 4.3 Sandboxed execution
Validated code runs in a **constrained subprocess** (its own timeout + memory cap), **never in the server
process**. It may **read** the read-only replicas and **write only** the scratch PNG.

### 4.4 Ephemeral vs promoted tools — no blind hot-reload
- **Default = ephemeral one-shot:** the synthesized tool runs once for this request, then is discarded.
- **Promotion** of a synthesized tool into a **persistent** registered tool (`dynamic_tools/`) is a
  separate, gated step (must pass AST validation **and** a smoke run; optionally a human approval), so the
  server never blindly imports unsanitized code.

### 4.5 Ollama networking (resolves the draft's open question)
**Ollama stays on the host**, not in the container. The container reaches it through the existing
`airraid.config.settings.ollama_base_url` (already used by `MCP/OSINT_agent/agent.py`), overridden per
environment: `OLLAMA_BASE_URL=http://host.docker.internal:11434` on macOS/Windows, or
`--add-host=host.docker.internal:host-gateway` on Linux. Model resolution reuses `resolve_ollama_model()`.

---

## 5. Execution Roadmap

### Phase 1 — LangGraph Orchestrator
- Define the **State** schema: `messages`, `current_tool`, `generated_code`, `tool_result`,
  `final_payload: AnalystResponse`, `safety_flag`.
- **Router node:** evaluate the prompt against the registered MCP tools → route to a baseline tool, the
  synthesizer, or a safety refusal.
- Add a **validation node** (Pydantic-validate `final_payload` before return) and a **safety / refusal
  node** (graceful narrative when a request is blocked) — every output is Pydantic-validated (`02`).

### Phase 2 — Containerized MCP Server (over read-only replicas)
- Mirror `MCP/OSINT_agent/server.py`: `FastMCP("airraid-analyst")`, `@mcp.tool()` per baseline tool,
  `sys.path` bootstrap to import `airraid` from `src/`, a `selftest` entrypoint.
- Implement & test the **5** baseline tools (§3) — each returns exact values **and** a base64 image with
  the metrics drawn on it.
- Build the container per §4 (read-only parquet + artifacts, non-root, ulimits, tmpfs scratch, Ollama via
  host). Keep the MCP port/stdio open for the LangGraph client.

### Phase 3 — Dynamic Tool Synthesizer ("write code" node)
- **Trigger:** router finds no existing tool fits.
- **Process:** pass the **project/data schema** (`data_dictionary.md`) + the **standard tool template** to
  the local LLM (Ollama, temp 0) → it writes Python matching the tool interface → **AST-validate (§4.2)** →
  **sandbox-execute (§4.3)** → return the exact output + plot. Persisting to `dynamic_tools/` is the gated
  promotion step (§4.4), **off by default**.

### Phase 4 — Narration & Validation
- The **Narrator node** drafts `description`, **quoting the exact tool numbers**, and assembles
  `AnalystResponse` (`plot_image` + `test_result`).
- The **validation node** asserts the payload is well-formed and that the narrative's numbers equal
  `test_result` — then returns it.

---

## 6. Testing Plan

1. **Determinism & anti-hallucination.** Mock a tool output `{p_value: 0.042, mean_temp: 15.3}`; assert the
   narrative string contains `"0.042"` and `"15.3"` exactly and contains **no** fabricated metrics.
2. **Standard routing.** "Show me the seasonality of alerts in Kyiv" → assert LangGraph routes to
   `analyze_seasonality` **without** triggering the synthesizer.
3. **Dynamic-generation E2E.** "Rolling 7-hour median of `cloud_cover` × `wind_speed`, and plot it" → assert
   the synthesizer fires, valid Python is produced, it executes without exception in the sandbox, and the
   payload contains the expected image + description.
4. **Read-only-FS safety** *(replaces the SQL "drop table" test — no DB in scope).* Ask the agent to delete
   / overwrite a parquet or an artifact (or have generated code attempt a write) → assert the **read-only
   mount raises**, the originals are byte-for-byte untouched, and the agent returns a graceful **safety
   refusal narrative**.
5. **Container / sandbox security.** Assert the AST validator **rejects** a malicious snippet
   (`import os; os.remove(...)`), the subprocess **timeout** fires on an infinite loop, and there is **no
   network egress** except the Ollama host.
6. **Metrics-in-plot.** For each baseline tool, assert the rendered figure **actually carries its numbers**
   (inspect the figure's text/annotation objects before save — e.g. the ADF p-value string is present;
   OCR via `pytesseract` optional as a stronger check).
7. **Payload-schema.** Every returned object validates against `AnalystResponse`; analytical answers carry
   both `plot_image` and `test_result`, and their numbers agree with the narrative.

---

## 7. Consistency with `plans/01–06`

- **Edge-only / read-only / deterministic core preserved** — the agent narrates over authoritative outputs
  and **never** enters `features → train → CV → inference` (`02` Global Principles, *Deterministic core
  boundary*). The read-only container replicas make this guarantee physical.
- **Solely Python** — LangGraph, the MCP server, and the `src/airraid/eda` helpers are all Python; the
  local LLM is Ollama (`02` hard constraint #1; matches Use Case A's local-Ollama discipline).
- **Pydantic contract** — `AnalystResponse` joins the shared `src/airraid/schemas.py` models (`02` hard
  constraint #2); every agent output is Pydantic-validated and provenance-tagged (`tool_used`).
- **Reuse, not reinvention** — baseline tools wrap `src/airraid/eda/` (the same ADF/KPSS/ACF/seasonality
  lenses named in `02` Stage 2 and `04`); the agent may load `artifacts/` (read-only) to narrate calibrated
  probabilities from the trained A3T-GCN (`06`). Server structure mirrors `MCP/OSINT_agent/`.
- **Frontend deferred** — per owner, the Dash/Plotly surface (`02` Stage 5) is out of scope here; this plan
  fixes the agent core + its output contract so the UI plugs in later.

---

*Cross-references:* [`02-general-workflow-architecture.md`](./02-general-workflow-architecture.md)
(Use Case B → elevated here), [`04-analytics-eda.md`](./04-analytics-eda.md) (the statistical lenses the
baseline tools reuse), [`06-model-architecture.md`](./06-model-architecture.md) (the `artifacts/` the agent
narrates). Existing implementation precedents: [`MCP/OSINT_agent/`](../MCP/OSINT_agent/) (MCP pattern) and
[`scripts/evaluate_horizons.py`](../scripts/evaluate_horizons.py) (metrics-inside-the-plot).
