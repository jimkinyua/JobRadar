"""Comprehensive offline unit tests for source adapters and ATS sniffer."""

import json
from unittest.mock import MagicMock
import pytest
from jobradar.config import SourceConfig, CrawlerConfig
from jobradar.adapters.sources.ats_sniffer import detect_ats_employer
from jobradar.adapters.sources.smartrecruiters import SmartRecruitersSourceAdapter
from jobradar.adapters.sources.greenhouse import GreenhouseSourceAdapter
from jobradar.adapters.sources.lever import LeverSourceAdapter
from jobradar.adapters.sources.workable import WorkableSourceAdapter
from jobradar.adapters.sources.remotive import RemotiveSourceAdapter
from jobradar.adapters.sources.reliefweb import ReliefWebSourceAdapter
from jobradar.adapters.sources.rss import RssSourceAdapter
from jobradar.adapters.sources.html import HtmlSourceAdapter


@pytest.fixture
def crawler_config():
    return CrawlerConfig(user_agent="JobRadarBot/1.0", request_delay_seconds=0.0)


def test_ats_sniffer_patterns():
    # SmartRecruiters
    sr = detect_ats_employer("https://jobs.smartrecruiters.com/deloitte/12345")
    assert sr is not None
    assert sr.system == "smartrecruiters"
    assert sr.slug == "deloitte"

    # Greenhouse
    gh = detect_ats_employer("https://boards.greenhouse.io/watu/jobs/99", "Watu Credit")
    assert gh is not None
    assert gh.system == "greenhouse"
    assert gh.slug == "watu"
    assert gh.company == "Watu Credit"

    # Lever
    lv = detect_ats_employer("https://jobs.lever.co/saasgroup/abc")
    assert lv is not None
    assert lv.system == "lever"
    assert lv.slug == "saasgroup"

    # Workable
    wa = detect_ats_employer("https://apply.workable.com/safaricom/j/XYZ/")
    assert wa is not None
    assert wa.system == "workable"
    assert wa.slug == "safaricom"

    # JazzHR
    jz = detect_ats_employer("https://watu.applytojob.com/apply/123")
    assert jz is not None
    assert jz.system == "jazzhr"
    assert jz.slug == "watu"

    # Workday
    wd = detect_ats_employer("https://path.wd3.myworkdayjobs.com/path_jobs/job/12")
    assert wd is not None
    assert wd.system == "workday"
    assert wd.slug == "path"


def test_smartrecruiters_adapter(crawler_config):
    mock_payload = {
        "content": [
            {
                "id": "sr-100",
                "name": "Senior Consultant - .NET Core & Cloud",
                "company": {"name": "Deloitte East Africa"},
                "location": {"city": "Nairobi", "country": "Kenya"},
                "releasedDate": "2026-10-20T10:00:00Z",
                "jobAd": {
                    "sections": {
                        "jobDescription": {
                            "text": "<p>Looking for a Senior .NET developer with Azure and SQL skills.</p>"
                        }
                    }
                },
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status.return_value = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    cfg = SourceConfig(id="deloitte_sr", name="Deloitte EA", type="smartrecruiters", company_identifier="deloitte")
    adapter = SmartRecruitersSourceAdapter(cfg, crawler_config)
    items, run = adapter.safe_fetch(mock_session)

    assert run.status == "success"
    assert len(items) == 1
    raw, job = items[0]
    assert job.title == "Senior Consultant - .NET Core & Cloud"
    assert job.company == "Deloitte East Africa"
    assert "Nairobi" in job.location
    assert "Azure" in job.description


def test_greenhouse_adapter(crawler_config):
    mock_payload = {
        "jobs": [
            {
                "id": 999,
                "title": "Cloud Solutions Developer",
                "absolute_url": "https://boards.greenhouse.io/path/jobs/999",
                "location": {"name": "Nairobi, Kenya"},
                "updated_at": "2026-10-21T08:00:00Z",
                "content": "<p>Develop ETL pipelines and Azure Functions.</p>",
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_payload
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    cfg = SourceConfig(id="path_gh", name="PATH", type="greenhouse", company_identifier="path")
    adapter = GreenhouseSourceAdapter(cfg, crawler_config)
    items, run = adapter.safe_fetch(mock_session)

    assert run.status == "success"
    assert len(items) == 1
    raw, job = items[0]
    assert job.title == "Cloud Solutions Developer"
    assert "ETL pipelines" in job.description


def test_reliefweb_skip_if_unset(crawler_config, monkeypatch):
    monkeypatch.delenv("RELIEFWEB_APPNAME", raising=False)
    cfg = SourceConfig(id="reliefweb", name="ReliefWeb", type="reliefweb")
    adapter = ReliefWebSourceAdapter(cfg, crawler_config)
    items, run = adapter.safe_fetch()

    assert items == []
    assert run.status == "partial"  # skipped cleanly


def test_rss_adapter(crawler_config):
    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>We Work Remotely</title>
            <item>
                <title>Davis &amp; Shirtliff: Tax Systems Integration Developer</title>
                <link>https://weworkremotely.com/jobs/davis-1</link>
                <description><![CDATA[<p>eTIMS and M-Pesa integration with Python and Go.</p>]]></description>
                <pubDate>Wed, 22 Oct 2026 12:00:00 +0000</pubDate>
            </item>
        </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.text = sample_rss
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    cfg = SourceConfig(id="wwr_rss", name="WWR", type="rss", url="https://weworkremotely.com/feed.rss")
    adapter = RssSourceAdapter(cfg, crawler_config)
    items, run = adapter.safe_fetch(mock_session)

    assert run.status == "success"
    assert len(items) == 1
    raw, job = items[0]
    assert job.title == "Tax Systems Integration Developer"
    assert job.company == "Davis & Shirtliff"
    assert "eTIMS" in job.description


def test_html_adapter_ethical_rules(crawler_config, monkeypatch):
    sample_html = """
    <html>
        <body>
            <div class="job-item">
                <h2 class="job-title"><a href="/jobs/101">Senior Data Engineer</a></h2>
                <span class="company">Britam</span>
                <span class="location">Nairobi</span>
                <p class="description">Kafka and SQL data pipelines.</p>
            </div>
        </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.text = sample_html
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    cfg = SourceConfig(
        id="kenyan_portal",
        name="Kenyan Portal",
        type="html",
        url="https://example-jobs.co.ke/tech",
        selectors={
            "item": ".job-item",
            "title": ".job-title",
            "link": "a[href]",
            "company": ".company",
            "location": ".location",
            "description": ".description",
        },
    )
    adapter = HtmlSourceAdapter(cfg, crawler_config)

    # Mock robots.txt check to allow
    monkeypatch.setattr(adapter, "is_allowed_by_robots", lambda url, sess: True)
    items, run = adapter.safe_fetch(mock_session)

    assert run.status == "success"
    assert len(items) == 1
    raw, job = items[0]
    assert job.title == "Senior Data Engineer"
    assert job.company == "Britam"
    assert job.url == "https://example-jobs.co.ke/jobs/101"


def test_fault_isolation_on_unhandled_error(crawler_config):
    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("DNS resolution failed for remote host")

    cfg = SourceConfig(id="broken_source", name="Broken Source", type="smartrecruiters", company_identifier="broken")
    adapter = SmartRecruitersSourceAdapter(cfg, crawler_config)

    items, run = adapter.safe_fetch(mock_session)

    # Must NOT raise, must return status failed and record the error message
    assert items == []
    assert run.status == "failed"
    assert "DNS resolution failed" in (run.error_message or "")
