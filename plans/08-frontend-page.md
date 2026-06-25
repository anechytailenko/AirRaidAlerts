# 08 — Frontend Page (Analysis tab, Narrative Analyst client)

**Purpose.** Specify and build the **interactive Analysis page** — the production face of the
[Narrative Analyst Agent](./07-narrative-analyst-agent.md). The user asks a question in a chat box; the
agent returns a standardized `AnalystResponse` (`description`, `test_result`, `plot_image`); the page
renders the **plot on the left** and the **narrative + metrics on the right**.

Hard constraints carried from [`02-general-workflow-architecture.md`](./02-general-workflow-architecture.md):
**solely Python**, **Dash + Plotly** for the UI (Stage 5), **Pydantic** as the data contract
(`AnalystResponse` from `src/airraid/schemas.py`).

---

## 1. Reference design & required changes

Baseline: [`demo/web_01.png`](../demo/web_01.png) — a header with **Analysis / Prediction** tabs, a row of
KPI cards, a grid of plots, and a right-hand "Analytics Assistant" chat. We adapt it:

| Element in `web_01` | Action |
|---|---|
| Header + **Analysis / Prediction** tabs | **Keep.** Analysis is active; Prediction is a stub (out of scope). |
| Top row of **KPI cards** (alert hours, base rate, longest alert, peak month) | **REMOVE entirely** — no standalone numbers-only windows (numbers now live *inside* the agent's plot, plans/07 §2). |
| Static plot grid (2022–2025) | **Replace** with a single **agent-driven visual panel** (left). |
| Right-hand chat | **Keep & wire** to the Narrative Analyst. |

**Scope:** only the **Analysis** tab. The **Prediction** tab renders a "coming soon" placeholder.

---

## 2. Layout — two columns

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Ukraine Air-Raid Alert Intelligence System      [Analysis] [Prediction]   │  header + tabs
├──────────────────────────────────────────┬────────────────────────────────┤
│  LEFT — VISUALS (≈ 62%)                   │  RIGHT — CHAT (≈ 38%)          │
│                                            │  Narrative Analyst              │
│   ┌──────────────────────────────────┐    │  ┌──────────────────────────┐   │
│   │                                  │    │  │ assistant: …description… │   │
│   │   agent plot_image (base64 PNG)  │    │  │   metrics: k = v …       │   │
│   │   <html.Img>                     │    │  │ user: …query…            │   │
│   │                                  │    │  └──────────────────────────┘   │
│   └──────────────────────────────────┘    │  [suggestion chips]             │
│   caption: tool_used · oblast · column     │  [ Ask about the data…  ▸ ]    │
└──────────────────────────────────────────┴────────────────────────────────┘
```

- **Left (visuals).** A single `html.Img` whose `src` is `data:image/png;base64,<plot_image>`, plus a
  caption (`tool_used`) and an empty-state placeholder before the first answer. Dedicated **entirely** to
  the agent's plots.
- **Right (chat).** Scrollable message list (assistant + user bubbles), a row of **suggestion chips**
  ("Seasonality of alerts in Kyiv", "Is the Kharkiv series stationary?", "Distribution of wind speed"),
  and the input row (`dcc.Input` + Send) with a `dcc.Loading` spinner while the agent works.

---

## 3. Backend integration — frontend is the agent's client

Data path (solely Python, matches `02` Stage 4/5):

```
Dash callback ──► AnalystClient.ask(prompt, oblast, column)
                      │
            ┌─────────┴───────────────────────────────┐
            │ HttpAnalystClient  (POST /analyst/ask)   │  ← production: FastAPI wraps the agent
            │ LocalAnalystClient (in-process call)     │  ← default/dev & tests: no server needed
            └─────────┬───────────────────────────────┘
                      ▼
            airraid.analyst.NarrativeAnalyst.answer(...) ──► AnalystResponse (Pydantic)
```

- **`src/airraid/api/analyst_api.py`** — minimal **FastAPI** app: `POST /analyst/ask`
  `{prompt, oblast?, column?}` → `AnalystResponse` JSON (+ `GET /health`). This is the production boundary
  ("frontend acts as the client for the agent").
- **`src/airraid/ui/client.py`** — `AnalystClient` protocol with two impls: `HttpAnalystClient(base_url)`
  (uses `requests`, selected when `ANALYST_API_URL` is set) and `LocalAnalystClient()` (calls the agent
  in-process; the zero-config default and the test path). `get_client()` factory picks by env.

### Data-flow mapping (the core rule)
The agent returns `AnalystResponse {description, test_result, plot_image, tool_used, is_dynamic_tool}`:
- **`description` + `test_result` → RIGHT (chat reply).** The assistant bubble shows the narrative, then a
  compact **metrics block** rendered from `test_result` (`key = value` lines).
- **`plot_image` → LEFT (visual panel).** Base64 PNG decoded into `html.Img(src="data:image/png;base64,…")`.
- A `safety_refusal` / clarification answer (no `plot_image`) shows only the chat reply; the left panel
  keeps its previous image / placeholder.

---

## 4. Files

| Path | Role |
|---|---|
| `src/airraid/ui/render.py` | **pure** functions: `chat_reply_markdown(payload)`, `format_metrics(test_result)`, `image_src(payload)` — unit-tested against a mock payload |
| `src/airraid/ui/client.py` | `AnalystClient` (`Http*` / `Local*`) + `get_client()` |
| `src/airraid/ui/layout.py` | header, tabs, the two-column Analysis layout, `dcc.Store` for chat history, suggestion chips |
| `src/airraid/ui/app.py` | Dash `app`, callbacks (submit → client → render → outputs), `main()` runner |
| `src/airraid/api/analyst_api.py` | FastAPI `POST /analyst/ask` + `GET /health` |
| `tests/test_frontend.py` | parses a **mock `AnalystResponse`** through the render layer + client roundtrip + app builds |

Keeping the **render functions pure** (payload dict → outputs) is what makes the data-flow rules testable
without a browser: the callback is a thin wire from input → client → render → `(image_src, chat_children)`.

---

## 5. Async handling & state
- **State** lives in a `dcc.Store` (`chat-history`: list of `{role, text}`) and a `dcc.Store`
  (`last-image`). Callbacks append the user turn, call the client, append the assistant turn, and set the
  image.
- **Async feel:** wrap the chat list + image in `dcc.Loading` so the spinner shows during the
  (blocking) `requests`/in-process call. A future upgrade to Dash **background callbacks**
  (`DiskcacheManager`) is noted but not required for this phase.
- **Robustness:** the callback never raises into the UI — client/agent errors become an assistant
  message ("the analyst could not complete that…"), so a bad query degrades gracefully.

---

## 6. Testing plan (Task 2 acceptance — "parses a mock payload matching the agent's schema")
1. **Mock matches schema** — the test fixture payload validates against `AnalystResponse`.
2. **Chat rendering** — `chat_reply_markdown(mock)` contains the `description` and every
   `test_result` `key = value`.
3. **Image decoding** — `image_src(mock)` returns `data:image/png;base64,…` and the base64 decodes to real
   PNG bytes (PNG magic header); `image_src` returns `None` when `plot_image` is absent (safety turn).
4. **Client roundtrip** — `LocalAnalystClient().ask("seasonality of alerts in Kyiv")` returns a dict with
   `tool_used == "analyze_seasonality"`, a `plot_image`, and a `test_result` (end-to-end through the agent).
5. **App builds** — importing `app` constructs the Dash layout without error; the **KPI-card labels are
   absent** and both the left image container and the right chat input exist.

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_frontend.py -q`.

---

## 7. Out of scope / deferred
- **Prediction tab** (the choropleth + lead-time scrubber of `02` Stage 5) — placeholder only.
- Oblast GeoJSON map, authentication, multi-user sessions, streaming tokens, persistent chat history.
- True background callbacks / websockets — `dcc.Loading` is sufficient now.

*Cross-references:* [`07-narrative-analyst-agent.md`](./07-narrative-analyst-agent.md) (the agent + payload
contract), [`02-general-workflow-architecture.md`](./02-general-workflow-architecture.md) (Dash+Plotly /
FastAPI / solely-Python mandate), `src/airraid/schemas.py::AnalystResponse`.



PYTHONPATH=src ./.venv/bin/python -m airraid.ui.app          # → http://127.0.0.1:8050 (agent in-process)
# optional production split:
PYTHONPATH=src ./.venv/bin/uvicorn airraid.api.analyst_api:api --port 8000
ANALYST_API_URL=http://127.0.0.1:8000 PYTHONPATH=src ./.venv/bin/python -m airraid.ui.app