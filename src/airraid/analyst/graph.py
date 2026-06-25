"""LangGraph state graph for the Narrative Analyst (plans/07 §5 Phase 1).

Nodes: router → {baseline | dynamic | safety} → validate → END. Each node delegates to the
`NarrativeAnalyst` methods (DRY); the `validate` node re-checks the payload against the Pydantic
contract before it is returned, so every graph output is schema-valid (plans/02 principle).
"""
from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from ..schemas import AnalystResponse
from .agent import NarrativeAnalyst


class AnalystState(TypedDict, total=False):
    prompt: str
    oblast: Optional[str]
    column: Optional[str]
    route: str
    response: dict


def build_graph(analyst: NarrativeAnalyst):
    g = StateGraph(AnalystState)

    def router(state: AnalystState) -> dict:
        return {"route": analyst.route(state["prompt"])}

    def baseline(state: AnalystState) -> dict:
        r = analyst.baseline_response(state["prompt"], state.get("oblast"),
                                      state.get("column"), tool=state["route"])
        return {"response": r.model_dump()}

    def dynamic(state: AnalystState) -> dict:
        r = analyst.dynamic_response(state["prompt"], state.get("oblast"), state.get("column"))
        return {"response": r.model_dump()}

    def safety(state: AnalystState) -> dict:
        return {"response": analyst.safety_response(state["prompt"]).model_dump()}

    def validate(state: AnalystState) -> dict:
        AnalystResponse(**state["response"])  # raises if the payload drifted from the contract
        return {}

    for name, fn in (("router", router), ("baseline", baseline),
                     ("dynamic", dynamic), ("safety", safety), ("validate", validate)):
        g.add_node(name, fn)
    g.set_entry_point("router")
    g.add_conditional_edges(
        "router",
        lambda s: s["route"] if s["route"] in ("dynamic", "safety") else "baseline",
        {"baseline": "baseline", "dynamic": "dynamic", "safety": "safety"},
    )
    for n in ("baseline", "dynamic", "safety"):
        g.add_edge(n, "validate")
    g.add_edge("validate", END)
    return g.compile()


def run(compiled_graph, prompt: str, oblast=None, column=None) -> AnalystResponse:
    out = compiled_graph.invoke({"prompt": prompt, "oblast": oblast, "column": column})
    return AnalystResponse(**out["response"])
