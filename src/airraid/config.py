"""Typed configuration loaded from .env via pydantic-settings."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore" so the many unrelated .env keys don't break loading.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://airraid:airraid@localhost:5432/airraid"

    # Live alert API (token serves only the last ~2 months; see plans/03 §C)
    alerts_in_ua_token: str | None = None
    ukrainealarm_api_token: str | None = None
    poll_interval_seconds: int = 45

    # Local LLM (Ollama) for the LangGraph OSINT parser — no external providers
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1:8b"

    # Telegram (OSINT) — one-time historical scrape only (no scheduler/daemon)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session_string: str | None = None
    telegram_channels: str = "kpszsu,air_alert_ua"

    random_seed: int = 42
    log_level: str = "INFO"


settings = Settings()
