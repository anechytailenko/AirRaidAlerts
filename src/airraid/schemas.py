"""Pydantic v2 contracts — the validation gate before any DB write."""
from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from .models import AlertType, Source


class AnalystResponse(BaseModel):
    """Standardized payload of the Narrative Analyst Agent (plans/07 §2).

    `description` is ALWAYS present. For any analytical/statistical answer, BOTH `plot_image` and
    `test_result` are required and their numbers must agree with the narrative; only pure
    clarification / greeting / safety-refusal turns may omit them. The key metrics are rendered
    *inside* the plot image (plans/07 §2 — the frontend has no numbers-only pane).
    """
    model_config = ConfigDict(extra="forbid")

    description: str
    plot_image: str | None = None      # base64 PNG (metrics are drawn ON the image)
    test_result: dict | None = None    # exact numbers: p-values, statistics, metrics
    tool_used: str
    is_dynamic_tool: bool = False

    @model_validator(mode="after")
    def _analytical_completeness(self) -> "AnalystResponse":
        # an answer that carries numbers MUST also carry the plot those numbers are drawn on
        if self.test_result is not None and self.plot_image is None:
            raise ValueError("analytical answer with `test_result` must also include a `plot_image`")
        return self


class RawAlertEvent(BaseModel):
    """A validated alert interval. tz-aware datetimes are enforced by AwareDatetime."""
    model_config = ConfigDict(extra="forbid")

    oblast_id: int
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    alert_type: AlertType = AlertType.air_raid
    source: Source
    is_naive: bool = False
    external_id: str | None = None

    @model_validator(mode="after")
    def _interval(self) -> "RawAlertEvent":
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError("ended_at must be > started_at")
        return self
