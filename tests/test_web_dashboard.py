"""Unit tests for the JobRadar Web Dashboard and API endpoints."""

import pytest
from unittest.mock import MagicMock, patch
from jobradar.web.app import serve_dashboard, get_jobs, get_stats, get_sources


@pytest.mark.anyio
async def test_serve_dashboard_returns_file():
    """Verify that the dashboard root route serves the static index.html."""
    response = await serve_dashboard()
    assert response.status_code == 200
    assert str(response.path).endswith("index.html")


@pytest.mark.anyio
async def test_get_jobs_api_endpoint():
    """Verify that /api/jobs returns formatted job list with counts."""
    mock_repo = MagicMock()
    mock_repo.get_dashboard_jobs.return_value = [
        {
            "id": 1,
            "title": "Senior Data Engineer",
            "company": "Safaricom",
            "final_score": 14.5,
            "is_match": True,
            "best_track_id": "data_engineer",
        }
    ]

    with patch("jobradar.web.app.get_repository", return_value=mock_repo):
        result = await get_jobs(track="data_engineer", min_score=9.0)
        assert result["count"] == 1
        assert result["jobs"][0]["title"] == "Senior Data Engineer"
        mock_repo.get_dashboard_jobs.assert_called_once_with(
            track_id="data_engineer",
            min_score=9.0,
            source=None,
            search=None,
            application_status=None,
            limit=150,
        )


@pytest.mark.anyio
async def test_get_stats_api_endpoint():
    """Verify that /api/stats returns aggregate metrics."""
    mock_repo = MagicMock()
    mock_repo.get_dashboard_stats.return_value = {
        "total_jobs": 500,
        "high_matches": 67,
        "near_misses": 24,
        "active_sources": 12,
        "employers_spotted": 10,
        "top10_avg_score": 14.2,
    }

    with patch("jobradar.web.app.get_repository", return_value=mock_repo):
        stats = await get_stats()
        assert stats["total_jobs"] == 500
        assert stats["high_matches"] == 67
        assert stats["top10_avg_score"] == 14.2


@pytest.mark.anyio
async def test_get_sources_api_endpoint():
    """Verify that /api/sources returns list of configured sources."""
    result = await get_sources()
    assert "sources" in result
    assert len(result["sources"]) > 0
    source_ids = [s["id"] for s in result["sources"]]
    assert "coop_bank" in source_ids
    assert "kpmg_east_africa" in source_ids


@pytest.mark.anyio
async def test_evaluate_job_ai_endpoint():
    """Verify that /api/jobs/{job_id}/ai-evaluate evaluates fit via Gemini."""
    from jobradar.web.app import evaluate_job_ai
    from jobradar.domain.models import AICopilotInsight, Job

    mock_insight = AICopilotInsight(
        semantic_fit_score=94,
        fit_rationale="Great profile alignment",
        key_strengths=["Python", "C#"],
        skill_gaps=[],
        tailored_pitch="Proven track record",
    )

    mock_job = Job(
        title="Senior AI Engineer",
        company="Co-op Bank",
        url="https://example.com/job",
        location="Nairobi",
        description="Build LLM systems",
        source="coop_bank",
    )

    mock_repo = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "id": 10,
        "title": "Senior AI Engineer",
        "company": "Co-op Bank",
        "url": "https://example.com/job",
        "location": "Nairobi",
        "description": "Build LLM systems",
        "source": "coop_bank",
        "fingerprint": "abc12345",
        "breakdown_json": None,
    }
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_repo.pool.connection.return_value.__enter__.return_value = mock_conn
    mock_repo._row_to_job.return_value = mock_job

    with patch("jobradar.web.app.get_repository", return_value=mock_repo), \
         patch("jobradar.services.ai_service.AIService.is_available", return_value=True), \
         patch("jobradar.services.ai_service.AIService.evaluate_job_fit", return_value=mock_insight):
        res = await evaluate_job_ai(10)
        assert res["status"] == "generated"
        assert res["ai_insight"]["semantic_fit_score"] == 94

