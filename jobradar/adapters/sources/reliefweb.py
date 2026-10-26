"""ReliefWeb Humanitarian Jobs API adapter."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class ReliefWebSourceAdapter(BaseSourceAdapter):
    """
    Adapter for ReliefWeb API.
    Requires the RELIEFWEB_APPNAME environment variable to be set according to ReliefWeb terms of service.
    Skips cleanly with an informative warning if unset.
    """

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        appname = os.getenv("RELIEFWEB_APPNAME")
        if not appname:
            logger.warning(
                "ReliefWeb source '%s' skipped: RELIEFWEB_APPNAME environment variable is unset.",
                self.source_id,
            )
            return []

        sess = session or self.get_session()
        base_url = self.source_config.url or "https://api.reliefweb.int/v1/jobs"
        params = {
            "appname": appname,
            "limit": 50,
            "profile": "full",
            "filter[field]": "country.name",
            "filter[value]": "Kenya",
        }

        resp = sess.get(base_url, params=params, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        data_items = data.get("data", [])
        results: list[tuple[RawJob, Job]] = []

        for entry in data_items:
            fields = entry.get("fields", {})
            title = fields.get("title", "").strip()
            if not title:
                continue

            job_url = fields.get("url") or f"https://reliefweb.int/job/{entry.get('id')}"
            orgs = fields.get("source", [])
            company = orgs[0].get("name") if orgs else "NGO / Humanitarian"

            countries = fields.get("country", [])
            country_names = [c.get("name") for c in countries if c.get("name")]
            loc_str = ", ".join(country_names) or "Kenya"

            posted_date = None
            date_info = fields.get("date", {})
            created_str = date_info.get("created")
            closing_str = date_info.get("closing")

            if created_str:
                try:
                    posted_date = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    posted_date = None

            deadline_date = None
            if closing_str:
                try:
                    deadline_date = datetime.fromisoformat(closing_str.replace("Z", "+00:00"))
                except Exception:
                    deadline_date = None

            body_html = fields.get("body", "")
            desc_text = BeautifulSoup(body_html, "html.parser").get_text(separator=" ").strip() if body_html else title

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=entry,
            )
            job = Job(
                title=title,
                company=company,
                url=job_url,
                location=loc_str,
                description=desc_text,
                posted=posted_date,
                deadline=deadline_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
