"""Narrative Analyst Agent — orchestrator core (plans/07 §1, §5).

`NarrativeAnalyst` is the importable, unit-tested cognition layer: it routes a request, runs the
authoritative `airraid.eda` tools (or synthesizes one in the sandbox), narrates the EXACT numbers,
and returns a Pydantic-validated `AnalystResponse`. The MCP server and the LangGraph graph both wrap
this single class (DRY).
"""
from __future__ import annotations

from ..schemas import AnalystResponse
from .agent import SYSTEM_PROMPT, NarrativeAnalyst

__all__ = ["NarrativeAnalyst", "AnalystResponse", "SYSTEM_PROMPT"]
