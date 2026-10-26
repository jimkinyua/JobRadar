"""Workable public widget API adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class WorkableSourceAdapter(BaseSourceAdapter):
    """Adapter for Workable careers widget API."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        company = self.source_config.company_identifier or self.source_config.id
        url = self.source_config.url or f"https://apply.workable.com/api/v1/widget/accounts/{company}"

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        jobs_list = data.get("jobs", []) if isinstance(data, dict) else []
        results: list[tuple[RawJob, Job]] = []

        for item in jobs_list:
            title = item.get("title", "").strip()
            if not title:
                continue

            shortcode = item.get("shortcode")
            job_url = item.get("url") or f"https://apply.workable.com/{company}/j/{shortcode}/"
            city = item.get("city", "")
            country = item.get("country", "")
            telecommute = item.get("telecommute", False)
            loc_parts = [p for p in (city, country) if p]
            if telecommute:
                loc_parts.append("Remote")
            loc_str = ", ".join(loc_parts) or "Remote"

            posted_date = None
            date_str = item.get("published_on") or item.get("created_at")
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
                company=company.replace("-", " ").title(),
                url=job_url,
                location=loc_str,
                description=desc_text,
                posted=posted_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
