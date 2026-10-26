"""ATS Sniffer - Discovers hiring systems (Greenhouse, Lever, SmartRecruiters, Workable, JazzHR, Workday)."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse
from jobradar.domain.models import DiscoveredEmployer

# Regex patterns to detect supported Applicant Tracking Systems (ATS)
ATS_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "smartrecruiters",
        re.compile(
            r"https?://(?:careers|jobs|api)\.smartrecruiters\.com/(?:v1/companies/)?([a-zA-Z0-9_\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "greenhouse",
        re.compile(
            r"https?://(?:boards|job-boards|boards-api)\.greenhouse\.io/(?:v1/boards/)?([a-zA-Z0-9_\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "lever",
        re.compile(
            r"https?://(?:jobs|api)\.lever\.co/(?:v0/postings/)?([a-zA-Z0-9_\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "workable",
        re.compile(
            r"https?://apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-zA-Z0-9_\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "jazzhr",
        re.compile(
            r"https?://([a-zA-Z0-9_\-]+)\.applytojob\.com",
            re.IGNORECASE,
        ),
    ),
    (
        "workday",
        re.compile(
            r"https?://([a-zA-Z0-9_\-]+)\.(?:wd[0-9]*\.)?myworkdayjobs\.com",
            re.IGNORECASE,
        ),
    ),
]


def detect_ats_employer(url: str, company_hint: Optional[str] = None) -> Optional[DiscoveredEmployer]:
    """
    Sniff a URL to determine if it is hosted on a supported ATS.
    Extracts the ATS system name and employer slug.
    """
    if not url:
        return None

    clean_url = url.strip()
    for system, pattern in ATS_PATTERNS:
        match = pattern.search(clean_url)
        if match:
            slug = match.group(1).lower().strip()
            # Ignore generic non-company slugs
            if slug in ("jobs", "apply", "search", "careers", "api", "widget", "v1"):
                continue

            company_name = company_hint.strip() if company_hint else slug.replace("-", " ").title()
            return DiscoveredEmployer(
                company=company_name,
                system=system,
                slug=slug,
            )

    return None
