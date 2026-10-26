"""SmartRecruiters REST API adapter."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


class SmartRecruitersSourceAdapter(BaseSourceAdapter):
    """Adapter for SmartRecruiters public posting API."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        company = self.source_config.company_identifier or self.source_config.id
        url = self.source_config.url or f"https://api.smartrecruiters.com/v1/companies/{company}/postings"

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()

        content_list = data.get("content", []) if isinstance(data, dict) else data
        results: list[tuple[RawJob, Job]] = []

        for item in content_list:
            posting_id = item.get("id")
            title = item.get("name", "").strip()
            if not title:
                continue

            company_info = item.get("company", {})
            company_name = company_info.get("name") if isinstance(company_info, dict) else company
            company_name = company_name or company.title()

            job_url = f"https://jobs.smartrecruiters.com/{company}/{posting_id}" if posting_id else url
            loc_data = item.get("location", {})
            city = loc_data.get("city", "")
            country = loc_data.get("country", "")
            loc_str = f"{city}, {country}".strip(", ") or "Nairobi, Kenya"

            # Parse date
            posted_date = None
            date_str = item.get("releasedDate") or item.get("createdOn")
            if date_str:
                try:
                    posted_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except Exception:
                    posted_date = None

            # Description if provided in summary or full ad
            desc_html = item.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", "")
            if not desc_html and "customField" in item:
                desc_html = str(item.get("customField"))
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator=" ").strip() if desc_html else title

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=item,
            )
            job = Job(
                title=title,
                company=company_name,
                url=job_url,
                location=loc_str,
                description=desc_text,
                posted=posted_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
