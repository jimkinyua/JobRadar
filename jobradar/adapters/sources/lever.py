"""Lever Postings REST API adapter."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
import requests
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class LeverSourceAdapter(BaseSourceAdapter):
    """Adapter for Lever postings API."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        company = self.source_config.company_identifier or self.source_config.id
        url = self.source_config.url or f"https://api.lever.co/v0/postings/{company}?mode=json"

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        postings = resp.json()

        results: list[tuple[RawJob, Job]] = []
        for item in postings:
            title = item.get("text", "").strip()
            if not title:
                continue

            job_url = item.get("hostedUrl") or item.get("applyUrl") or url
            cats = item.get("categories", {})
            loc_str = cats.get("location") or "Remote"
            commitment = cats.get("commitment", "")
            if commitment and commitment not in loc_str:
                loc_str = f"{loc_str} ({commitment})"

            posted_date = None
            created_at = item.get("createdAt")
            if created_at and isinstance(created_at, (int, float)):
                try:
                    posted_date = datetime.fromtimestamp(created_at / 1000.0, tz=timezone.utc)
                except Exception:
                    posted_date = None

            desc = item.get("descriptionPlain") or item.get("description") or title

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
                description=desc,
                posted=posted_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
