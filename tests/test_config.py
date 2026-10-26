"""Unit tests for JobRadar configuration parser and employers registry."""

import os
from pathlib import Path
from jobradar.config import load_config, load_employers, save_employers


def test_load_default_config():
    config = load_config("config/config.yaml")

    assert config.pipeline.min_score == 8.0
    assert config.pipeline.near_miss_delta == 2.0
    assert "track_data_engineering" in config.scoring.tracks
    assert "track_dotnet_azure" in config.scoring.tracks
    assert "track_fintech_integrations" in config.scoring.tracks
    assert "nairobi" in config.scoring.locations
    assert config.crawler.request_delay_seconds == 2.0


def test_load_and_save_employers(tmp_path: Path):
    temp_yaml = tmp_path / "test_employers.yaml"
    initial_data = [
        {
            "id": 1,
            "company": "Safaricom",
            "system": "smartrecruiters",
            "identifier": "safaricom",
            "status": "approved",
        }
    ]

    save_employers(initial_data, temp_yaml)
    loaded = load_employers(temp_yaml)

    assert len(loaded) == 1
    assert loaded[0]["company"] == "Safaricom"
    assert loaded[0]["status"] == "approved"
