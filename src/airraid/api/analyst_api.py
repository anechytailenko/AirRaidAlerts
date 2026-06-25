"""FastAPI wrapper of the Narrative Analyst — the production boundary the frontend calls (plans/08 §3).

Pydantic-native (the response model IS `AnalystResponse` from `schemas.py`). Read-only: it only runs the
agent, which never mutates the data.

Run:  PYTHONPATH=src ./.venv/bin/uvicorn airraid.api.analyst_api:api --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from ..analyst import NarrativeAnalyst
from ..schemas import AnalystResponse

api = FastAPI(title="Narrative Analyst API", version="1.0")
_analyst = NarrativeAnalyst()


class AskRequest(BaseModel):
    prompt: str
    oblast: str | None = None
    column: str | None = None


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "narrative-analyst"}


@api.post("/analyst/ask", response_model=AnalystResponse)
def ask(req: AskRequest) -> AnalystResponse:
    return _analyst.answer(req.prompt, oblast=req.oblast, column=req.column)
