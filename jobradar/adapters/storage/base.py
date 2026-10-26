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
    def get_unnotified_matches(self, limit: int = 15) -> list[ScoredJob]:
        """Retrieve highest scoring matches that have not been notified via Telegram yet."""
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
