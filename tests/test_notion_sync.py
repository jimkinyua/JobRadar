"""
Automated unit tests for JobRadar <-> Notion Job Applications integration.
Tests cover:
- NotionClient configuration & schema mapping
- Fuzzy company & role title matching engine
- Bidirectional synchronization logic & link backfill
- Notification & reminder gatekeeping for applied / closed jobs
- Web API status transition & Notion sync endpoints
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch
import pytest

from jobradar.domain.models import Job
from jobradar.adapters.notion.client import NotionClient
from jobradar.adapters.notion.sync import (
    normalize_company_name,
    normalize_role_tokens,
    is_company_match,
    is_role_match,
    find_matching_job,
    sync_notion_with_repository,
)


# ============================================================================
# 1. NotionClient Configuration & Client Unit Tests
# ============================================================================

def test_notion_client_configuration_checks():
    """Verify is_configured handles missing or dummy credentials."""
    unconfigured = NotionClient(api_key="", database_id="")
    assert not unconfigured.is_configured()

    dummy = NotionClient(api_key="your_notion_secret_key_here", database_id="")
    assert not dummy.is_configured()

    configured = NotionClient(api_key="secret_test_123456789", database_id="db_abc123")
    assert configured.is_configured()


def test_notion_client_query_database_success():
    """Verify query_database correctly parses Notion API response into dictionaries."""
    client = NotionClient(api_key="secret_mock", database_id="db_mock")

    mock_notion_response = {
        "results": [
            {
                "id": "page_001",
                "properties": {
                    "Role": {"type": "title", "title": [{"plain_text": "Senior Backend Engineer"}]},
                    "Company": {"type": "rich_text", "rich_text": [{"plain_text": "M-KOPA Solar"}]},
                    "Status": {"type": "status", "status": {"name": "Interview"}},
                    "Date Applied": {"type": "date", "date": {"start": "2026-10-25"}},
                    "Job Link": {"type": "url", "url": "https://careers.m-kopa.com/job/123"},
                    "Notes": {"type": "rich_text", "rich_text": [{"plain_text": "First round passed."}]},
                },
            },
            {
                "id": "page_002",
                "properties": {
                    "Role": {"type": "title", "title": [{"plain_text": "Lead Data Scientist"}]},
                    "Company": {"type": "select", "select": {"name": "Safaricom"}},
                    "Status": {"type": "select", "select": {"name": "Applied"}},
                    "Job Link": {"type": "url", "url": None},
                },
            },
        ],
        "has_more": False,
        "next_cursor": None,
    }

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_notion_response

    with patch.object(client.session, "post", return_value=mock_resp):
        pages = client.query_database()
        assert len(pages) == 2

        p1 = pages[0]
        assert p1["page_id"] == "page_001"
        assert p1["role"] == "Senior Backend Engineer"
        assert p1["company"] == "M-KOPA Solar"
        assert p1["status"] == "Interview"
        assert p1["job_link"] == "https://careers.m-kopa.com/job/123"
        assert p1["notes"] == "First round passed."
        assert p1["date_applied"] == "2026-10-25"

        p2 = pages[1]
        assert p2["page_id"] == "page_002"
        assert p2["company"] == "Safaricom"
        assert p2["status"] == "Applied"
        assert not p2["job_link"]


def test_notion_client_create_application_page():
    """Verify create_application_page constructs the expected Notion payload."""
    client = NotionClient(api_key="secret_mock", database_id="db_mock")

    mock_job = Job(
        title="Cloud Solutions Architect",
        company="Equity Bank",
        url="https://equitybank.com/careers/1",
        location="Nairobi",
        description="AWS / Azure infrastructure",
        source="direct",
    )

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "new_page_999"}

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        page_id = client.create_application_page(
            job=mock_job,
            status="Applied",
            notes="Applied through portal",
        )
        assert page_id == "new_page_999"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        body = call_kwargs["json"]
        assert body["parent"]["database_id"] == "db_mock"
        props = body["properties"]
        assert props["Role"]["title"][0]["text"]["content"] == "Cloud Solutions Architect"
        assert props["Company"]["rich_text"][0]["text"]["content"] == "Equity Bank"
        assert props["Job Link"]["url"] == "https://equitybank.com/careers/1"


# ============================================================================
# 2. Fuzzy Matcher & Normalization Unit Tests
# ============================================================================

def test_normalize_company_name():
    """Test standard corporate suffixes and noise removal."""
    assert normalize_company_name("M-KOPA Solar Kenya Ltd.") == "m-kopa"
    assert normalize_company_name("Safaricom PLC") == "safaricom"
    assert "co-operative" in normalize_company_name("Co-operative Bank of Kenya")
    assert normalize_company_name("Davis & Shirtliff Limited") == "davis shirtliff"
    assert normalize_company_name("Watu Credit Africa") == "watu"


def test_is_company_match():
    """Test fuzzy company matching across variants."""
    assert is_company_match("M-KOPA Solar", "M-KOPA")
    assert is_company_match("Safaricom PLC", "Safaricom")
    assert is_company_match("KPMG East Africa", "KPMG")
    assert not is_company_match("Google", "Microsoft")
    assert not is_company_match("NCBA Bank", "Equity Bank")


def test_is_role_match():
    """Test token overlap matching for role titles."""
    assert is_role_match("Senior Backend Engineer - Python", "Backend Engineer")
    assert is_role_match("Full Stack Developer (React / Python)", "Full Stack Developer")
    assert not is_role_match("Human Resources Business Partner", "Senior DevOps Engineer")
    assert not is_role_match("Finance Assistant", "Full Stack Developer")


def test_find_matching_job_by_url_and_fuzzy():
    """Verify find_matching_job matches by URL first, then fuzzy company/title."""
    job_target = Job(
        title="Senior Python Architect",
        company="M-KOPA Solar",
        url="https://mkopa.com/careers/123",
        location="Nairobi",
        description="Core services",
        source="direct",
    )
    job_target.id = 42

    all_jobs = [job_target]
    url_index = {job_target.url: job_target}

    # 1. Exact URL Match
    record_with_url = {
        "page_id": "p1",
        "role": "Python Architect",
        "company": "M-KOPA",
        "status": "Applied",
        "job_link": "https://mkopa.com/careers/123",
    }
    match = find_matching_job(record_with_url, all_jobs, url_index)
    assert match is not None
    assert match.id == 42

    # 2. Fuzzy Match (when job_link is None)
    record_without_url = {
        "page_id": "p2",
        "role": "Senior Python Architect",
        "company": "M-KOPA",
        "status": "Applied",
        "job_link": None,
    }
    match_fuzzy = find_matching_job(record_without_url, all_jobs, url_index)
    assert match_fuzzy is not None
    assert match_fuzzy.id == 42


# ============================================================================
# 3. Bidirectional Sync Engine & Link Backfill Unit Tests
# ============================================================================

def test_sync_notion_with_repository_updates_status_and_backfills_link():
    """Verify sync updates repo status and backfills Notion URL when missing."""
    notion = MagicMock()
    notion.is_configured.return_value = True

    repo = MagicMock()
    job_repo = Job(
        title="Engineering Manager - Payments",
        company="Watu Credit Ltd",
        url="https://watu.africa/jobs/eng-mgr",
        location="Nairobi",
        description="Lead payment rails",
        source="watu_credit",
    )
    job_repo.id = 88
    job_repo.application_status = "unapplied"

    repo.get_all_jobs_for_rescore.return_value = [job_repo]

    # Notion row without job_link
    notion.query_database.return_value = [
        {
            "page_id": "page_watu_1",
            "role": "Engineering Manager",
            "company": "Watu Credit",
            "status": "Interview",
            "job_link": None,
            "notes": "Screening call cleared",
            "date_applied": "2026-10-25",
        }
    ]
    notion.update_application_page.return_value = True

    summary = sync_notion_with_repository(notion, repo)

    assert summary["synced_jobs"] == 1
    assert summary["backfilled_links"] == 1
    assert summary["notion_rows_scanned"] == 1

    # Verify repo update
    repo.update_job_application_status.assert_called_once()
    call_kwargs = repo.update_job_application_status.call_args[1]
    assert call_kwargs["job_id_or_fingerprint"] == job_repo.fingerprint
    assert call_kwargs["status"] == "Interview"
    assert call_kwargs["notion_page_id"] == "page_watu_1"
    assert call_kwargs["notes"] == "Screening call cleared"

    # Verify Notion URL backfill
    notion.update_application_page.assert_called_once_with(
        page_id="page_watu_1",
        job_link="https://watu.africa/jobs/eng-mgr",
    )


def test_sync_notion_graceful_degradation_when_unconfigured():
    """Verify sync returns safely without errors if Notion is unconfigured."""
    notion = MagicMock()
    notion.is_configured.return_value = False
    repo = MagicMock()

    summary = sync_notion_with_repository(notion, repo)
    assert summary["synced_jobs"] == 0
    assert summary["notion_rows_scanned"] == 0
    repo.get_all_jobs_for_rescore.assert_not_called()


# ============================================================================
# 4. Reminder Gatekeeping Unit Tests
# ============================================================================

def test_reminder_gatekeeping_sql_clauses():
    """Verify that PostgresRepo query methods include application_status filters."""
    import inspect
    from jobradar.adapters.storage.postgres_repo import PostgresRepository

    unnotified_source = inspect.getsource(PostgresRepository.get_unnotified_matches)
    assert "LOWER(j.application_status)" in unnotified_source

    near_misses_source = inspect.getsource(PostgresRepository.get_near_misses)
    assert "LOWER(j.application_status)" in near_misses_source

    closing_soon_source = inspect.getsource(PostgresRepository.get_closing_soon_matches)
    assert "LOWER(j.application_status)" in closing_soon_source


# ============================================================================
# 5. Web API Status Update & Sync Endpoints
# ============================================================================

@pytest.mark.anyio
async def test_api_update_job_status_pushes_to_notion():
    """Verify POST /api/jobs/{job_id}/status persists locally and invokes Notion client."""
    from jobradar.web.app import update_job_status, JobStatusUpdateRequest

    mock_job = Job(
        title="Staff SRE",
        company="Safaricom",
        url="https://safaricom.co.ke/careers/sre",
        location="Nairobi",
        description="Kubernetes reliability",
        source="direct",
    )
    mock_job.id = 55
    mock_job.application_status = "unapplied"

    mock_repo = MagicMock()
    mock_repo.get_job_by_id.return_value = mock_job
    def fake_update(job_id_or_fingerprint, status, **kwargs):
        mock_job.application_status = status
        if "notion_page_id" in kwargs:
            mock_job.notion_page_id = kwargs["notion_page_id"]
        return mock_job
    mock_repo.update_job_application_status.side_effect = fake_update

    mock_notion = MagicMock()
    mock_notion.is_configured.return_value = True
    mock_notion.create_application_page.return_value = "new_page_sre_55"

    with patch("jobradar.web.app.get_repository", return_value=mock_repo), \
         patch("jobradar.web.app.NotionClient", return_value=mock_notion):

        req = JobStatusUpdateRequest(status="Applied", notes="Submitted CV")
        res = await update_job_status(55, req)

        assert res["success"] is True
        assert res["notion_synced"] is True
        assert res["job"]["application_status"] == "Applied"
        assert res["job"]["notion_page_id"] == "new_page_sre_55"

        assert mock_repo.update_job_application_status.call_count == 2
        mock_notion.create_application_page.assert_called_once()


@pytest.mark.anyio
async def test_api_notion_sync_endpoint():
    """Verify POST /api/notion/sync triggers synchronization engine."""
    from jobradar.web.app import trigger_notion_sync

    mock_summary = {
        "notion_rows_scanned": 12,
        "synced_jobs": 3,
        "backfilled_links": 2,
    }

    mock_repo = MagicMock()
    mock_notion = MagicMock()
    mock_notion.is_configured.return_value = True

    with patch("jobradar.web.app.get_repository", return_value=mock_repo), \
         patch("jobradar.web.app.NotionClient", return_value=mock_notion), \
         patch("jobradar.web.app.sync_notion_with_repository", return_value=mock_summary):

        res = await trigger_notion_sync()
        assert res["success"] is True
        assert res["summary"]["synced_jobs"] == 3
        assert res["summary"]["backfilled_links"] == 2
