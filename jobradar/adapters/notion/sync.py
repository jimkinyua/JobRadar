"""
Bidirectional Synchronization Engine between JobRadar and Notion Job Applications.
Implements fuzzy company and role matching to link manual Notion rows with crawled jobs.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from jobradar.adapters.notion.client import NotionClient
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.domain.models import Job

logger = logging.getLogger(__name__)

# Common business suffixes and modifiers to strip during company normalization
COMPANY_STOPWORDS = {
    "ltd", "limited", "inc", "llc", "plc", "corp", "corporation", "group",
    "services", "technologies", "technology", "solutions", "kenya", "africa",
    "east africa", "solar", "credit", "bank",
}

# Generic title modifiers
ROLE_MODIFIERS = {
    "senior", "lead", "principal", "staff", "junior", "mid", "intermediate",
    "expert", "specialist", "experienced", "role", "position", "vacancy",
}


def normalize_company_name(name: str) -> str:
    """Normalize company name by stripping legal entities, noise words, and symbols."""
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\s-]", " ", name.lower()).strip()
    words = cleaned.split()
    filtered = [w for w in words if w not in COMPANY_STOPWORDS]
    result = " ".join(filtered) if filtered else cleaned
    return re.sub(r"\s+", " ", result).strip()


def normalize_role_tokens(title: str) -> set[str]:
    """Extract key domain tokens from a job title for fuzzy matching."""
    if not title:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", title.lower()).strip()
    tokens = {w for w in cleaned.split() if len(w) > 1 and w not in ROLE_MODIFIERS}
    return tokens


def is_company_match(comp1: str, comp2: str) -> bool:
    """Check if two company names represent the same organization."""
    n1 = normalize_company_name(comp1)
    n2 = normalize_company_name(comp2)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    if len(n1) >= 4 and len(n2) >= 4:
        if n1 in n2 or n2 in n1:
            return True
    return False


def is_role_match(role1: str, role2: str) -> bool:
    """Check if two job titles refer to the same position via token overlap."""
    t1 = normalize_role_tokens(role1)
    t2 = normalize_role_tokens(role2)
    if not t1 or not t2:
        return False
    overlap = t1.intersection(t2)
    # If the smaller set is a subset of the larger set, or high Jaccard index
    shorter_len = min(len(t1), len(t2))
    if len(overlap) >= max(1, shorter_len):
        return True
    jaccard = len(overlap) / float(len(t1.union(t2)))
    return jaccard >= 0.5


def find_matching_job(
    notion_row: dict[str, Any],
    jobs: list[Job],
    url_index: dict[str, Job],
) -> Optional[Job]:
    """
    Attempt to find an existing JobRadar job matching a Notion row.
    1. Exact URL match (if Notion row has Job Link).
    2. Fuzzy match on Company + Role title tokens.
    """
    notion_link = (notion_row.get("job_link") or "").strip()
    if notion_link and notion_link in url_index:
        return url_index[notion_link]

    notion_comp = notion_row.get("company", "").strip()
    notion_role = notion_row.get("role", "").strip()

    if not notion_comp or not notion_role:
        return None

    # Search through jobs for company match + role match
    for job in jobs:
        if is_company_match(notion_comp, job.company) and is_role_match(notion_role, job.title):
            return job

    return None


def sync_notion_with_repository(
    notion_client: NotionClient,
    repo: BaseStorageRepository,
) -> dict[str, int]:
    """
    Execute full two-way synchronization between Notion and JobRadar.
    1. Pull all pages from Notion Job Applications.
    2. Match each row with local jobs (by URL or fuzzy company/role).
    3. Update local job status, applied timestamp, and notion_page_id.
    4. Backfill job link into Notion if manual Notion row lacked a URL.
    """
    summary = {
        "notion_rows_scanned": 0,
        "synced_jobs": 0,
        "backfilled_links": 0,
    }

    if not notion_client.is_configured():
        logger.info("Notion sync skipped: Client not configured.")
        return summary

    notion_rows = notion_client.query_database()
    summary["notion_rows_scanned"] = len(notion_rows)

    if not notion_rows:
        return summary

    all_jobs = repo.get_all_jobs_for_rescore()
    url_index = {j.url.strip(): j for j in all_jobs if j.url}

    for row in notion_rows:
        matched_job = find_matching_job(row, all_jobs, url_index)
        if not matched_job:
            continue

        notion_status = row.get("status") or "Applied"
        page_id = row.get("page_id")
        notes = row.get("notes")
        date_applied_str = row.get("date_applied")
        applied_at = None
        if date_applied_str:
            try:
                applied_at = datetime.fromisoformat(date_applied_str).replace(tzinfo=timezone.utc)
            except Exception:
                applied_at = datetime.now(timezone.utc)

        # Update local JobRadar status
        repo.update_job_application_status(
            job_id_or_fingerprint=matched_job.fingerprint,
            status=notion_status,
            applied_at=applied_at,
            notion_page_id=page_id,
            notes=notes,
        )
        summary["synced_jobs"] += 1

        # If Notion manual row had no job link, backfill it from JobRadar!
        if not row.get("job_link") and matched_job.url and page_id:
            updated = notion_client.update_application_page(page_id=page_id, job_link=matched_job.url)
            if updated:
                summary["backfilled_links"] += 1

    logger.info("Notion two-way sync completed: %s", summary)
    return summary
