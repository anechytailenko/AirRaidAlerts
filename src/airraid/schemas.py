"""Pydantic v2 contracts — the validation gate before any DB write."""
from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from .models import AlertType, Source


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
