"""Unit tests for AIService semantic job evaluation and web extraction."""

import pytest
from jobradar.domain.models import AICopilotInsight, ExtractedJobItem, Job
from jobradar.services.ai_client import GeminiClient
from jobradar.services.ai_service import AIService, ExtractedJobsList, load_candidate_profile


def test_load_candidate_profile():
    profile = load_candidate_profile("config/profile.yaml")
    assert profile.get("name") == "James Kinyua"
    assert "Python" in profile.get("core_skills", [])
    assert "FastAPI" in profile.get("core_skills", [])


def test_ai_service_is_available():
    # Unconfigured client
    unconf_service = AIService(client=GeminiClient(api_key=None))
    assert unconf_service.is_available() is False

    # Configured client
    conf_service = AIService(client=GeminiClient(api_key="AIzaSyValidGeminiKey123"))
    assert conf_service.is_available() is True


def test_evaluate_job_fit_success(mocker):
    client = GeminiClient(api_key="AIzaSyValidGeminiKey123")
    expected_insight = AICopilotInsight(
        semantic_fit_score=94,
        fit_rationale="Strong match for Co-op Bank AI Application Engineer role.",
        key_strengths=["Python", "FastAPI", "Data Pipelines", "Kafka"],
        skill_gaps=["Qdrant vector database"],
        tailored_pitch="Engineered automated Medallion data pipelines in Python and PostgreSQL.",
    )

    mocker.patch.object(client, "generate_json", return_value=expected_insight)

    service = AIService(client=client)
    job = Job(
        title="AI Application Engineer",
        company="Co-operative Bank of Kenya",
        url="https://www.co-opbank.co.ke/careers/co-op-bank/ai-application-engineer/",
        location="Nairobi, Kenya",
        description="Developing LLM applications, RAG pipelines, and integrating vector databases.",
        source="coop_bank",
    )

    insight = service.evaluate_job_fit(job)
    assert insight is not None
    assert insight.semantic_fit_score == 94
    assert "FastAPI" in insight.key_strengths
    assert "Qdrant vector database" in insight.skill_gaps
    assert client.generate_json.called


def test_evaluate_job_fit_unconfigured():
    client = GeminiClient(api_key=None)
    service = AIService(client=client)
    job = Job(
        title="Software Engineer",
        company="Tech Corp",
        url="https://example.com/job/1",
        source="test",
    )

    # When unconfigured, should return None without error
    assert service.evaluate_job_fit(job) is None


def test_extract_jobs_from_unstructured_page(mocker):
    client = GeminiClient(api_key="AIzaSyValidGeminiKey123")
    mock_extracted = ExtractedJobsList(
        jobs=[
            ExtractedJobItem(
                title="AI Application Engineer",
                url="https://www.co-opbank.co.ke/careers/ai-app-eng",
                location="Nairobi, Kenya",
                summary="Build AI pipelines.",
            ),
            ExtractedJobItem(
                title="Data Scientist",
                url="https://www.co-opbank.co.ke/careers/data-scientist",
                location="Nairobi, Kenya",
                summary="Machine learning models.",
            ),
        ]
    )

    mocker.patch.object(client, "generate_json", return_value=mock_extracted)

    service = AIService(client=client)
    raw_html_snippet = "<div>Some messy unformatted corporate HTML listing jobs</div>"
    jobs = service.extract_jobs_from_unstructured_page(
        page_text=raw_html_snippet,
        base_url="https://www.co-opbank.co.ke",
    )

    assert len(jobs) == 2
    assert jobs[0].title == "AI Application Engineer"
    assert jobs[1].title == "Data Scientist"
