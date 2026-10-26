"""Remotive Remote Jobs API adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class RemotiveSourceAdapter(BaseSourceAdapter):
    """Adapter for Remotive remote jobs API."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        url = self.source_config.url or "https://remotive.com/api/remote-jobs?category=software-dev"

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        jobs_list = data.get("jobs", []) if isinstance(data, dict) else []
        results: list[tuple[RawJob, Job]] = []

        for item in jobs_list:
            title = item.get("title", "").strip()
            if not title:
                continue

            company = item.get("company_name", "Remote Employer").strip()
            job_url = item.get("url", "")
            location = item.get("candidate_required_location") or "Remote / Worldwide"

            posted_date = None
            date_str = item.get("publication_date")
            if date_str:
                try:
                    posted_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except Exception:
                    posted_date = None

            desc_html = item.get("description", "")
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator=" ").strip() if desc_html else title

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=item,
            )
            job = Job(
                title=title,
                company=company,
                url=job_url,
                location=location,
                description=desc_text,
                posted=posted_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
