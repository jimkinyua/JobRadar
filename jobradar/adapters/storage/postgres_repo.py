"""PostgreSQL implementation of the storage repository using psycopg 3 and ConnectionPool."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.domain.models import (
    RawJob,
    Job,
    ScoredJob,
    ScoreBreakdown,
    SourceRun,
    DiscoveredEmployer,
)


class PostgresRepository(BaseStorageRepository):
    """Production PostgreSQL storage adapter utilizing psycopg3 connection pooling."""

    def __init__(self, connection_url: str, min_size: int = 1, max_size: int = 10) -> None:
        self.connection_url = connection_url
        self.pool = ConnectionPool(
            conninfo=connection_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        self.initialize_schema()

    def close(self) -> None:
        """Close connection pool."""
        self.pool.close()

    def initialize_schema(self) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                # 1. Bronze Layer: raw_jobs
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS raw_jobs (
                        id BIGSERIAL PRIMARY KEY,
                        source VARCHAR(100) NOT NULL,
                        source_url TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )

                # 2. Silver Layer: jobs
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id BIGSERIAL PRIMARY KEY,
                        fingerprint VARCHAR(64) UNIQUE NOT NULL,
                        url TEXT UNIQUE NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        company VARCHAR(255) NOT NULL,
                        location VARCHAR(255) NOT NULL,
                        description TEXT NOT NULL,
                        posted_at TIMESTAMPTZ,
                        deadline_at TIMESTAMPTZ,
                        source VARCHAR(100) NOT NULL,
                        raw_id BIGINT REFERENCES raw_jobs(id) ON DELETE SET NULL,
                        first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        is_closed BOOLEAN DEFAULT FALSE
                    );
                    CREATE INDEX IF NOT EXISTS idx_pg_jobs_fingerprint ON jobs(fingerprint);
                    CREATE INDEX IF NOT EXISTS idx_pg_jobs_source ON jobs(source);
                    """
                )

                # 3. Gold Layer: scored_matches
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scored_matches (
                        id BIGSERIAL PRIMARY KEY,
                        job_fingerprint VARCHAR(64) UNIQUE NOT NULL REFERENCES jobs(fingerprint) ON DELETE CASCADE,
                        best_track_id VARCHAR(100) NOT NULL,
                        best_track_name VARCHAR(100) NOT NULL,
                        final_score NUMERIC(6, 2) NOT NULL,
                        is_match BOOLEAN NOT NULL,
                        is_near_miss BOOLEAN NOT NULL,
                        breakdown_json JSONB NOT NULL,
                        alert_sent_at TIMESTAMPTZ,
                        deadline_reminder_sent_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_pg_matches_score ON scored_matches(final_score DESC);
                    CREATE INDEX IF NOT EXISTS idx_pg_matches_alert ON scored_matches(alert_sent_at);
                    """
                )

                # 4. Observability: source_runs
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS source_runs (
                        id BIGSERIAL PRIMARY KEY,
                        source_id VARCHAR(100) NOT NULL,
                        run_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        items_fetched INTEGER DEFAULT 0,
                        new_items INTEGER DEFAULT 0,
                        matches_found INTEGER DEFAULT 0,
                        error_message TEXT,
                        status VARCHAR(50) NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_pg_source_runs ON source_runs(source_id, run_timestamp DESC);
                    """
                )

                # 5. Employer Discovery: discovered_employers
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS discovered_employers (
                        id BIGSERIAL PRIMARY KEY,
                        company VARCHAR(255) NOT NULL,
                        system VARCHAR(100) NOT NULL,
                        slug VARCHAR(255) UNIQUE NOT NULL,
                        jobs_seen INTEGER DEFAULT 1,
                        status VARCHAR(50) DEFAULT 'new',
                        first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_pg_employers_status ON discovered_employers(status);
                    """
                )
            conn.commit()

    def save_raw_job(self, raw_job: RawJob) -> int:
        payload_data = raw_job.payload
        if isinstance(payload_data, str):
            try:
                payload_data = json.loads(payload_data)
            except Exception:
                payload_data = {"raw_text": raw_job.payload}

        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO raw_jobs (source, source_url, payload, fetched_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (raw_job.source, raw_job.source_url, json.dumps(payload_data), raw_job.fetched_at),
                )
                raw_id = cursor.fetchone()["id"]
            conn.commit()
            return int(raw_id)

    def upsert_job(self, job: Job) -> tuple[Job, bool]:
        now = datetime.now(timezone.utc)
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                # Check for existing listing by either canonical fingerprint OR URL
                cursor.execute(
                    """
                    SELECT id, fingerprint, first_seen, last_seen
                    FROM jobs
                    WHERE fingerprint = %s OR url = %s
                    LIMIT 1;
                    """,
                    (job.fingerprint, job.url),
                )
                existing = cursor.fetchone()

                if existing:
                    # Update existing job: update last_seen, merge deadline, update description if richer
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET last_seen = %s,
                            deadline_at = COALESCE(%s, jobs.deadline_at),
                            description = CASE WHEN length(%s) > length(jobs.description) THEN %s ELSE jobs.description END,
                            is_closed = FALSE
                        WHERE id = %s
                        RETURNING first_seen, last_seen;
                        """,
                        (now, job.deadline, job.description, job.description, existing["id"]),
                    )
                    res = cursor.fetchone()
                    job.fingerprint = existing["fingerprint"]
                    job.first_seen = res["first_seen"]
                    job.last_seen = res["last_seen"]
                    conn.commit()
                    return job, False
                else:
                    # Insert new job
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            fingerprint, url, title, company, location, description,
                            posted_at, deadline_at, source, raw_id, first_seen, last_seen, is_closed
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                        RETURNING first_seen, last_seen;
                        """,
                        (
                            job.fingerprint,
                            job.url,
                            job.title,
                            job.company,
                            job.location,
                            job.description,
                            job.posted,
                            job.deadline,
                            job.source,
                            job.raw_id,
                            job.first_seen,
                            now,
                        ),
                    )
                    res = cursor.fetchone()
                    job.first_seen = res["first_seen"]
                    job.last_seen = res["last_seen"]
                    conn.commit()
                    return job, True

    def save_scored_match(self, scored_job: ScoredJob) -> None:
        breakdown_dict = scored_job.score_breakdown.model_dump()
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scored_matches (
                        job_fingerprint, best_track_id, best_track_name, final_score,
                        is_match, is_near_miss, breakdown_json, alert_sent_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT(job_fingerprint) DO UPDATE SET
                        best_track_id = EXCLUDED.best_track_id,
                        best_track_name = EXCLUDED.best_track_name,
                        final_score = EXCLUDED.final_score,
                        is_match = EXCLUDED.is_match,
                        is_near_miss = EXCLUDED.is_near_miss,
                        breakdown_json = EXCLUDED.breakdown_json;
                    """,
                    (
                        scored_job.job.fingerprint,
                        scored_job.score_breakdown.best_track_id,
                        scored_job.score_breakdown.best_track_name,
                        scored_job.score_breakdown.final_score,
                        scored_job.score_breakdown.is_match,
                        scored_job.score_breakdown.is_near_miss,
                        json.dumps(breakdown_dict),
                        scored_job.alert_sent_at,
                    ),
                )
            conn.commit()

    def get_unnotified_matches(self, limit: int = 15) -> list[ScoredJob]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.*, m.breakdown_json, m.alert_sent_at
                    FROM scored_matches m
                    JOIN jobs j ON j.fingerprint = m.job_fingerprint
                    WHERE m.is_match = TRUE AND m.alert_sent_at IS NULL AND j.is_closed = FALSE
                    ORDER BY m.final_score DESC, j.first_seen DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
                return [self._row_to_scored_job(r) for r in rows]

    def mark_alert_sent(self, fingerprint: str, alert_time: Optional[datetime] = None) -> None:
        sent_time = alert_time or datetime.now(timezone.utc)
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE scored_matches SET alert_sent_at = %s WHERE job_fingerprint = %s;",
                    (sent_time, fingerprint),
                )
            conn.commit()

    def get_near_misses(self, days_back: int = 7) -> list[ScoredJob]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.*, m.breakdown_json, m.alert_sent_at
                    FROM scored_matches m
                    JOIN jobs j ON j.fingerprint = m.job_fingerprint
                    WHERE m.is_near_miss = TRUE AND j.first_seen >= %s AND j.is_closed = FALSE
                    ORDER BY m.final_score DESC;
                    """,
                    (cutoff,),
                )
                return [self._row_to_scored_job(r) for r in cursor.fetchall()]

    def get_closing_soon_matches(self, days_ahead: int = 3) -> list[ScoredJob]:
        now = datetime.now(timezone.utc)
        target = now + timedelta(days=days_ahead)
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.*, m.breakdown_json, m.alert_sent_at
                    FROM scored_matches m
                    JOIN jobs j ON j.fingerprint = m.job_fingerprint
                    WHERE m.is_match = TRUE
                      AND m.deadline_reminder_sent_at IS NULL
                      AND j.deadline_at IS NOT NULL
                      AND j.deadline_at <= %s
                      AND j.deadline_at >= %s
                      AND j.is_closed = FALSE;
                    """,
                    (target, now),
                )
                return [self._row_to_scored_job(r) for r in cursor.fetchall()]

    def mark_deadline_reminder_sent(self, fingerprint: str) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE scored_matches SET deadline_reminder_sent_at = NOW() WHERE job_fingerprint = %s;",
                    (fingerprint,),
                )
            conn.commit()

    def record_source_run(self, run: SourceRun) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO source_runs (
                        source_id, run_timestamp, items_fetched, new_items,
                        matches_found, error_message, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        run.source_id,
                        run.run_timestamp,
                        run.items_fetched,
                        run.new_items,
                        run.matches_found,
                        run.error_message,
                        run.status,
                    ),
                )
            conn.commit()

    def get_previous_source_run(self, source_id: str) -> Optional[SourceRun]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM source_runs
                    WHERE source_id = %s
                    ORDER BY run_timestamp DESC, id DESC
                    LIMIT 1 OFFSET 1;
                    """,
                    (source_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return SourceRun(
                    id=row["id"],
                    source_id=row["source_id"],
                    run_timestamp=row["run_timestamp"],
                    items_fetched=row["items_fetched"],
                    new_items=row["new_items"],
                    matches_found=row["matches_found"],
                    error_message=row["error_message"],
                    status=row["status"],
                )

    def upsert_discovered_employer(self, employer: DiscoveredEmployer) -> tuple[DiscoveredEmployer, bool]:
        now = datetime.now(timezone.utc)
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO discovered_employers (
                        company, system, slug, jobs_seen, status, first_seen, last_seen
                    ) VALUES (%s, %s, %s, 1, 'new', %s, %s)
                    ON CONFLICT(slug) DO UPDATE SET
                        jobs_seen = discovered_employers.jobs_seen + 1,
                        last_seen = EXCLUDED.last_seen
                    RETURNING id, jobs_seen, status, (xmax = 0) AS is_new;
                    """,
                    (employer.company, employer.system, employer.slug, now, now),
                )
                row = cursor.fetchone()
                employer.id = row["id"]
                employer.jobs_seen = row["jobs_seen"]
                employer.status = row["status"]
                is_new = row["is_new"]
            conn.commit()
            return employer, is_new

    def get_discovered_employers(self, status: Optional[str] = None) -> list[DiscoveredEmployer]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                if status:
                    cursor.execute(
                        "SELECT * FROM discovered_employers WHERE status = %s ORDER BY jobs_seen DESC;",
                        (status,),
                    )
                else:
                    cursor.execute("SELECT * FROM discovered_employers ORDER BY first_seen DESC;")

                rows = cursor.fetchall()
                return [
                    DiscoveredEmployer(
                        id=r["id"],
                        company=r["company"],
                        system=r["system"],
                        slug=r["slug"],
                        jobs_seen=r["jobs_seen"],
                        status=r["status"],
                        first_seen=r["first_seen"],
                    )
                    for r in rows
                ]

    def update_employer_status(self, employer_id: int, status: str) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE discovered_employers SET status = %s WHERE id = %s;",
                    (status, employer_id),
                )
                updated = cursor.rowcount > 0
            conn.commit()
            return updated

    def get_all_jobs_for_rescore(self) -> list[Job]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM jobs ORDER BY first_seen ASC;")
                return [self._row_to_job(r) for r in cursor.fetchall()]

    def count_total_jobs(self) -> int:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM jobs;")
                return int(cursor.fetchone()["count"])

    def _row_to_job(self, r: dict[str, Any]) -> Job:
        return Job(
            title=r["title"],
            company=r["company"],
            url=r["url"],
            location=r["location"],
            description=r["description"],
            posted=r["posted_at"],
            deadline=r["deadline_at"],
            source=r["source"],
            raw_id=r["raw_id"],
            fingerprint=r["fingerprint"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            is_closed=r["is_closed"],
        )

    def _row_to_scored_job(self, r: dict[str, Any]) -> ScoredJob:
        job = self._row_to_job(r)
        breakdown_data = r["breakdown_json"]
        if isinstance(breakdown_data, str):
            breakdown_data = json.loads(breakdown_data)
        breakdown = ScoreBreakdown.model_validate(breakdown_data)
        return ScoredJob(
            job=job,
            score_breakdown=breakdown,
            alert_sent_at=r["alert_sent_at"],
        )
