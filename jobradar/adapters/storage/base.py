"""Abstract base repository for JobRadar storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from jobradar.domain.models import (
    RawJob,
    Job,
    ScoredJob,
    SourceRun,
    DiscoveredEmployer,
)


class BaseStorageRepository(ABC):
    """Abstract interface defining all database operations for JobRadar."""

    @abstractmethod
    def initialize_schema(self) -> None:
        """Create tables, indexes, and extensions if they do not exist."""
        pass

    @abstractmethod
    def save_raw_job(self, raw_job: RawJob) -> int:
        """Save a Bronze raw payload and return its generated ID."""
        pass

    @abstractmethod
    def upsert_job(self, job: Job) -> tuple[Job, bool]:
        """
        Upsert a normalized Silver job.
        If fingerprint exists, update last_seen and return (job, is_new=False).
        If new, insert and return (job, is_new=True).
        """
        pass

    @abstractmethod
    def save_scored_match(self, scored_job: ScoredJob) -> None:
        """Save or update a Gold analytical scored match."""
        pass

    @abstractmethod
    def get_unnotified_matches(self, limit: int = 15, min_score: Optional[float] = None) -> list[ScoredJob]:
        """Retrieve highest scoring matches (optionally >= min_score) not alerted yet."""
        pass


    @abstractmethod
    def mark_alert_sent(self, fingerprint: str, alert_time: Optional[datetime] = None) -> None:
        """Mark a job's match as alerted."""
        pass

    @abstractmethod
    def get_near_misses(self, days_back: int = 7) -> list[ScoredJob]:
        """Retrieve near-miss jobs (is_near_miss=True) from the past n days."""
        pass

    @abstractmethod
    def get_closing_soon_matches(self, days_ahead: int = 3) -> list[ScoredJob]:
        """Retrieve matches closing within days_ahead that have not received a deadline reminder."""
        pass

    @abstractmethod
    def mark_deadline_reminder_sent(self, fingerprint: str) -> None:
        """Record that a 3-day deadline alert was sent."""
        pass

    @abstractmethod
    def record_source_run(self, run: SourceRun) -> None:
        """Save execution metrics for source observability."""
        pass

    @abstractmethod
    def get_previous_source_run(self, source_id: str) -> Optional[SourceRun]:
        """Get the most recent run metrics for a source before the current run."""
        pass

    @abstractmethod
    def upsert_discovered_employer(self, employer: DiscoveredEmployer) -> tuple[DiscoveredEmployer, bool]:
        """Upsert a discovered employer by slug. Returns (employer, is_new)."""
        pass

    @abstractmethod
    def get_discovered_employers(self, status: Optional[str] = None) -> list[DiscoveredEmployer]:
        """List discovered employers optionally filtered by status ('new', 'approved', 'ignored')."""
        pass

    @abstractmethod
    def update_employer_status(self, employer_id: int, status: str) -> bool:
        """Update an employer's status (approved, ignored, etc.)."""
        pass

    @abstractmethod
    def get_all_jobs_for_rescore(self) -> list[Job]:
        """Fetch all stored silver jobs for re-scoring."""
        pass

    @abstractmethod
    def count_total_jobs(self) -> int:
        """Return total count of stored silver jobs."""
        pass

    @abstractmethod
    def get_job_by_id(self, job_id: int) -> Optional[Job]:
        """Fetch a job by its database ID."""
        pass

    @abstractmethod
    def get_job_by_url(self, url: str) -> Optional[Job]:
        """Fetch a job by canonical URL."""
        pass

    @abstractmethod
    def update_job_application_status(
        self,
        job_id_or_fingerprint: int | str,
        status: str,
        applied_at: Optional[datetime] = None,
        notion_page_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Job]:
        """Update a job's application tracking status and Notion metadata."""
        pass

    @abstractmethod
    def get_dashboard_jobs(
        self,
        track_id: Optional[str] = None,
        min_score: Optional[float] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        application_status: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Fetch ranked jobs with their scoring breakdowns for web presentation."""
        pass

    @abstractmethod
    def get_dashboard_stats(self) -> dict:
        """Fetch aggregate summary metrics for the web dashboard."""
        pass

    @abstractmethod
    def save_custom_source(self, source_data: dict[str, Any]) -> dict[str, Any]:
        """Insert or update a custom crawler source."""
        pass

    @abstractmethod
    def get_custom_sources(self) -> list[dict[str, Any]]:
        """List all user-added custom crawler sources."""
        pass

    @abstractmethod
    def toggle_custom_source(self, source_id: str, enabled: bool) -> bool:
        """Enable or pause a custom crawler source."""
        pass

    @abstractmethod
    def delete_custom_source(self, source_id: str) -> bool:
        """Delete a custom crawler source."""
        pass

