"""SQLAlchemy 2.0 models — the 5 Stage-1 tables + ingest_errors dead-letter.

Schema mirrors plans/03-data-ingestion-engineering.md §B.
"""
from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class AlertType(enum.Enum):
    air_raid = "air_raid"
    artillery = "artillery"
    urban_combat = "urban_combat"
    chemical = "chemical"
    nuclear = "nuclear"
    info = "info"


class Source(enum.Enum):
    alerts_in_ua = "alerts_in_ua"
    ukrainealarm = "ukrainealarm"
    vadimkin_official = "vadimkin_official"
    vadimkin_volunteer = "vadimkin_volunteer"
    telegram = "telegram"
    open_meteo = "open_meteo"


class Scope(enum.Enum):
    national = "national"
    oblast = "oblast"


class Oblast(Base):
    __tablename__ = "oblasts"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_uk: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    koatuu: Mapped[str | None] = mapped_column(String(12))
    centroid_lat: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    centroid_lon: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    alerts_in_ua_uid: Mapped[int | None] = mapped_column(Integer, unique=True)
    ukrainealarm_region_id: Mapped[str | None] = mapped_column(String(16))


class OblastAdjacency(Base):
    __tablename__ = "oblast_adjacency"
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    neighbor_oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    __table_args__ = (CheckConstraint("oblast_id <> neighbor_oblast_id", name="ck_adj_no_self"),)


class RawAlert(Base):
    __tablename__ = "raw_alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), nullable=False, default=AlertType.air_raid)
    source: Mapped[Source] = mapped_column(Enum(Source), nullable=False)
    is_naive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_id: Mapped[str | None] = mapped_column(String(64))
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("oblast_id", "started_at", "alert_type", "source", name="uq_raw_alert"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_alert_interval"),
        Index("ix_raw_alert_oblast_time", "oblast_id", "started_at"),
        Index("ix_raw_alert_time", "started_at"),
    )


class ExogenousFeature(Base):
    __tablename__ = "exogenous_features"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(48), nullable=False)
    scope: Mapped[Scope] = mapped_column(Enum(Scope), nullable=False)
    oblast_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("oblasts.id"))
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    value_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[Source] = mapped_column(Enum(Source), nullable=False)
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("feature_key", "event_ts", "scope", "oblast_id", "source", name="uq_exo"),
        CheckConstraint("(scope = 'national') = (oblast_id IS NULL)", name="ck_exo_scope"),
        CheckConstraint("num_nonnulls(value_bool, value_num, value_text) = 1", name="ck_exo_one_value"),
        Index("ix_exo_key_time", "feature_key", "event_ts"),
        Index("ix_exo_oblast_time", "oblast_id", "event_ts"),
    )


class HourlyPanel(Base):
    __tablename__ = "hourly_panel"
    hour_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    lead_hours: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    y_alert_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    built_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("lead_hours BETWEEN 1 AND 6", name="ck_panel_lead"),
        Index("ix_panel_time", "hour_ts"),
    )


class FeatureMatrix(Base):
    """Leak-safe model-input matrix, keyed (hour_ts, oblast_id) — every feature is known AS-OF `t`.

    Joins to `hourly_panel` on (hour_ts, oblast_id) for all 6 leads. The label lives at `t + lead`
    (strictly future) and is NEVER read here, so features cannot leak the target. Three families:
      • weather (target-oblast, contemporaneous at `t`)  • spatial alert state at `t` (self + neighbors)
      • calendar (deterministic from `hour_ts`).
    """
    __tablename__ = "feature_matrix"
    hour_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    oblast_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("oblasts.id"), primary_key=True)
    # weather as-of t (nullable: ERA5 begins 2022-02-25, so the first grid hours can be NULL)
    temp_c: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    wind_speed: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    precip_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    cloud_cover: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    # spatial alert state at t (NOT t+lead) — leak-safe autoregressive / neighbor signal
    self_alert_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    neighbor_alert_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    neighbor_alert_frac: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # calendar (deterministic from hour_ts)
    hour_of_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    dow: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hour_sin: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    hour_cos: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    dow_sin: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    dow_cos: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    built_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_fm_time", "hour_ts"),)


class IngestError(Base):
    """Dead-letter table — permanent/schema failures land here, never crash the loop."""
    __tablename__ = "ingest_errors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text)


ALL_TABLES = [
    "oblasts",
    "oblast_adjacency",
    "raw_alerts",
    "exogenous_features",
    "hourly_panel",
    "feature_matrix",
    "ingest_errors",
]
