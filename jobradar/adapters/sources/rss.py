"""Generic RSS 2.0 and Atom XML feed adapter."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.domain.models import Job, RawJob

logger = logging.getLogger(__name__)


def _parse_xml_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return None


class RssSourceAdapter(BaseSourceAdapter):
    """Adapter for generic RSS and Atom job feeds."""

    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        sess = session or self.get_session()
        url = self.source_config.url
        if not url:
            raise ValueError(f"RSS source '{self.source_id}' has no configured url.")

        resp = sess.get(url, timeout=self.crawler_config.request_timeout_seconds)
        resp.raise_for_status()
        xml_text = resp.text

        root = ET.fromstring(xml_text)
        results: list[tuple[RawJob, Job]] = []

        # 1. RSS 2.0: <channel><item>
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")

        # 2. Atom 1.0: <feed><entry>
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall("atom:entry", ns) or root.findall(".//entry")

        for item in items:
            # Title
            title_elem = item.find("title")
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            if not title:
                continue

            # Link
            link_elem = item.find("link")
            job_url = ""
            if link_elem is not None:
                job_url = link_elem.attrib.get("href") or (link_elem.text or "").strip()
            if not job_url:
                guid_elem = item.find("guid")
                if guid_elem is not None and guid_elem.text and guid_elem.text.startswith("http"):
                    job_url = guid_elem.text.strip()
            job_url = job_url or url

            # PubDate
            pub_date = None
            date_elem = item.find("pubDate")
            if date_elem is None:
                date_elem = item.find("published")
            if date_elem is None:
                date_elem = item.find("updated")

            if date_elem is not None and date_elem.text:
                pub_date = _parse_xml_date(date_elem.text.strip())

            # Description / Content
            desc_elem = item.find("description")
            if desc_elem is None:
                desc_elem = item.find("summary")
            if desc_elem is None:
                desc_elem = item.find("content")

            desc_html = desc_elem.text.strip() if (desc_elem is not None and desc_elem.text) else ""
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator=" ").strip() if desc_html else title

            # Company inference (often formatted as "Company: Title" or in <dc:creator>)
            company = self.source_name
            dc_creator = item.find("{http://purl.org/dc/elements/1.1/}creator")
            if dc_creator is not None and dc_creator.text:
                company = dc_creator.text.strip()
            elif ":" in title and len(title.split(":")[0]) < 40:
                parts = title.split(":", 1)
                company = parts[0].strip()
                title = parts[1].strip()

            raw = RawJob(
                source=self.source_id,
                source_url=job_url,
                payload=xml_text[:500],  # snapshot representation
            )
            job = Job(
                title=title,
                company=company,
                url=job_url,
                location="Remote / Nairobi",
                description=desc_text,
                posted=pub_date,
                source=self.source_id,
            )
            results.append((raw, job))

        return results
