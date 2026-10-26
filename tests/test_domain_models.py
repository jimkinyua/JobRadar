"""Unit tests for JobRadar domain models and fingerprinting logic."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from jobradar.domain.models import (
    Job,
    RawJob,
    ScoreBreakdown,
    ScoredJob,
    DiscoveredEmployer,
    generate_fingerprint,
    normalize_text,
)


def test_normalize_text():
    assert normalize_text("  Safaricom PLC.  ") == "safaricom plc"
    assert normalize_text("Senior .NET / C# Developer!!") == "senior net c developer"
    assert normalize_text("") == ""


def test_fingerprint_deterministic_and_deduplicating():
    fp1 = generate_fingerprint("Safaricom PLC", "Senior .NET Developer")
    fp2 = generate_fingerprint("safaricom   plc.", "Senior .NET Developer")
    fp3 = generate_fingerprint("Airtel Kenya", "Senior .NET Developer")

    assert fp1 == fp2, "Subtle formatting and casing differences should yield matching fingerprints"
    assert fp1 != fp3, "Different companies must produce distinct fingerprints"


def test_job_model_creation_and_auto_fingerprint():
    job = Job(
        title="  Cloud Solutions Developer  ",
        company="PATH",
        url="https://path.org/jobs/123",
        location="Nairobi, Kenya",
        description="Developing Azure Cloud Solutions using Python and C#.",
        source="path_careers",
    )

    assert job.title == "Cloud Solutions Developer"
    assert job.company == "PATH"
    assert job.fingerprint != ""
    assert len(job.fingerprint) == 64  # SHA-256 length
    assert job.is_closed is False


def test_job_model_validation_failure_on_empty_fields():
    with pytest.raises(ValidationError):
        Job(
            title="",
            company="Davis & Shirtliff",
            url="https://davisandshirtliff.com/jobs/1",
            source="manual",
        )


def test_scored_job_and_breakdown_serialization():
    job = Job(
        title="Senior Data Engineer",
        company="Watu Credit",
        url="https://watu.africa/jobs/456",
        source="watu_careers",
    )
    breakdown = ScoreBreakdown(
        best_track_id="track_data_engineering",
        best_track_name="Data Engineering & Streaming",
        track_score=12.0,
        location_bonus=4.0,
        matched_locations=["nairobi"],
        seniority_bonus=2.0,
        matched_seniority=["senior"],
        penalties=0.0,
        final_score=18.0,
        is_match=True,
        is_near_miss=False,
        details="Matched Kafka, ETL, Azure in description; Nairobi location bonus.",
    )

    scored = ScoredJob(job=job, score_breakdown=breakdown)
    assert scored.score_breakdown.final_score == 18.0
    assert scored.score_breakdown.is_match is True
    assert scored.job.company == "Watu Credit"
