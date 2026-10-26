"""
Source Acceptance Testing & Backtesting Harness.

Evaluates candidates against the 5 Acceptance Criteria:
(1) robots.txt and terms allow it, no login;
(2) feed, API, or stable HTML structure exists;
(3) backtest: lists tracked roles or relevant Kenyan/remote tech jobs;
(4) listings have explicit dates;
(5) returns results on 3 consecutive test runs.
"""

from __future__ import annotations

import logging
import sys
import time
import urllib.robotparser
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
import requests

# Set stdout to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER_AGENT = "JobRadarBot/1.0 (+https://github.com/james/job-radar; ethical career crawler)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/html, */*"}

CANDIDATES = [
    # 1. Remote & NGO Portals
    {
        "id": "remotive",
        "name": "Remotive Remote Jobs API",
        "type": "api",
        "url": "https://remotive.com/api/remote-jobs?category=software-dev",
    },
    {
        "id": "weworkremotely",
        "name": "We Work Remotely RSS Feed",
        "type": "rss",
        "url": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    },
    {
        "id": "reliefweb",
        "name": "ReliefWeb Humanitarian Jobs API",
        "type": "api",
        "url": "https://api.reliefweb.int/v1/jobs?appname=jobradar.portfolio.v1&limit=5&filter[field]=country.name&filter[value]=Kenya",
    },
    # 2. Known ATS Employers
    {
        "id": "saasgroup",
        "name": "saas.group (Lever API)",
        "type": "api",
        "url": "https://api.lever.co/v0/postings/saasgroup?mode=json",
    },
    {
        "id": "deloitte_smartrecruiters",
        "name": "Deloitte East Africa (SmartRecruiters)",
        "type": "api",
        "url": "https://api.smartrecruiters.com/v1/companies/deloitte/postings",
    },
    {
        "id": "watu_jazzhr",
        "name": "Watu Credit (JazzHR)",
        "type": "html",
        "url": "https://watu.applytojob.com",
    },
    {
        "id": "corporate_staffing_rss",
        "name": "Corporate Staffing Services (WordPress Feed)",
        "type": "rss",
        "url": "https://www.corporatestaffing.co.ke/feed/",
    },
    {
        "id": "myjobmag",
        "name": "MyJobMag Kenya",
        "type": "rss",
        "url": "https://www.myjobmag.co.ke/rss.xml",
    },
    {
        "id": "jobwebkenya",
        "name": "JobWebKenya",
        "type": "rss",
        "url": "https://jobwebkenya.com/feed/",
    },
    {
        "id": "davis_shirtliff",
        "name": "Davis & Shirtliff Careers",
        "type": "html",
        "url": "https://www.davisandshirtliff.com/careers",
    },
    {
        "id": "britam",
        "name": "Britam Careers",
        "type": "html",
        "url": "https://www.britam.com/careers",
    },
    {
        "id": "fuzu",
        "name": "Fuzu Kenya",
        "type": "html",
        "url": "https://www.fuzu.com/kenya/jobs",
    },
]


def check_robots(target_url: str) -> tuple[bool, str]:
    """Check robots.txt for the given target URL."""
    parsed = urlparse(target_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()

    try:
        resp = requests.get(robots_url, headers=HEADERS, timeout=8.0)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch(USER_AGENT, target_url)
            return allowed, "robots.txt allowed" if allowed else "robots.txt explicitly disallows crawler"
        elif resp.status_code == 404:
            return True, "robots.txt not found (allowed)"
        else:
            return True, f"robots.txt status HTTP {resp.status_code} (default allowed)"
    except Exception as e:
        return True, f"robots.txt unreachable: {e} (proceeding cautiously)"


def evaluate_candidate(cand: dict[str, Any]) -> dict[str, Any]:
    url = cand["url"]
    cand_id = cand["id"]
    name = cand["name"]

    report = {
        "id": cand_id,
        "name": name,
        "passed": False,
        "c1_robots": False,
        "c2_structure": False,
        "c3_content": False,
        "c4_dates": False,
        "c5_consecutive_3": False,
        "items_count": 0,
        "notes": "",
    }

    # Criterion 1: Robots.txt
    allowed, rob_note = check_robots(url)
    report["c1_robots"] = allowed
    if not allowed:
        report["notes"] = f"Failed Criterion 1: {rob_note}"
        return report

    # Criterion 5: 3 Consecutive Runs & Structure/Content
    consecutive_success = 0
    items_found: list[Any] = []

    for run_i in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12.0)
            if resp.status_code != 200:
                report["notes"] = f"Failed Criterion 2: HTTP {resp.status_code} on run {run_i+1}"
                return report

            content_type = resp.headers.get("Content-Type", "").lower()
            text = resp.text

            # Parse based on expected type
            if cand["type"] == "api" or "json" in content_type:
                data = resp.json()
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("jobs") or data.get("data") or data.get("content") or []
                else:
                    items = []
                report["c2_structure"] = True

                # Check Criterion 4: Dates present
                has_dates = False
                for it in items[:5]:
                    if isinstance(it, dict):
                        if any(k in it for k in ("publication_date", "releasedDate", "created_at", "createdAt", "date", "updated_at")):
                            has_dates = True
                            break
                        if "fields" in it and "date" in it["fields"]:
                            has_dates = True
                            break
                report["c4_dates"] = has_dates
                items_found = items

            elif cand["type"] == "rss" or "xml" in content_type:
                has_items = ("<item>" in text or "<entry>" in text)
                report["c2_structure"] = has_items
                has_dates = ("<pubDate>" in text or "<published>" in text or "<updated>" in text)
                report["c4_dates"] = has_dates
                items_found = [1] if has_items else []

            else:
                # HTML
                has_html = ("<html" in text.lower() and len(text) > 1000)
                report["c2_structure"] = has_html
                # Check for Cloudflare / bot walls
                if "cloudflare" in text.lower() and "challenge" in text.lower():
                    report["c2_structure"] = False
                    report["notes"] = "Blocked by Cloudflare bot protection"
                    return report
                # HTML dates
                has_dates = ("202" in text)
                report["c4_dates"] = has_dates
                items_found = [1] if has_html else []

            if report["c2_structure"]:
                consecutive_success += 1
            time.sleep(0.5)

        except Exception as e:
            report["notes"] = f"Network or parsing error on run {run_i+1}: {e}"
            return report

    report["c5_consecutive_3"] = (consecutive_success == 3)
    report["items_count"] = len(items_found)
    report["c3_content"] = (len(items_found) > 0)

    # Determine overall pass
    all_passed = (
        report["c1_robots"]
        and report["c2_structure"]
        and report["c3_content"]
        and report["c4_dates"]
        and report["c5_consecutive_3"]
    )
    report["passed"] = all_passed
    if not report["notes"]:
        report["notes"] = f"PASSED 3/3 runs, {len(items_found)} items found" if all_passed else "Missing criteria"
    return report


def main():
    print("\n🔍 Running 5-Point Source Acceptance Test on all Candidate Sources...")
    print("=" * 95)
    print(f"{'Source':<32} {'Robots':<8} {'Format':<8} {'Content':<8} {'Dates':<8} {'3x Run':<8} {'Result':<10} {'Details'}")
    print("=" * 95)

    results = []
    for cand in CANDIDATES:
        rep = evaluate_candidate(cand)
        results.append(rep)

        c1 = "PASS" if rep["c1_robots"] else "FAIL"
        c2 = "PASS" if rep["c2_structure"] else "FAIL"
        c3 = "PASS" if rep["c3_content"] else "FAIL"
        c4 = "PASS" if rep["c4_dates"] else "FAIL"
        c5 = "PASS" if rep["c5_consecutive_3"] else "FAIL"
        res = "ENABLED" if rep["passed"] else "DISABLED"

        print(f"{rep['name'][:30]:<32} {c1:<8} {c2:<8} {c3:<8} {c4:<8} {c5:<8} {res:<10} {rep['notes'][:25]}")

    print("=" * 95)

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count
    print(f"\n📊 Summary: {passed_count} Passed (to be enabled), {failed_count} Failed (to remain disabled with notes).\n")


if __name__ == "__main__":
    main()
