"""
Unit tests for zero-code dynamic source detection, live probing, and custom source management.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from jobradar.domain.models import ExtractedJobItem, Job, RawJob
from jobradar.services.source_detector import probe_source
from jobradar.adapters.sources.ai_html import AiHtmlSourceAdapter
from jobradar.config import SourceConfig, CrawlerConfig


def test_probe_source_greenhouse_ats():
    """Verify ATS sniffer detects Greenhouse and constructs API URL."""
    with patch("jobradar.services.source_detector._test_adapter_extraction") as mock_test:
        mock_test.return_value = {
            "success": True,
            "type": "greenhouse",
            "type_label": "Greenhouse ATS API",
            "count": 2,
            "sample_jobs": [{"title": "Software Engineer"}],
        }
        res = probe_source("https://boards.greenhouse.io/stripe", name="Stripe")
        assert res["success"] is True
        mock_test.assert_called_once()
        kwargs = mock_test.call_args[1]
        assert kwargs["source_type"] == "greenhouse"
        assert "boards-api.greenhouse.io/v1/boards/stripe/jobs" in kwargs["url"]
        assert kwargs["name"] == "Stripe"


def test_probe_source_lever_ats():
    """Verify ATS sniffer detects Lever and constructs postings API URL."""
    with patch("jobradar.services.source_detector._test_adapter_extraction") as mock_test:
        mock_test.return_value = {"success": True, "type": "lever"}
        res = probe_source("https://jobs.lever.co/netflix", name="Netflix")
        assert res["success"] is True
        kwargs = mock_test.call_args[1]
        assert kwargs["source_type"] == "lever"
        assert "api.lever.co/v0/postings/netflix?mode=json" in kwargs["url"]


def test_probe_source_smartrecruiters_ats():
    """Verify ATS sniffer detects SmartRecruiters."""
    with patch("jobradar.services.source_detector._test_adapter_extraction") as mock_test:
        mock_test.return_value = {"success": True, "type": "smartrecruiters"}
        res = probe_source("https://jobs.smartrecruiters.com/AcmeCorp", name="Acme")
        assert res["success"] is True
        kwargs = mock_test.call_args[1]
        assert kwargs["source_type"] == "smartrecruiters"
        assert "api.smartrecruiters.com/v1/companies/acmecorp/postings" in kwargs["url"]


def test_probe_source_rss_detection():
    """Verify RSS feed detection from XML header or link tag."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/xml"}
    mock_resp.text = '<?xml version="1.0"?><rss><channel><title>Jobs</title></channel></rss>'

    with patch("requests.get", return_value=mock_resp), \
         patch("jobradar.services.source_detector._test_adapter_extraction") as mock_test:
        mock_test.return_value = {"success": True, "type": "rss"}
        res = probe_source("https://example.com/jobs/feed")
        assert res["success"] is True
        kwargs = mock_test.call_args[1]
        assert kwargs["source_type"] == "rss"


def test_probe_source_fallback_to_gemini_ai():
    """Verify HTML pages without standard selectors fallback to Gemini AI."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = '<html><body><div>Custom corporate careers page without selectors</div></body></html>'

    with patch("requests.get", return_value=mock_resp), \
         patch("jobradar.services.source_detector._test_adapter_extraction") as mock_test:
        # First call with html fails/returns 0 items, second call uses ai_html
        mock_test.side_effect = [
            {"success": True, "count": 0},
            {"success": True, "type": "ai_html", "count": 3},
        ]
        res = probe_source("https://mycompany.co.ke/careers", name="MyCompany")
        assert res["success"] is True
        assert res["type"] == "ai_html"


def test_ai_html_source_adapter_extraction():
    """Verify AiHtmlSourceAdapter fetches page and parses items via AIService."""
    source_cfg = SourceConfig(
        id="test_ai_source",
        name="Test Corp",
        type="ai_html",
        url="https://example.com/careers",
        enabled=True,
    )
    crawler_cfg = CrawlerConfig(request_delay_seconds=0, request_timeout_seconds=5)

    mock_ai = MagicMock()
    mock_ai.extract_jobs_from_unstructured_page.return_value = [
        ExtractedJobItem(
            title="Senior Backend Engineer",
            url="/job/backend-1",
            location="Nairobi",
            summary="Python FastAPI engineering",
        )
    ]

    adapter = AiHtmlSourceAdapter(source_cfg, crawler_cfg, ai_service=mock_ai)

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Open Positions</h1><div>Senior Backend Engineer</div></body></html>"
    mock_session.get.return_value = mock_resp

    with patch.object(adapter, "is_allowed_by_robots", return_value=True):
        items = adapter.fetch_jobs(session=mock_session)
        assert len(items) == 1
        raw, job = items[0]
        assert job.title == "Senior Backend Engineer"
        assert job.url == "https://example.com/job/backend-1"
        assert job.company == "Test Corp"


@pytest.mark.anyio
async def test_api_sources_probe_and_crud():
    """Verify FastAPI /api/sources endpoints."""
    from jobradar.web.app import probe_source_endpoint, add_source, toggle_source, delete_source
    from jobradar.web.app import SourceProbeRequest, AddSourceRequest, ToggleSourceRequest

    # 1. Probe
    with patch("jobradar.services.source_detector.probe_source", return_value={"success": True, "type": "greenhouse"}):
        probe_res = await probe_source_endpoint(SourceProbeRequest(url="https://boards.greenhouse.io/sample"))
        assert probe_res["success"] is True

    # 2. Add
    mock_repo = MagicMock()
    mock_repo.save_custom_source.return_value = {"id": "my_new_source", "name": "New Source", "enabled": True}
    with patch("jobradar.web.app.get_repository", return_value=mock_repo):
        add_res = await add_source(AddSourceRequest(name="New Source", url="https://example.com"))
        assert add_res["success"] is True
        assert add_res["source"]["id"] == "my_new_source"

    # 3. Toggle
    mock_repo.toggle_custom_source.return_value = True
    with patch("jobradar.web.app.get_repository", return_value=mock_repo):
        toggle_res = await toggle_source("my_new_source", ToggleSourceRequest(enabled=False))
        assert toggle_res["success"] is True
        assert toggle_res["enabled"] is False

    # 4. Delete
    mock_repo.delete_custom_source.return_value = True
    with patch("jobradar.web.app.get_repository", return_value=mock_repo):
        del_res = await delete_source("my_new_source")
        assert del_res["success"] is True
