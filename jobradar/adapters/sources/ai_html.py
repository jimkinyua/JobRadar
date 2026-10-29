"""
AI-Powered HTML Source Adapter.
Extracts structured job postings from arbitrary corporate career portals
using Gemini 2.0 Flash fallback when CSS selectors are absent or fail.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob
from jobradar.services.ai_service import AIService

logger = logging.getLogger(__name__)

FORBIDDEN_DOMAINS = ("linkedin.com", "indeed.com")


class AiHtmlSourceAdapter(BaseSourceAdapter):
    """Zero-code scraper that uses Gemini AI structured output to extract vacancies."""

    def __init__(self, source_config, crawler_config, ai_service: Optional[AIService] = None) -> None:
        super().__init__(source_config, crawler_config)
        self.ai_service = ai_service or AIService()

    def is_allowed_by_robots(self, target_url: str, session: requests.Session) -> bool:
        """Ethical robots.txt check."""
        parsed = urlparse(target_url)
        if any(forbidden in parsed.netloc.lower() for forbidden in FORBIDDEN_DOMAINS):
            logger.warning("Scraping forbidden domain '%s' is disallowed by policy.", parsed.netloc)
            return False

        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = session.get(robots_url, timeout=10.0)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                return rp.can_fetch(self.crawler_config.user_agent, target_url)
        except Exception:
            pass
        return True

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        target_url = self.source_config.url
        if not target_url:
            raise ValueError(f"AI HTML source '{self.source_id}' requires a configured URL.")

        if not self.is_allowed_by_robots(target_url, sess):
            logger.warning("Source '%s' skipped due to robots.txt policy.", self.source_id)
            return []

        delay = self.crawler_config.request_delay_seconds
        if delay > 0:
            time.sleep(delay)

        resp = sess.get(target_url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        html_content = resp.text

        # Extract readable text or clean HTML
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "svg", "nav", "footer", "iframe"]):
            tag.decompose()

        cleaned_text = soup.get_text(separator="\n", strip=True)

        # Send to Gemini AI for schema-constrained extraction
        extracted_items = self.ai_service.extract_jobs_from_unstructured_page(
            page_text=cleaned_text,
            base_url=target_url,
        )

        results: list[tuple[RawJob, Job]] = []
        for item in extracted_items:
            full_url = urljoin(target_url, item.url.strip())
            raw = RawJob(
                source=self.source_id,
                source_url=full_url,
                payload={"title": item.title, "url": full_url, "location": item.location, "summary": item.summary},
            )
            job = Job(
                title=item.title,
                company=self.source_name,
                url=full_url,
                location=item.location or "Nairobi, Kenya",
                description=item.summary or item.title,
                source=self.source_id,
            )
            results.append((raw, job))

        logger.info("AiHtmlSourceAdapter extracted %d jobs from '%s'", len(results), self.source_name)
        return results
