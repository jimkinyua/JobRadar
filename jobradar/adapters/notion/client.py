"""
Notion API Client for JobRadar.
Handles CRUD operations on the Notion 'Job Applications' database.
Designed with graceful degradation and zero-crash error handling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
import requests

from jobradar.domain.models import Job

logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    """Wrapper around Notion REST API for managing Job Applications."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        database_id: Optional[str] = None,
        timeout: float = 12.0,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.database_id = database_id.strip() if database_id else None
        self.timeout = timeout
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            })

    def is_configured(self) -> bool:
        """Return True if both API key and Database ID are configured."""
        return bool(self.api_key and self.database_id)

    def query_database(self) -> list[dict[str, Any]]:
        """
        Query all pages in the Job Applications database.
        Automatically handles Notion pagination via start_cursor.
        Returns list of parsed application dictionaries.
        """
        if not self.is_configured():
            logger.info("Notion sync skipped: Notion credentials not configured.")
            return []

        url = f"{NOTION_API_URL}/databases/{self.database_id}/query"
        pages: list[dict[str, Any]] = []
        has_more = True
        next_cursor: Optional[str] = None

        try:
            while has_more:
                payload: dict[str, Any] = {"page_size": 100}
                if next_cursor:
                    payload["start_cursor"] = next_cursor

                resp = self.session.post(url, json=payload, timeout=self.timeout)
                if resp.status_code != 200:
                    logger.error(
                        "Notion database query failed (HTTP %s): %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    break

                data = resp.json()
                results = data.get("results", [])
                for page in results:
                    parsed = self._parse_page(page)
                    if parsed:
                        pages.append(parsed)

                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")

        except Exception as e:
            logger.error("Error querying Notion database: %s", e)
            return []

        return pages

    def create_application_page(
        self,
        job: Job,
        status: str = "Applied",
        notes: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new row in the Notion Job Applications database.
        Returns the created Notion page ID, or None on failure.
        """
        if not self.is_configured():
            logger.info("Notion page creation skipped: Notion credentials not configured.")
            return None

        url = f"{NOTION_API_URL}/pages"
        now_date = datetime.now().date().isoformat()

        # Build properties mapped to the user's Notion schema
        properties: dict[str, Any] = {
            "Role": {
                "title": [{"text": {"content": job.title[:200]}}]
            },
            "Company": {
                "rich_text": [{"text": {"content": job.company[:100]}}]
            },
            "Status": {
                "status": {"name": status}
            },
        }

        if status.lower() in ("applied", "screening", "interview", "final round", "offer"):
            properties["Date Applied"] = {"date": {"start": now_date}}

        if job.deadline:
            deadline_str = job.deadline.date().isoformat()
            properties["Closing Date"] = {"date": {"start": deadline_str}}

        if job.url:
            properties["Job Link"] = {"url": job.url}

        notes_content = notes or f"Ingested by JobRadar from {job.source}."
        properties["Notes"] = {
            "rich_text": [{"text": {"content": notes_content[:2000]}}]
        }

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code in (200, 201):
                page_id = resp.json().get("id")
                logger.info("Created Notion application page %s for '%s at %s'", page_id, job.title, job.company)
                return page_id
            
            # If Notion rejects 'status' for Status (e.g., if Status is a select property), retry with select format
            if resp.status_code == 400 and "select" in resp.text.lower():
                properties["Status"] = {"select": {"name": status}}
                resp = self.session.post(url, json=payload, timeout=self.timeout)
                if resp.status_code in (200, 201):
                    page_id = resp.json().get("id")
                    logger.info("Created Notion page %s with select status for '%s'", page_id, job.title)
                    return page_id

            logger.error("Failed to create Notion page (HTTP %s): %s", resp.status_code, resp.text[:300])
            return None
        except Exception as e:
            logger.error("Exception while creating Notion page: %s", e)
            return None

    def update_application_page(
        self,
        page_id: str,
        status: Optional[str] = None,
        job_link: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update an existing page in Notion.
        Returns True if successful, False otherwise.
        """
        if not self.is_configured() or not page_id:
            return False

        url = f"{NOTION_API_URL}/pages/{page_id}"
        properties: dict[str, Any] = {}

        if status:
            properties["Status"] = {"status": {"name": status}}
        if job_link:
            properties["Job Link"] = {"url": job_link}
        if notes:
            properties["Notes"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}

        if not properties:
            return True

        payload = {"properties": properties}

        try:
            resp = self.session.patch(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                logger.info("Updated Notion page %s", page_id)
                return True

            # Retry with select property if status rejected
            if status and resp.status_code == 400 and "select" in resp.text.lower():
                properties["Status"] = {"select": {"name": status}}
                resp = self.session.patch(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    return True

            logger.error("Failed to update Notion page %s (HTTP %s): %s", page_id, resp.status_code, resp.text[:300])
            return False
        except Exception as e:
            logger.error("Exception updating Notion page %s: %s", page_id, e)
            return False

    def _parse_page(self, page: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Extract structured fields from a Notion raw page object."""
        try:
            page_id = page.get("id")
            props = page.get("properties", {})

            # 1. Role (title)
            role_prop = props.get("Role") or props.get("role") or props.get("Name")
            role_title = ""
            if role_prop and role_prop.get("title"):
                role_title = "".join(t.get("plain_text", "") for t in role_prop["title"]).strip()
            if not role_title:
                # Find any property of type title
                for p_val in props.values():
                    if isinstance(p_val, dict) and p_val.get("type") == "title" and p_val.get("title"):
                        role_title = "".join(t.get("plain_text", "") for t in p_val["title"]).strip()
                        break

            # 2. Company (rich_text or select)
            company_prop = props.get("Company") or props.get("company")
            company_name = ""
            if company_prop:
                p_type = company_prop.get("type")
                if p_type == "rich_text" and company_prop.get("rich_text"):
                    company_name = "".join(t.get("plain_text", "") for t in company_prop["rich_text"]).strip()
                elif p_type == "select" and company_prop.get("select"):
                    company_name = company_prop["select"].get("name", "").strip()

            # 3. Status (select or status)
            status_prop = props.get("Status") or props.get("status")
            status_name = "To apply"
            if status_prop:
                p_type = status_prop.get("type")
                if p_type == "select" and status_prop.get("select"):
                    status_name = status_prop["select"].get("name", "To apply")
                elif p_type == "status" and status_prop.get("status"):
                    status_name = status_prop["status"].get("name", "To apply")

            # 4. Job Link (url)
            link_prop = props.get("Job Link") or props.get("job_link") or props.get("Link")
            job_link = ""
            if link_prop and link_prop.get("url"):
                job_link = link_prop["url"].strip()

            # 5. Date Applied
            date_prop = props.get("Date Applied") or props.get("date_applied")
            date_applied = None
            if date_prop and date_prop.get("date") and date_prop["date"].get("start"):
                date_applied = date_prop["date"]["start"]

            # 6. Notes
            notes_prop = props.get("Notes") or props.get("notes")
            notes_text = ""
            if notes_prop and notes_prop.get("rich_text"):
                notes_text = "".join(t.get("plain_text", "") for t in notes_prop["rich_text"]).strip()

            return {
                "page_id": page_id,
                "role": role_title,
                "company": company_name,
                "status": status_name,
                "job_link": job_link,
                "date_applied": date_applied,
                "notes": notes_text,
                "last_edited_time": page.get("last_edited_time"),
            }
        except Exception as e:
            logger.warning("Failed to parse Notion page %s: %s", page.get("id"), e)
            return None
