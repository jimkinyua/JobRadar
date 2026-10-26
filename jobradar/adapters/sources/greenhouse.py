"""Greenhouse Board REST API adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class GreenhouseSourceAdapter(BaseSourceAdapter):
    """Adapter for Greenhouse boards API."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        company = self.source_config.company_identifier or self.source_config.id
        url = self.source_config.url or f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        jobs_data = data.get("jobs", [])
        results: list[tuple[RawJob, Job]] = []

        for item in jobs_data:
            title = item.get("title", "").strip()
            if not title:
                continue

            job_url = item.get("absolute_url") or f"https://boards.greenhouse.io/{company}/jobs/{item.get('id')}"
            location_info = item.get("location", {})
            loc_str = location_info.get("name") if isinstance(location_info, dict) else str(location_info)
            loc_str = loc_str or "Remote"

            posted_date = None
            date_str = item.get("updated_at")
            if date_str:
                try:
                    posted_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except Exception:
                    posted_date = None

            content_html = item.get("content", "")
            desc_text = BeautifulSoup(content_html, "html.parser").get_text(separator=" ").strip() if content_html else title

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=item,
            )
            job = Job(
                title=title,
                company=company.replace("-", " ").title(),
                url=job_url,
                location=loc_str,
                description=desc_text,
                posted=posted_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
