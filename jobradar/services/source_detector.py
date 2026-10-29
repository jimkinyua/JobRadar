"""
Source Detector and Live Prober.
Analyzes user-provided career page URLs, automatically identifies ATS platforms
or RSS feeds, tests live extraction, and falls back to Gemini 2.0 Flash AI extractor.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

from jobradar.config import SourceConfig, CrawlerConfig
from jobradar.adapters.sources.ats_sniffer import detect_ats_employer
from jobradar.adapters.sources.factory import get_source_adapter
from jobradar.domain.models import Job

logger = logging.getLogger(__name__)


def probe_source(url: str, name: Optional[str] = None) -> dict[str, Any]:
    """
    Probes a career URL, auto-detects its ingestion type (ATS, RSS, HTML, AI),
    and executes a live test fetch returning sample extracted vacancies.
    """
    if not url or not url.strip().startswith(("http://", "https://")):
        return {"success": False, "error": "Please provide a valid URL starting with http:// or https://"}

    clean_url = url.strip()
    clean_name = (name or "").strip()

    # 1. Check for standard ATS URL patterns
    ats_detected = detect_ats_employer(clean_url, company_hint=clean_name)
    if ats_detected:
        system = ats_detected.system.lower()
        company = clean_name or ats_detected.company
        slug = ats_detected.slug

        if system == "greenhouse":
            target_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            stype = "greenhouse"
            label = "Greenhouse ATS API"
        elif system == "lever":
            target_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            stype = "lever"
            label = "Lever ATS API"
        elif system == "smartrecruiters":
            target_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            stype = "smartrecruiters"
            label = "SmartRecruiters ATS API"
        elif system == "workable":
            target_url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
            stype = "workable"
            label = "Workable ATS API"
        elif system == "workday":
            target_url = clean_url
            stype = "workday"
            label = "Workday Careers Portal"
        else:
            target_url = clean_url
            stype = "html"
            label = f"{system.title()} Portal"

        return _test_adapter_extraction(
            source_type=stype,
            url=target_url,
            name=company,
            type_label=label,
            company_id=slug,
        )

    # 2. Probe URL with HTTP GET
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(clean_url, headers=headers, timeout=12.0)
    except requests.exceptions.SSLError:
        return {"success": False, "error": "SSL Certificate verification failed on the target server."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to the domain. Check spelling and connectivity."}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Connection timed out after 12 seconds."}
    except Exception as e:
        return {"success": False, "error": f"Failed to fetch webpage: {str(e)}"}

    if resp.status_code == 403:
        return {
            "success": False,
            "error": "Access Forbidden (HTTP 403). This website is protected by Cloudflare/Akamai bot detection.",
        }
    elif resp.status_code == 404:
        return {"success": False, "error": "Page Not Found (HTTP 404). Please verify the career page URL."}
    elif resp.status_code >= 400:
        return {"success": False, "error": f"Target server returned HTTP {resp.status_code}."}

    content_type = resp.headers.get("Content-Type", "").lower()
    text = resp.text

    # Derive company name from domain if not provided
    if not clean_name:
        domain = urlparse(clean_url).netloc
        domain_parts = domain.replace("www.", "").split(".")
        clean_name = domain_parts[0].replace("-", " ").title() if domain_parts else "Custom Portal"

    # 3. Check for RSS Feed
    is_xml = "xml" in content_type or text.strip().startswith("<?xml") or "<rss" in text[:300]
    if is_xml:
        return _test_adapter_extraction(
            source_type="rss",
            url=clean_url,
            name=clean_name,
            type_label="RSS Job Feed",
        )

    soup = BeautifulSoup(text, "html.parser")

    # Check for RSS discovery tag inside HTML
    rss_link = soup.find("link", rel=lambda r: r and "alternate" in r, type=lambda t: t and "rss" in t)
    if rss_link and rss_link.get("href"):
        feed_url = urljoin(clean_url, rss_link["href"])
        return _test_adapter_extraction(
            source_type="rss",
            url=feed_url,
            name=clean_name,
            type_label="Discovered RSS Feed",
        )

    # 4. Check standard HTML selectors
    default_selectors = {
        "item": "article, .job-listing, .job-item, .career-item, .vacancy-item, tr.job, li.job",
        "title": "h2, h3, h4, .job-title, .title, a",
        "link": "a",
        "location": ".location",
        "description": "p, .summary, .description",
    }

    test_res = _test_adapter_extraction(
        source_type="html",
        url=clean_url,
        name=clean_name,
        type_label="Standard HTML Scraper",
        selectors=default_selectors,
    )

    if test_res["success"] and test_res.get("count", 0) > 0:
        return test_res

    # 5. Fallback to Gemini 2.0 Flash AI Extractor
    return _test_adapter_extraction(
        source_type="ai_html",
        url=clean_url,
        name=clean_name,
        type_label="✦ Gemini AI Auto-Extractor",
    )


def _test_adapter_extraction(
    source_type: str,
    url: str,
    name: str,
    type_label: str,
    company_id: Optional[str] = None,
    selectors: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Helper to instantiate adapter and test extraction of sample jobs."""
    source_cfg = SourceConfig(
        id=re.sub(r"[^a-z0-9_]", "_", name.lower().strip()) or "custom_source",
        name=name,
        type=source_type,
        url=url,
        company_identifier=company_id,
        selectors=selectors,
        enabled=True,
    )
    crawler_cfg = CrawlerConfig(
        request_delay_seconds=0,
        request_timeout_seconds=10.0,
    )

    try:
        adapter = get_source_adapter(source_cfg, crawler_cfg)
        items = adapter.fetch_jobs()

        sample_jobs = []
        for raw, job in items[:4]:
            sample_jobs.append({
                "title": job.title,
                "company": job.company or name,
                "location": job.location,
                "url": job.url,
                "description": job.description[:200] + "..." if len(job.description or "") > 200 else job.description,
            })

        return {
            "success": True,
            "id": source_cfg.id,
            "name": name,
            "type": source_type,
            "type_label": type_label,
            "url": url,
            "company_identifier": company_id,
            "selectors": selectors,
            "sample_jobs": sample_jobs,
            "count": len(sample_jobs),
        }
    except Exception as e:
        logger.warning("Adapter test extraction failed for %s (%s): %s", name, url, e)
        return {
            "success": False,
            "error": f"Failed extracting vacancies: {str(e)[:250]}",
        }
