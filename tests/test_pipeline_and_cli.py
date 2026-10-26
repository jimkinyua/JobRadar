"""Integration tests for JobRadarPipeline orchestrator and CLI commands."""

import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.adapters.storage.postgres_repo import PostgresRepository
from jobradar.adapters.telegram.client import TelegramClient
from jobradar.config import AppConfig, PipelineConfig, ScoringConfig, HealthConfig, SourceConfig, CrawlerConfig
from jobradar.domain.models import Job, RawJob, SourceRun
from jobradar.services.pipeline import JobRadarPipeline
from jobradar.cli import cmd_rescore, cmd_export_csv

TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


class MockTestSourceAdapter(BaseSourceAdapter):
    """Mock source adapter returning predictable test jobs."""

    def fetch_jobs(self, session=None) -> list[tuple[RawJob, Job]]:
        raw1 = RawJob(source="test_src", source_url="https://test.org/job-1", payload={"id": 1})
        job1 = Job(
            title="Senior .NET Developer",
            company="Rainforest Alliance",
            url="https://test.org/job-1",
            location="Nairobi, Kenya",
            description="C#, .NET Core, Azure, and SQL integration pipelines.",
            source="test_src",
        )

        raw2 = RawJob(source="test_src", source_url="https://test.org/job-2", payload={"id": 2})
        job2 = Job(
            title="Marketing Intern",
            company="Acme",
            url="https://test.org/job-2",
            location="Remote",
            description="Entry level internship.",
            source="test_src",
        )
        return [(raw1, job1), (raw2, job2)]


@pytest.fixture
def test_config():
    return AppConfig(
        pipeline=PipelineConfig(min_score=8.0, initial_run_baseline_alerts=10, max_alerts_per_run=15),
        scoring=ScoringConfig(
            locations={"nairobi": 4.0, "remote": 4.0},
            seniority={"senior": 2.0},
            tracks={
                "track_dotnet": {
                    "name": "Enterprise .NET",
                    "keywords": {".net": 5.0, "c#": 5.0, "azure": 3.0, "sql": 2.0},
                }
            },
            exclude_keywords=["intern", "junior"],
        ),
        health_monitoring=HealthConfig(drop_threshold_percent=50.0, alert_on_zero=True),
        sources=[SourceConfig(id="test_src", name="Test Source", type="mock", enabled=True)],
        crawler=CrawlerConfig(),
        database_url=TEST_DB_URL,
    )


@pytest.fixture
def pg_repo():
    repo = PostgresRepository(TEST_DB_URL)
    yield repo
    repo.close()


@pytest.fixture(autouse=True)
def clean_tables(pg_repo: PostgresRepository):
    with pg_repo.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                    scored_matches,
                    jobs,
                    raw_jobs,
                    source_runs,
                    discovered_employers
                CASCADE;
                """
            )
        conn.commit()


def test_pipeline_orchestrator_end_to_end(test_config, pg_repo, monkeypatch):
    mock_telegram = MagicMock(spec=TelegramClient)
    mock_telegram.is_configured.return_value = True
    mock_telegram.send_job_alert.return_value = True

    # Monkeypatch adapter factory to return MockTestSourceAdapter
    monkeypatch.setattr(
        "jobradar.services.pipeline.get_source_adapter",
        lambda src, crawl: MockTestSourceAdapter(src, crawl),
    )

    pipeline = JobRadarPipeline(test_config, pg_repo, mock_telegram)
    summary = pipeline.run(dry_run=False)

    # 1. Pipeline Summary Assertions
    assert summary["items_fetched"] == 2
    assert summary["new_jobs"] == 2
    assert summary["matches_found"] == 1
    assert summary["alerts_sent"] == 1
    assert summary["is_baseline_run"] is True

    # 2. Database Assertions
    assert pg_repo.count_total_jobs() == 2
    # Verify only the high-match received an alert
    unnotified = pg_repo.get_unnotified_matches()
    assert len(unnotified) == 0  # Alert was marked sent


def test_pipeline_dry_run_does_not_send_alerts(test_config, pg_repo, monkeypatch):
    mock_telegram = MagicMock(spec=TelegramClient)
    mock_telegram.is_configured.return_value = True

    monkeypatch.setattr(
        "jobradar.services.pipeline.get_source_adapter",
        lambda src, crawl: MockTestSourceAdapter(src, crawl),
    )

    pipeline = JobRadarPipeline(test_config, pg_repo, mock_telegram)
    summary = pipeline.run(dry_run=True)

    assert summary["alerts_sent"] == 0
    mock_telegram.send_job_alert.assert_not_called()


def test_cli_rescore_and_export_csv(test_config, pg_repo, monkeypatch, tmp_path: Path):
    # Setup 1 stored job in database
    job = Job(
        title="Senior .NET Developer",
        company="Rainforest Alliance",
        url="https://test.org/job-1",
        location="Nairobi, Kenya",
        description="C#, .NET Core, Azure.",
        source="test_src",
    )
    pg_repo.upsert_job(job)

    monkeypatch.setattr("jobradar.cli.load_config", lambda: test_config)
    monkeypatch.setattr("jobradar.cli.get_repository", lambda url: pg_repo)

    # Run rescore command
    class RescoreArgs:
        pass

    exit_code = cmd_rescore(RescoreArgs())
    assert exit_code == 0

    # Run export-csv command
    csv_file = tmp_path / "test_matches.csv"

    class ExportArgs:
        output = str(csv_file)

    exit_code_csv = cmd_export_csv(ExportArgs())
    assert exit_code_csv == 0
    assert csv_file.exists()

    content = csv_file.read_text(encoding="utf-8")
    assert "Senior .NET Developer" in content
    assert "Rainforest Alliance" in content
