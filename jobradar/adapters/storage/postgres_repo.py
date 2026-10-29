"""PostgreSQL implementation of the storage repository using psycopg 3 and ConnectionPool."""

from __future__ import annotations

import json
import re
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

                    -- Notion & Application tracking migrations
                    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS application_status VARCHAR(50) DEFAULT 'unapplied';
                    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;
                    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notion_page_id VARCHAR(100);
                    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notion_synced_at TIMESTAMPTZ;
                    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS application_notes TEXT;
                    CREATE INDEX IF NOT EXISTS idx_pg_jobs_app_status ON jobs(application_status);
                    CREATE INDEX IF NOT EXISTS idx_pg_jobs_notion_page ON jobs(notion_page_id);
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

                    -- 6. Dynamic Custom Sources added via Web UI
                    CREATE TABLE IF NOT EXISTS custom_sources (
                        id VARCHAR(64) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(32) NOT NULL,
                        url TEXT NOT NULL,
                        company_identifier VARCHAR(128),
                        selectors_json JSONB,
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
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
                        RETURNING id, first_seen, last_seen, application_status, applied_at, notion_page_id;
                        """,
                        (now, job.deadline, job.description, job.description, existing["id"]),
                    )
                    res = cursor.fetchone()
                    job.id = res["id"]
                    job.fingerprint = existing["fingerprint"]
                    job.first_seen = res["first_seen"]
                    job.last_seen = res["last_seen"]
                    job.application_status = res.get("application_status") or "unapplied"
                    job.applied_at = res.get("applied_at")
                    job.notion_page_id = res.get("notion_page_id")
                    conn.commit()
                    return job, False
                else:
                    # Insert new job
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            fingerprint, url, title, company, location, description,
                            posted_at, deadline_at, source, raw_id, first_seen, last_seen, is_closed,
                            application_status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                        RETURNING id, first_seen, last_seen;
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
                            job.application_status or "unapplied",
                        ),
                    )
                    res = cursor.fetchone()
                    job.id = res["id"]
                    job.first_seen = res["first_seen"]
                    job.last_seen = res["last_seen"]
                    conn.commit()
                    return job, True


    def save_scored_match(self, scored_job: ScoredJob) -> None:
        breakdown_dict = scored_job.score_breakdown.model_dump()
        if scored_job.ai_insight:
            breakdown_dict["ai_insight"] = scored_job.ai_insight.model_dump()
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

    def get_unnotified_matches(
        self, limit: int = 15, min_score: Optional[float] = None
    ) -> list[ScoredJob]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT j.*, m.breakdown_json, m.alert_sent_at
                    FROM scored_matches m
                    JOIN jobs j ON j.fingerprint = m.job_fingerprint
                    WHERE m.is_match = TRUE
                      AND m.alert_sent_at IS NULL
                      AND j.is_closed = FALSE
                      AND (j.application_status IS NULL OR LOWER(j.application_status) IN ('unapplied', 'to apply'))
                """
                params: list[Any] = []
                if min_score is not None:
                    query += " AND m.final_score >= %s"
                    params.append(min_score)

                query += " ORDER BY m.final_score DESC, j.first_seen DESC LIMIT %s;"
                params.append(limit)

                cursor.execute(query, tuple(params))
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
                    WHERE m.is_near_miss = TRUE
                      AND j.first_seen >= %s
                      AND j.is_closed = FALSE
                      AND (j.application_status IS NULL OR LOWER(j.application_status) IN ('unapplied', 'to apply'))
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
                      AND j.is_closed = FALSE
                      AND (j.application_status IS NULL OR LOWER(j.application_status) IN ('unapplied', 'to apply'));
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

    def get_job_by_id(self, job_id: int) -> Optional[Job]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM jobs WHERE id = %s LIMIT 1;", (job_id,))
                row = cursor.fetchone()
                return self._row_to_job(row) if row else None

    def get_job_by_url(self, url: str) -> Optional[Job]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM jobs WHERE url = %s LIMIT 1;", (url,))
                row = cursor.fetchone()
                return self._row_to_job(row) if row else None

    def update_job_application_status(
        self,
        job_id_or_fingerprint: int | str,
        status: str,
        applied_at: Optional[datetime] = None,
        notion_page_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Job]:
        now = datetime.now(timezone.utc)
        app_time = applied_at
        if status.lower() in ("applied", "screening", "interview", "final_round", "offer") and not app_time:
            app_time = now

        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                if isinstance(job_id_or_fingerprint, int) or (isinstance(job_id_or_fingerprint, str) and str(job_id_or_fingerprint).isdigit()):
                    where_clause = "id = %s"
                    val: Any = int(job_id_or_fingerprint)
                else:
                    where_clause = "fingerprint = %s"
                    val = str(job_id_or_fingerprint)

                cursor.execute(
                    f"""
                    UPDATE jobs
                    SET application_status = %s,
                        applied_at = COALESCE(%s, applied_at),
                        notion_page_id = COALESCE(%s, notion_page_id),
                        notion_synced_at = %s,
                        application_notes = COALESCE(%s, application_notes)
                    WHERE {where_clause}
                    RETURNING *;
                    """,
                    (status, app_time, notion_page_id, now, notes, val),
                )
                row = cursor.fetchone()
            conn.commit()
            return self._row_to_job(row) if row else None

    def _row_to_job(self, r: dict[str, Any]) -> Job:
        return Job(
            id=r.get("id"),
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
            application_status=r.get("application_status") or "unapplied",
            applied_at=r.get("applied_at"),
            notion_page_id=r.get("notion_page_id"),
            notion_synced_at=r.get("notion_synced_at"),
            application_notes=r.get("application_notes"),
        )

    def _row_to_scored_job(self, r: dict[str, Any]) -> ScoredJob:
        job = self._row_to_job(r)
        breakdown_data = r["breakdown_json"]
        if isinstance(breakdown_data, str):
            breakdown_data = json.loads(breakdown_data)
        breakdown = ScoreBreakdown.model_validate(breakdown_data)
        ai_insight = None
        if isinstance(breakdown_data, dict) and breakdown_data.get("ai_insight"):
            try:
                from jobradar.domain.models import AICopilotInsight
                ai_insight = AICopilotInsight.model_validate(breakdown_data["ai_insight"])
            except Exception:
                ai_insight = None
        return ScoredJob(
            job=job,
            score_breakdown=breakdown,
            ai_insight=ai_insight,
            alert_sent_at=r["alert_sent_at"],
        )

    def get_dashboard_jobs(
        self,
        track_id: Optional[str] = None,
        min_score: Optional[float] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        application_status: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []

        if application_status == "applied":
            clauses.append("LOWER(j.application_status) IN ('applied', 'screening', 'interview', 'final round', 'final_round', 'offer')")
        elif application_status == "closed":
            clauses.append("(j.is_closed = TRUE OR LOWER(j.application_status) IN ('rejected', 'withdrawn', 'no response', 'no_response', 'closed'))")
        elif application_status == "new":
            clauses.append("j.is_closed = FALSE AND (j.application_status IS NULL OR LOWER(j.application_status) IN ('unapplied', 'to apply'))")
        elif application_status == "all":
            pass
        else:
            clauses.append("j.is_closed = FALSE AND (j.application_status IS NULL OR LOWER(j.application_status) NOT IN ('rejected', 'withdrawn', 'no response', 'no_response', 'closed'))")

        if track_id and track_id != "all":
            clauses.append("m.best_track_id = %s")
            params.append(track_id)

        if min_score is not None:
            clauses.append("m.final_score >= %s")
            params.append(min_score)

        if source and source != "all":
            clauses.append("j.source = %s")
            params.append(source)

        if search and search.strip():
            clauses.append("(j.title ILIKE %s OR j.company ILIKE %s OR j.location ILIKE %s OR j.description ILIKE %s)")
            q = f"%{search.strip()}%"
            params.extend([q, q, q, q])

        where_sql = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)

        query = f"""
        SELECT 
            j.id,
            j.fingerprint,
            j.url,
            j.title,
            j.company,
            j.location,
            j.description,
            j.posted_at,
            j.deadline_at,
            j.source,
            j.first_seen,
            j.last_seen,
            j.is_closed,
            COALESCE(j.application_status, 'unapplied') AS application_status,
            j.applied_at,
            j.notion_page_id,
            j.notion_synced_at,
            j.application_notes,
            COALESCE(m.best_track_id, 'general') AS best_track_id,
            COALESCE(m.best_track_name, 'General Tech') AS best_track_name,
            COALESCE(m.final_score, 0.0) AS final_score,
            COALESCE(m.is_match, FALSE) AS is_match,
            COALESCE(m.is_near_miss, FALSE) AS is_near_miss,
            m.breakdown_json
        FROM jobs j
        LEFT JOIN scored_matches m ON j.fingerprint = m.job_fingerprint
        WHERE {where_sql}
        ORDER BY m.final_score DESC NULLS LAST, j.first_seen DESC
        LIMIT %s;
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    breakdown = r["breakdown_json"]
                    if isinstance(breakdown, str):
                        try:
                            breakdown = json.loads(breakdown)
                        except Exception:
                            breakdown = {}
                    elif breakdown is None:
                        breakdown = {}

                    results.append({
                        "id": r["id"],
                        "fingerprint": r["fingerprint"],
                        "url": r["url"],
                        "title": r["title"],
                        "company": r["company"],
                        "location": r["location"] or "Unspecified",
                        "description": r["description"][:250] + "..." if len(r["description"] or "") > 250 else (r["description"] or ""),
                        "full_description": r["description"] or "No detailed description provided.",
                        "posted_at": r["posted_at"].isoformat() if r["posted_at"] else None,
                        "deadline_at": r["deadline_at"].isoformat() if r["deadline_at"] else None,
                        "source": r["source"],
                        "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                        "is_closed": bool(r["is_closed"]),
                        "application_status": r["application_status"],
                        "applied_at": r["applied_at"].isoformat() if r["applied_at"] else None,
                        "notion_page_id": r["notion_page_id"],
                        "notion_synced_at": r["notion_synced_at"].isoformat() if r["notion_synced_at"] else None,
                        "application_notes": r["application_notes"],
                        "best_track_id": r["best_track_id"],
                        "best_track_name": r["best_track_name"],
                        "final_score": float(r["final_score"]),
                        "is_match": bool(r["is_match"]),
                        "is_near_miss": bool(r["is_near_miss"]),
                        "breakdown": breakdown,
                    })
                return results

    def get_dashboard_stats(self) -> dict:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        (SELECT COUNT(*) FROM jobs WHERE is_closed = FALSE AND (application_status IS NULL OR LOWER(application_status) IN ('unapplied', 'to apply'))) AS total_jobs,
                        (SELECT COUNT(*) FROM jobs WHERE LOWER(application_status) IN ('applied', 'screening', 'interview', 'final round', 'final_round', 'offer')) AS applied_count,
                        (SELECT COUNT(*) FROM scored_matches WHERE is_match = TRUE) AS high_matches,
                        (SELECT COUNT(*) FROM scored_matches WHERE is_near_miss = TRUE) AS near_misses,
                        (SELECT COUNT(DISTINCT source) FROM jobs) AS active_sources,
                        (SELECT COUNT(*) FROM discovered_employers) AS employers_spotted,
                        (SELECT COALESCE(ROUND(AVG(final_score)::numeric, 1), 0.0) FROM (
                            SELECT final_score FROM scored_matches WHERE is_match = TRUE ORDER BY final_score DESC LIMIT 10
                         ) top10) AS top10_avg_score;
                    """
                )
                row = cursor.fetchone()
                return {
                    "total_jobs": int(row["total_jobs"] or 0),
                    "applied_count": int(row["applied_count"] or 0),
                    "high_matches": int(row["high_matches"] or 0),
                    "near_misses": int(row["near_misses"] or 0),
                    "active_sources": int(row["active_sources"] or 0),
                    "employers_spotted": int(row["employers_spotted"] or 0),
                    "top10_avg_score": float(row["top10_avg_score"] or 0.0),
                }

    def save_custom_source(self, source_data: dict[str, Any]) -> dict[str, Any]:
        source_id = source_data.get("id") or re.sub(r"[^a-z0-9_]", "_", source_data["name"].lower().strip())
        name = source_data["name"].strip()
        stype = source_data.get("type", "html").strip()
        url = source_data["url"].strip()
        company_id = source_data.get("company_identifier")
        selectors = source_data.get("selectors")
        selectors_json = json.dumps(selectors) if selectors else None
        enabled = source_data.get("enabled", True)

        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO custom_sources (
                        id, name, type, url, company_identifier, selectors_json, enabled, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        type = EXCLUDED.type,
                        url = EXCLUDED.url,
                        company_identifier = EXCLUDED.company_identifier,
                        selectors_json = EXCLUDED.selectors_json,
                        enabled = EXCLUDED.enabled,
                        updated_at = NOW()
                    RETURNING *;
                    """,
                    (source_id, name, stype, url, company_id, selectors_json, enabled),
                )
                row = cursor.fetchone()
            conn.commit()

        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "url": row["url"],
            "company_identifier": row["company_identifier"],
            "selectors": json.loads(row["selectors_json"]) if row["selectors_json"] else None,
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def get_custom_sources(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM custom_sources ORDER BY created_at DESC;")
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "url": r["url"],
                        "company_identifier": r["company_identifier"],
                        "selectors": json.loads(r["selectors_json"]) if r["selectors_json"] else None,
                        "enabled": bool(r["enabled"]),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    })
                return results

    def toggle_custom_source(self, source_id: str, enabled: bool) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE custom_sources SET enabled = %s, updated_at = NOW() WHERE id = %s;",
                    (enabled, source_id),
                )
                updated = cursor.rowcount > 0
            conn.commit()
            return updated

    def delete_custom_source(self, source_id: str) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM custom_sources WHERE id = %s;", (source_id,))
                deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

