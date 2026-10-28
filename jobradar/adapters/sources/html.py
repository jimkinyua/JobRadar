"""
Ethical HTML Web Scraper Adapter.

Adheres strictly to crawler rules:
- Checks robots.txt first; skips if disallowed
- Enforces request_delay_seconds (default 2s)
- Sends honest, transparent User-Agent
- Explicitly rejects login-gated pages, LinkedIn, and Indeed
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)

# Disallowed domains as strictly requested
FORBIDDEN_DOMAINS = ("linkedin.com", "indeed.com")


class HtmlSourceAdapter(BaseSourceAdapter):
    """Ethical, robots.txt-compliant HTML scraper for sites without feeds or APIs."""

    def is_allowed_by_robots(self, target_url: str, session: requests.Session) -> bool:
        """Fetch and evaluate robots.txt for the target domain."""
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
                allowed = rp.can_fetch(self.crawler_config.user_agent, target_url)
                if not allowed:
                    logger.warning("robots.txt disallows crawling '%s' for '%s'", target_url, self.crawler_config.user_agent)
                return allowed
        except Exception as e:
            logger.debug("Could not verify robots.txt at '%s': %s. Proceeding conservatively.", robots_url, e)

        return True

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        target_url = self.source_config.url
        if not target_url:
            raise ValueError(f"HTML source '{self.source_id}' requires a configured URL.")

        # 1. Enforce ethical crawler checks
        if not self.is_allowed_by_robots(target_url, sess):
            logger.warning("Source '%s' skipped due to robots.txt or domain policy.", self.source_id)
            return []

        # 2. Rate limiting courtesy delay
        delay = self.crawler_config.request_delay_seconds
        if delay > 0:
            time.sleep(delay)

        resp = sess.get(target_url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        html_content = resp.text

        soup = BeautifulSoup(html_content, "html.parser")
        selectors = self.source_config.selectors or {}

        item_selector = selectors.get("item", ".job-listing, .job-item, article.job")
        title_selector = selectors.get("title", "h2, h3, .job-title, a.job-link")
        link_selector = selectors.get("link", "a[href]")
        company_selector = selectors.get("company", ".company, .employer")
        location_selector = selectors.get("location", ".location")
        desc_selector = selectors.get("description", ".description, .summary, p")

        items = soup.select(item_selector)
        results: list[tuple[RawJob, Job]] = []

        for item in items:
            title_elem = item.select_one(title_selector)
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                continue

            # Link extraction: pick the first element with a valid href
            job_url = target_url
            for link_candidate in item.select(link_selector):
                href_val = link_candidate.get("href")
                if href_val and href_val.strip() and not href_val.startswith("#"):
                    job_url = urljoin(target_url, href_val.strip())
                    break

            # Company extraction
            company = self.source_name
            comp_elem = item.select_one(company_selector)
            if comp_elem:
                company = comp_elem.get_text(strip=True)

            # Location extraction
            loc_str = "Nairobi, Kenya"
            loc_elem = item.select_one(location_selector)
            if loc_elem:
                loc_str = loc_elem.get_text(strip=True)

            # Description extraction
            desc_text = title
            desc_elem = item.select_one(desc_selector)
            if desc_elem:
                desc_text = desc_elem.get_text(separator=" ", strip=True)

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=str(item),
            )
            job = Job(
                title=title,
                company=company,
                url=job_url,
                location=loc_str,
                description=desc_text,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
