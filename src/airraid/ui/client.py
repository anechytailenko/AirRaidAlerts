"""The frontend's client for the Narrative Analyst Agent (plans/08 §3).

Two interchangeable implementations behind one `.ask()` method:
  • `LocalAnalystClient`  — calls `NarrativeAnalyst` in-process (zero-config default; the test path).
  • `HttpAnalystClient`   — POSTs to the FastAPI `/analyst/ask` boundary (production; set ANALYST_API_URL).
Both return the `AnalystResponse` as a plain dict.
"""
from __future__ import annotations

import os
from typing import Protocol


class AnalystClient(Protocol):
    def ask(self, prompt: str, oblast: str | None = None, column: str | None = None) -> dict: ...


class LocalAnalystClient:
    """In-process agent — no server needed."""

    def __init__(self) -> None:
        from ..analyst import NarrativeAnalyst
        self._agent = NarrativeAnalyst()

    def ask(self, prompt: str, oblast: str | None = None, column: str | None = None) -> dict:
        return self._agent.answer(prompt, oblast=oblast, column=column).model_dump()


class HttpAnalystClient:
    """Talks to `POST {base_url}/analyst/ask` (the FastAPI wrapper of the agent)."""

    def __init__(self, base_url: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def ask(self, prompt: str, oblast: str | None = None, column: str | None = None) -> dict:
        import requests
        r = requests.post(f"{self.base_url}/analyst/ask",
                          json={"prompt": prompt, "oblast": oblast, "column": column},
                          timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def get_client() -> AnalystClient:
    """HTTP client when `ANALYST_API_URL` is set, else the in-process client."""
    url = os.environ.get("ANALYST_API_URL")
    return HttpAnalystClient(url) if url else LocalAnalystClient()
