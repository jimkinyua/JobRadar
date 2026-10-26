"""Comprehensive unit tests for the PostgreSQL storage repository layer."""

import os
from datetime import datetime, timezone, timedelta
import pytest
from jobradar.adapters.storage.postgres_repo import PostgresRepository
from jobradar.adapters.storage.factory import get_repository
from jobradar.domain.models import (
    RawJob,
    Job,
    ScoredJob,
    ScoreBreakdown,
    SourceRun,
    DiscoveredEmployer,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
if not TEST_DB_URL:
    raise RuntimeError(
        "DATABASE_URL or TEST_DATABASE_URL must be defined in your .env file to run storage tests."
    )


@pytest.fixture(scope="module")
def pg_repo():
    """Module-level Postgres repository fixture."""
    repo = PostgresRepository(TEST_DB_URL)
    yield repo
    repo.close()


@pytest.fixture(autouse=True)
def clean_tables(pg_repo: PostgresRepository):
    """Clean all tables before each test for total test isolation."""
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


def test_bronze_layer_save_raw_job(pg_repo: PostgresRepository):
    raw = RawJob(
        source="smartrecruiters",
        source_url="https://api.smartrecruiters.com/v1/companies/deloitte/postings",
        payload={"id": "sr-100", "title": "Senior Consultant .NET", "company": "Deloitte"},
    )
    raw_id = pg_repo.save_raw_job(raw)
    assert raw_id > 0


def test_silver_layer_upsert_deduplication(pg_repo: PostgresRepository):
    job1 = Job(
        title="Senior .NET Developer",
        company="Rainforest Alliance",
        url="https://rainforest-alliance.org/jobs/dotnet-1",
        location="Nairobi, Kenya",
        description="Senior .NET Developer working on forestry analytics.",
        source="rainforest_careers",
    )
    saved_job, is_new = pg_repo.upsert_job(job1)
    assert is_new is True
    assert pg_repo.count_total_jobs() == 1

    # Second arrival of the same job (identical company & title)
    job2 = Job(
        title="Senior .NET Developer",
        company="Rainforest Alliance",
        url="https://fuzu.com/jobs/rainforest-alliance-senior-dotnet-developer",
        location="Nairobi, Kenya",
        description="Senior .NET Developer working on forestry analytics and Azure data pipelines.",
        source="fuzu",
    )
    saved_job2, is_new2 = pg_repo.upsert_job(job2)
    assert is_new2 is False, "Duplicate listing across boards must update existing entity rather than duplicate"
    assert pg_repo.count_total_jobs() == 1


def test_gold_layer_scoring_and_unnotified_queue(pg_repo: PostgresRepository):
    job = Job(
        title="Data Engineer",
        company="PATH",
        url="https://path.org/jobs/de-10",
        source="path",
    )
    pg_repo.upsert_job(job)

    breakdown = ScoreBreakdown(
        best_track_id="track_data_engineering",
        best_track_name="Data Engineering & Streaming",
        track_score=14.0,
        final_score=18.0,
        is_match=True,
        is_near_miss=False,
    )
    scored = ScoredJob(job=job, score_breakdown=breakdown)
    pg_repo.save_scored_match(scored)

    # Fetch unnotified matches
    unnotified = pg_repo.get_unnotified_matches(limit=10)
    assert len(unnotified) == 1
    assert unnotified[0].job.fingerprint == job.fingerprint
    assert float(unnotified[0].score_breakdown.final_score) == 18.0

    # Mark notified
    pg_repo.mark_alert_sent(job.fingerprint)
    assert len(pg_repo.get_unnotified_matches()) == 0


def test_near_misses_and_deadline_reminders(pg_repo: PostgresRepository):
    closing_in_2_days = datetime.now(timezone.utc) + timedelta(days=2)
    job = Job(
        title="Tax Systems Integration Developer",
        company="Davis & Shirtliff",
        url="https://davisandshirtliff.com/careers/tax-dev",
        deadline=closing_in_2_days,
        source="davis_careers",
    )
    pg_repo.upsert_job(job)

    breakdown = ScoreBreakdown(
        best_track_id="track_fintech_integrations",
        best_track_name="FinTech & System Integrations",
        track_score=7.0,
        final_score=7.5,
        is_match=True,
        is_near_miss=True,
    )
    pg_repo.save_scored_match(ScoredJob(job=job, score_breakdown=breakdown))

    # Check near misses
    near_misses = pg_repo.get_near_misses(days_back=7)
    assert len(near_misses) == 1
    assert near_misses[0].job.company == "Davis & Shirtliff"

    # Check closing soon matches
    closing_soon = pg_repo.get_closing_soon_matches(days_ahead=3)
    assert len(closing_soon) == 1
    pg_repo.mark_deadline_reminder_sent(job.fingerprint)
    assert len(pg_repo.get_closing_soon_matches(days_ahead=3)) == 0


def test_observability_source_runs(pg_repo: PostgresRepository):
    run1 = SourceRun(
        source_id="smartrecruiters",
        items_fetched=25,
        new_items=5,
        matches_found=2,
        status="success",
    )
    pg_repo.record_source_run(run1)

    run2 = SourceRun(
        source_id="smartrecruiters",
        items_fetched=28,
        new_items=3,
        matches_found=1,
        status="success",
    )
    pg_repo.record_source_run(run2)

    prev_run = pg_repo.get_previous_source_run("smartrecruiters")
    assert prev_run is not None
    assert prev_run.items_fetched == 25


def test_employer_discovery_lifecycle(pg_repo: PostgresRepository):
    emp = DiscoveredEmployer(
        company="Watu Credit",
        system="greenhouse",
        slug="watu-credit",
    )
    saved_emp, is_new = pg_repo.upsert_discovered_employer(emp)
    assert is_new is True
    assert saved_emp.jobs_seen == 1

    # Second sighting increments sightings
    saved_emp2, is_new2 = pg_repo.upsert_discovered_employer(emp)
    assert is_new2 is False
    assert saved_emp2.jobs_seen == 2

    # Status update
    updated = pg_repo.update_employer_status(saved_emp2.id, "approved")
    assert updated is True

    approved_list = pg_repo.get_discovered_employers(status="approved")
    assert len(approved_list) == 1
    assert approved_list[0].company == "Watu Credit"


def test_factory_postgres():
    repo = get_repository(TEST_DB_URL)
    assert isinstance(repo, PostgresRepository)
    repo.close()
