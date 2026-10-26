"""
HTML message formatters for Telegram alerts.
Strictly escapes dynamic input using html.escape to prevent Telegram parse errors.
"""

from __future__ import annotations

import html
from typing import Any
from jobradar.domain.models import ScoredJob, DiscoveredEmployer


def format_job_alert(scored: ScoredJob) -> str:
    """Format a single matched job alert using Telegram HTML parse mode."""
    job = scored.job
    breakdown = scored.score_breakdown

    esc_title = html.escape(job.title)
    esc_company = html.escape(job.company)
    esc_location = html.escape(job.location)
    esc_track = html.escape(breakdown.best_track_name)
    esc_url = html.escape(job.url, quote=True)

    deadline_str = ""
    if job.deadline:
        deadline_formatted = job.deadline.strftime("%d %b %Y")
        deadline_str = f"\n⏳ <b>Deadline:</b> {deadline_formatted}"

    score_val = f"{breakdown.final_score:.1f}"

    lines = [
        f"🎯 <b>{esc_title}</b>",
        f"🏢 <b>Company:</b> {esc_company}",
        f"📍 <b>Location:</b> {esc_location}",
        f"⭐ <b>Score:</b> {score_val} ({esc_track}){deadline_str}",
        f'🔗 <a href="{esc_url}">View Job Listing</a>',
    ]
    return "\n".join(lines)


def format_health_alert(unhealthy_sources: list[dict[str, Any]]) -> str:
    """Format consolidated source health warning message."""
    lines = [
        "⚠️ <b>Job-Radar Source Health Alert</b>",
        "The following ingestion issues were detected during the recent run:\n",
    ]

    for item in unhealthy_sources:
        esc_name = html.escape(item.get("name", "Unknown Source"))
        reason = html.escape(item.get("reason", "Unknown error"))
        lines.append(f"• <b>{esc_name}:</b> {reason}")

    return "\n".join(lines)


def format_near_miss_digest(near_misses: list[ScoredJob]) -> str:
    """Format weekly Monday near-miss digest."""
    lines = [
        "📋 <b>Weekly Near-Miss Digest</b>",
        "These listings scored just below your threshold in the past 7 days:\n",
    ]

    for item in near_misses:
        esc_title = html.escape(item.job.title)
        esc_company = html.escape(item.job.company)
        esc_url = html.escape(item.job.url, quote=True)
        score_val = f"{item.score_breakdown.final_score:.1f}"
        lines.append(
            f'• <b>{esc_title}</b> — {esc_company} (Score: {score_val}) <a href="{esc_url}">Link</a>'
        )

    return "\n".join(lines)


def format_deadline_reminder(scored: ScoredJob) -> str:
    """Format 3-day closing deadline reminder alert."""
    job = scored.job
    esc_title = html.escape(job.title)
    esc_company = html.escape(job.company)
    esc_url = html.escape(job.url, quote=True)
    deadline_str = job.deadline.strftime("%d %b %Y") if job.deadline else "In 3 days"

    lines = [
        "⏰ <b>Application Deadline Reminder!</b>",
        f"A previously matched role closes soon:",
        f"<b>{esc_title}</b> at {esc_company}",
        f"⏳ <b>Closes:</b> {deadline_str}",
        f'🔗 <a href="{esc_url}">Apply Now</a>',
    ]
    return "\n".join(lines)


def format_employer_spotted(employer: DiscoveredEmployer, matching_jobs: int) -> str:
    """Format notification when a new ATS employer is detected."""
    esc_company = html.escape(employer.company)
    esc_system = html.escape(employer.system.title())
    esc_slug = html.escape(employer.slug)
    emp_id = employer.id or "0"

    lines = [
        "🏢 <b>New Employer Spotted!</b>",
        f"Found <b>{esc_company}</b> using <b>{esc_system}</b> (slug: <code>{esc_slug}</code>).",
        f"Spotted across <b>{matching_jobs}</b> matching job(s).\n",
        f"Reply to monitor or dismiss:",
        f"<code>/add {emp_id}</code> — Watch employer directly",
        f"<code>/ignore {emp_id}</code> — Ignore this employer",
    ]
    return "\n".join(lines)
