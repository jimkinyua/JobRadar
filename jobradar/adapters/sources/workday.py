"""
Workday ATS public CXS JSON API source adapter.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import requests
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.config import SourceConfig, CrawlerConfig
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class WorkdaySourceAdapter(BaseSourceAdapter):
    """Adapter fetching vacancies from Workday public CXS JSON endpoints."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        search_text = "Nairobi"
        if hasattr(self.source_config, "selectors") and self.source_config.selectors:
            search_text = self.source_config.selectors.get("search_text", "Nairobi")

        parts = self.source_config.url.split("/wday/cxs/")
        base_portal = parts[0]
        portal_slug = parts[1].split("/jobs")[0].split("/")[-1]
        job_base_url = f"{base_portal}/{portal_slug}"

        payload = {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": search_text,
        }

        resp = sess.post(
            self.source_config.url,
            json=payload,
            headers={
                "User-Agent": self.crawler_config.user_agent,
                "Accept": "application/json",
            },
            timeout=self.crawler_config.request_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[tuple[RawJob, Job]] = []
        for item in data.get("jobPostings", []):
            title = (item.get("title") or "").strip()
            ext_path = item.get("externalPath") or ""
            job_url = f"{job_base_url}{ext_path}" if ext_path else self.source_config.url
            loc = (item.get("locationsText") or "Nairobi, Kenya").strip()
            bullet_fields = item.get("bulletFields") or []
            desc = f"{title}. Location: {loc}. Info: {', '.join(bullet_fields)}"

            raw_job = RawJob(
                source=self.source_config.id,
                source_url=job_url,
                payload=item,
            )
            job = Job(
                title=title,
                company=self.source_config.name,
                url=job_url,
                location=loc,
                description=desc,
                source=self.source_config.id,
            )
            results.append((raw_job, job))

        logger.info(f"Workday source '{self.source_config.id}' fetched {len(results)} jobs (search: '{search_text}')")
        return results
