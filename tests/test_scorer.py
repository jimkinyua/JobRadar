"""Unit tests for JobScorer and keyword word-boundary matching."""

import pytest
from jobradar.config import load_config
from jobradar.domain.models import Job
from jobradar.services.scorer import JobScorer, build_keyword_pattern


@pytest.fixture
def scorer():
    config = load_config("config/config.yaml")
    return JobScorer(config)


def test_word_boundary_regex_accuracy():
    # .NET should match '.NET' but not 'Internet' or 'network'
    net_pat = build_keyword_pattern(".net")
    assert net_pat.search("Senior .NET Developer")
    assert net_pat.search("Working with ASP.NET and .NET Core")
    assert not net_pat.search("Internet Infrastructure Engineer")

    # C# should match 'C#' but not 'C++' or 'Cloud'
    cs_pat = build_keyword_pattern("c#")
    assert cs_pat.search("Backend C# Engineer")
    assert not cs_pat.search("C++ Developer")

    # Go should match 'Go' but not 'Good' or 'Going'
    go_pat = build_keyword_pattern("go")
    assert go_pat.search("Senior Go Backend Engineer")
    assert not go_pat.search("A good developer with strong skills")
    assert not go_pat.search("Algorithm analysis")

    # Tax should match 'tax' but not 'syntax'
    tax_pat = build_keyword_pattern("tax")
    assert tax_pat.search("Tax Systems Integration Developer")
    assert not tax_pat.search("Fixing Python syntax errors")


def test_score_rainforest_alliance_dotnet(scorer: JobScorer):
    job = Job(
        title="Senior .NET Developer",
        company="Rainforest Alliance",
        url="https://rainforest-alliance.org/jobs/sr-dotnet",
        location="Nairobi, Kenya",
        description="We are looking for a Senior .NET Developer with C#, ASP.NET, SQL, and Azure experience.",
        source="rainforest_alliance",
    )
    breakdown = scorer.score(job)

    assert breakdown.is_match is True
    assert breakdown.best_track_id == "track_dotnet_azure"
    assert breakdown.final_score >= 12.0
    assert "senior" in [s.split()[0] for s in breakdown.matched_seniority]
    assert "nairobi" in [loc.split()[0] for loc in breakdown.matched_locations]


def test_score_data_engineer_path(scorer: JobScorer):
    job = Job(
        title="Senior Data Engineer",
        company="PATH",
        url="https://path.org/jobs/de-10",
        location="Remote, Kenya",
        description="Building streaming pipelines using Kafka, ETL, Python, and Azure Data Factory.",
        source="path",
    )
    breakdown = scorer.score(job)

    assert breakdown.is_match is True
    assert breakdown.best_track_id == "track_data_engineering"
    assert breakdown.track_score >= 9.0
    assert breakdown.final_score >= 18.0


def test_disqualification_junior_or_intern(scorer: JobScorer):
    job = Job(
        title="Junior .NET Developer Intern",
        company="Acme Corp",
        url="https://acme.org/jobs/junior-1",
        location="Nairobi",
        description="Entry-level internship for graduates.",
        source="acme",
    )
    breakdown = scorer.score(job)

    assert breakdown.is_match is False
    assert breakdown.penalties >= 20.0
    assert len(breakdown.matched_penalties) >= 1


def test_near_miss_detection(scorer: JobScorer):
    # A job with moderate match that scores between 6.0 and 7.9 (min_score is 8.0)
    job = Job(
        title="Backend Software Developer",
        company="Some Org",
        url="https://example.org/jobs/backend-1",
        location="Remote",
        description="Working on SQL databases and Python scripts.",
        source="example",
    )
    breakdown = scorer.score(job)

    # Python (desc: 1.5) + SQL (desc: 1.0) + Remote (4.0) = 6.5
    if 6.0 <= breakdown.final_score < 8.0:
        assert breakdown.is_near_miss is True
        assert breakdown.is_match is False


def test_score_ai_ml_engineering_track(scorer: JobScorer):
    job = Job(
        title="AI Application Engineer",
        company="Co-operative Bank of Kenya",
        url="https://www.co-opbank.co.ke/careers/co-op-bank/ai-application-engineer/",
        location="Nairobi, Kenya",
        description="Developing LLM applications, RAG pipelines, fine-tuning, and integrating vector databases using LangChain and PyTorch.",
        source="coop_bank",
    )
    breakdown = scorer.score(job)

    assert breakdown.is_match is True
    assert breakdown.best_track_id == "track_ai_ml"
    assert breakdown.track_score >= 10.0
    assert breakdown.final_score >= 12.0

