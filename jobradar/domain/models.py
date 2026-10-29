"""
Domain models and schema contracts for JobRadar.
Follows the Medallion Data Engineering architecture:
- RawJob: Bronze layer (untouched raw payloads for auditability and replay)
- Job: Silver layer (standardized, validated, deduplicated entities)
- ScoredJob / ScoreBreakdown: Gold layer (curated, scored, and notification-ready)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator


def normalize_text(text: str) -> str:
    """Normalize text by converting to lower case, stripping punctuation, and collapsing whitespace."""
    if not text:
        return ""
    # Remove special punctuation but keep alphanumeric and spaces
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    # Collapse multiple whitespaces
    return re.sub(r"\s+", " ", cleaned).strip()


def generate_fingerprint(company: str, title: str) -> str:
    """
    Generate an immutable, deterministic SHA-256 fingerprint for entity deduplication.
    Based on normalized company name and normalized title.
    """
    norm_comp = normalize_text(company)
    norm_title = normalize_text(title)
    seed = f"{norm_comp}::{norm_title}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


# ==============================================================================
# Bronze Layer: Raw Ingestion
# ==============================================================================
class RawJob(BaseModel):
    """Immutable audit representation of untouched data fetched from external sources."""
    id: Optional[int] = None
    source: str
    source_url: str
    payload: str | dict[str, Any]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# Silver Layer: Standardized & Deduplicated Job Entity
# ==============================================================================
class Job(BaseModel):
    """
    Normalized, validated job entity.
    All source adapters map their disparate raw data into this canonical schema.
    """
    title: str = Field(..., min_length=2, description="Job title")
    company: str = Field(..., min_length=1, description="Hiring company or organization")
    url: str = Field(..., description="Canonical listing or application URL")
    location: str = Field(default="Nairobi, Kenya", description="Job location or Remote tag")
    description: str = Field(default="", description="Cleaned job description text")
    posted: Optional[datetime] = Field(default=None, description="Date job was published")
    deadline: Optional[datetime] = Field(default=None, description="Application closing date")
    source: str = Field(..., description="Identifier of the ingestion source")
    raw_id: Optional[int] = Field(default=None, description="Foreign key to Bronze raw_jobs table")
    fingerprint: str = Field(default="", description="Deduplication key: sha256(company + title)")
    id: Optional[int] = Field(default=None, description="Database primary key")
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_closed: bool = Field(default=False, description="Marked true when listing disappears")
    application_status: str = Field(default="unapplied", description="Application tracking status: unapplied, to_apply, applied, screening, interview, final_round, offer, rejected, no_response, withdrawn")
    applied_at: Optional[datetime] = Field(default=None, description="Timestamp when applied")
    notion_page_id: Optional[str] = Field(default=None, description="Notion page UUID in Job Applications database")
    notion_synced_at: Optional[datetime] = Field(default=None, description="Timestamp of last bidirectional Notion sync")
    application_notes: Optional[str] = Field(default=None, description="User notes or interview remarks")


    def model_post_init(self, __context: Any) -> None:
        """Automatically populate fingerprint if not provided."""
        if not self.fingerprint:
            self.fingerprint = generate_fingerprint(self.company, self.title)

    @field_validator("title", "company", "location", mode="before")
    @classmethod
    def clean_strings(cls, v: Any) -> str:
        """Strip extra whitespaces and newlines from short string fields."""
        if isinstance(v, str):
            return " ".join(v.split()).strip()
        return str(v) if v is not None else ""


# ==============================================================================
# Gold Layer: Multi-Track Scoring & Analytics
# ==============================================================================
class TrackScore(BaseModel):
    """Score evaluation for an individual persona track."""
    track_id: str
    track_name: str
    score: float
    matched_keywords: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    """Granular, explainable breakdown of how a job was scored."""
    best_track_id: str
    best_track_name: str
    track_score: float
    location_bonus: float = 0.0
    matched_locations: list[str] = Field(default_factory=list)
    seniority_bonus: float = 0.0
    matched_seniority: list[str] = Field(default_factory=list)
    penalties: float = 0.0
    matched_penalties: list[str] = Field(default_factory=list)
    final_score: float
    is_match: bool
    is_near_miss: bool
    details: str = Field(default="", description="Human-readable audit log summary")


class AICopilotInsight(BaseModel):
    """AI evaluation of a high-scoring job match against candidate profile."""
    semantic_fit_score: int = Field(default=80, ge=0, le=100, description="Match percentage 0-100")
    fit_rationale: str = Field(description="Explanation of why the job matches the candidate profile")
    key_strengths: list[str] = Field(default_factory=list, description="Candidate skills aligned with role")
    skill_gaps: list[str] = Field(default_factory=list, description="Missing tools or requirements")
    tailored_pitch: str = Field(description="Custom resume bullet or pitch crafted for this job")


class ExtractedJobItem(BaseModel):
    """Structured job entity extracted by LLM from raw HTML / unstructured page text."""
    title: str = Field(..., min_length=2)
    url: str = Field(...)
    location: Optional[str] = Field(default="Nairobi, Kenya")
    summary: Optional[str] = Field(default="")
    deadline: Optional[str] = Field(default=None)


class ScoredJob(BaseModel):
    """A job paired with its analytical evaluation, optional AI insights, and notification status."""
    job: Job
    score_breakdown: ScoreBreakdown
    ai_insight: Optional[AICopilotInsight] = None
    alert_sent_at: Optional[datetime] = None


# ==============================================================================
# Employer Discovery & Observability Models
# ==============================================================================
class DiscoveredEmployer(BaseModel):
    """An employer identified via an ATS link (Greenhouse, Lever, SmartRecruiters, etc.)."""
    id: Optional[int] = None
    company: str
    system: str  # smartrecruiters | greenhouse | lever | workable | jazzhr | workday
    slug: str
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    jobs_seen: int = 1
    status: str = Field(default="new", description="'new', 'approved', or 'ignored'")


class SourceRun(BaseModel):
    """Observability record captured after every source execution."""
    id: Optional[int] = None
    source_id: str
    run_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    items_fetched: int = 0
    new_items: int = 0
    matches_found: int = 0
    error_message: Optional[str] = None
    status: str = Field(default="success", description="'success', 'partial', or 'failed'")
