"""Configuration parser and validator for JobRadar."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Automatically load .env if present
load_dotenv()


class TrackConfig(BaseModel):
    name: str
    keywords: dict[str, float] = Field(default_factory=dict)


class ScoringConfig(BaseModel):
    title_any: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    locations: dict[str, float] = Field(default_factory=dict)
    seniority: dict[str, float] = Field(default_factory=dict)
    tracks: dict[str, TrackConfig] = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    name: str = "jobradar"
    version: str = "0.1.0"
    min_score: float = 8.0
    near_miss_delta: float = 2.0
    max_alerts_per_run: int = 15
    initial_run_baseline_alerts: int = 10
    deadline_reminder_days: int = 3


class HealthConfig(BaseModel):
    drop_threshold_percent: float = 50.0
    alert_on_zero: bool = True


class SourceConfig(BaseModel):
    id: str
    name: str
    type: str  # rss, smartrecruiters, greenhouse, lever, workable, remotive, reliefweb, html
    url: Optional[str] = None
    company_identifier: Optional[str] = None
    enabled: bool = True
    requires_env: Optional[str] = None
    selectors: Optional[dict[str, str]] = None  # for custom html crawler


class CrawlerConfig(BaseModel):
    user_agent: str = "JobRadarBot/1.0"
    request_delay_seconds: float = 2.0
    request_timeout_seconds: float = 15.0


class AppConfig(BaseModel):
    pipeline: PipelineConfig
    scoring: ScoringConfig
    health_monitoring: HealthConfig
    sources: list[SourceConfig] = Field(default_factory=list)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)

    # Runtime database and secrets from environment variables
    database_url: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", "")
    )
    telegram_bot_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    telegram_chat_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID")
    )
    reliefweb_appname: Optional[str] = Field(
        default_factory=lambda: os.getenv("RELIEFWEB_APPNAME")
    )


def load_config(config_path: str | Path = "config/config.yaml") -> AppConfig:
    """Load and validate the YAML configuration file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return AppConfig.model_validate(data)


def load_employers(employers_path: str | Path = "config/employers.yaml") -> list[dict[str, Any]]:
    """Load watched employers YAML registry."""
    path = Path(employers_path)
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("employers", [])


def save_employers(employers: list[dict[str, Any]], employers_path: str | Path = "config/employers.yaml") -> None:
    """Save watched employers to YAML registry."""
    path = Path(employers_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"employers": employers}, f, sort_keys=False)
