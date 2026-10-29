"""
FastAPI application serving the JobRadar Web Dashboard and JSON API.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from jobradar.adapters.storage.factory import get_repository
from jobradar.services.pipeline import JobRadarPipeline
from jobradar.adapters.notion import NotionClient, sync_notion_with_repository

logger = logging.getLogger(__name__)

app = FastAPI(
    title="JobRadar Dashboard",
    description="Live job feed, multi-track matching, and ranking analytics.",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not compiled.")
    return FileResponse(index_file)


@app.get("/api/jobs")
async def get_jobs(
    track: Optional[str] = None,
    min_score: Optional[float] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 150,
):
    """Retrieve ranked jobs with explainable scoring breakdowns and application tracking status."""
    repo = get_repository()
    try:
        jobs = repo.get_dashboard_jobs(
            track_id=track,
            min_score=min_score,
            source=source,
            search=search,
            application_status=status,
            limit=limit,
        )
        return {"count": len(jobs), "jobs": jobs}
    finally:
        repo.close()



@app.get("/api/stats")
async def get_stats():
    """Retrieve aggregate KPIs for the dashboard header."""
    repo = get_repository()
    try:
        stats = repo.get_dashboard_stats()
        return stats
    finally:
        repo.close()


class SourceProbeRequest(BaseModel):
    url: str
    name: Optional[str] = None


class AddSourceRequest(BaseModel):
    name: str
    url: str
    type: str = "html"
    company_identifier: Optional[str] = None
    selectors: Optional[dict[str, str]] = None
    enabled: bool = True


class ToggleSourceRequest(BaseModel):
    enabled: bool


@app.get("/api/sources")
async def get_sources():
    """List available sources from configuration and database."""
    from jobradar.config import load_config
    config = load_config()
    sources_data = [
        {"id": s.id, "name": s.name, "type": s.type, "enabled": s.enabled, "custom": False}
        for s in config.sources
    ]

    try:
        repo = get_repository(config.database_url)
        custom_sources = repo.get_custom_sources()
        for cs in custom_sources:
            sources_data.append({
                "id": cs["id"],
                "name": cs["name"],
                "type": cs["type"],
                "url": cs["url"],
                "enabled": cs["enabled"],
                "custom": True,
            })
        repo.close()
    except Exception as e:
        logger.warning("Could not fetch custom sources: %s", e)

    return {"sources": sources_data}


@app.post("/api/sources/probe")
async def probe_source_endpoint(req: SourceProbeRequest):
    """Probe a career URL, detect its source adapter, and extract live sample jobs."""
    import asyncio
    from jobradar.services.source_detector import probe_source
    res = await asyncio.to_thread(probe_source, req.url, req.name)
    return res


@app.post("/api/sources")
async def add_source(req: AddSourceRequest):
    """Add a new custom source/employer into the crawler pipeline."""
    from jobradar.config import load_config
    config = load_config()
    repo = get_repository(config.database_url)
    try:
        saved = repo.save_custom_source(req.model_dump())
        return {"success": True, "source": saved}
    finally:
        repo.close()


@app.patch("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: str, req: ToggleSourceRequest):
    """Toggle a custom source active/paused."""
    from jobradar.config import load_config
    config = load_config()
    repo = get_repository(config.database_url)
    try:
        ok = repo.toggle_custom_source(source_id, req.enabled)
        if not ok:
            raise HTTPException(status_code=404, detail="Custom source not found.")
        return {"success": True, "id": source_id, "enabled": req.enabled}
    finally:
        repo.close()


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a custom source from the database."""
    from jobradar.config import load_config
    config = load_config()
    repo = get_repository(config.database_url)
    try:
        ok = repo.delete_custom_source(source_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Custom source not found.")
        return {"success": True, "id": source_id}
    finally:
        repo.close()


@app.post("/api/trigger-run")
async def trigger_run():
    """Trigger an on-demand crawl and scoring cycle."""
    try:
        import asyncio
        pipeline = JobRadarPipeline()
        summary = await asyncio.to_thread(pipeline.run, False, False)
        return {"status": "success", "summary": summary}
    except Exception as e:
        logger.exception("Manual pipeline run failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/{job_id}/ai-evaluate")
async def evaluate_job_ai(job_id: int):
    """Generate or retrieve AI Copilot fit insight for a specific job."""
    import asyncio
    import json
    from jobradar.config import load_config
    from jobradar.services.ai_service import AIService
    from jobradar.services.scorer import JobScorer
    from jobradar.domain.models import ScoredJob

    config = load_config()
    ai_service = AIService(config)
    if not ai_service.is_available():
        raise HTTPException(status_code=503, detail="Gemini AI service is not configured or available.")

    repo = get_repository(config.database_url)
    try:
        with repo.pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.*, m.breakdown_json
                    FROM jobs j
                    LEFT JOIN scored_matches m ON j.fingerprint = m.job_fingerprint
                    WHERE j.id = %s;
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Job not found.")

                job = repo._row_to_job(row)
                breakdown = row.get("breakdown_json") or {}
                if isinstance(breakdown, str):
                    try:
                        breakdown = json.loads(breakdown)
                    except Exception:
                        breakdown = {}

                # If already evaluated, return immediately
                if breakdown.get("ai_insight"):
                    return {"status": "existing", "ai_insight": breakdown["ai_insight"]}

                # Generate via Gemini AI
                insight = await asyncio.to_thread(ai_service.evaluate_job_fit, job)
                if not insight:
                    raise HTTPException(status_code=500, detail="AI evaluation could not be completed.")

                breakdown["ai_insight"] = insight.model_dump()

                # If scored_matches row exists, update it; else insert
                cursor.execute(
                    """
                    UPDATE scored_matches
                    SET breakdown_json = %s
                    WHERE job_fingerprint = %s;
                    """,
                    (json.dumps(breakdown), job.fingerprint),
                )
                if cursor.rowcount == 0:
                    scorer = JobScorer(config)
                    breakdown_obj = scorer.score(job)
                    scored = ScoredJob(job=job, score_breakdown=breakdown_obj, ai_insight=insight)
                    repo.save_scored_match(scored)

            conn.commit()

        return {"status": "generated", "ai_insight": breakdown["ai_insight"]}
    finally:
        repo.close()


class JobStatusUpdateRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/status")
async def update_job_status(job_id: int, req: JobStatusUpdateRequest):
    """Update job application status and synchronize with Notion."""
    import asyncio
    from jobradar.config import load_config

    config = load_config()
    repo = get_repository(config.database_url)
    try:
        job = repo.get_job_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")

        # Update locally
        updated_job = repo.update_job_application_status(
            job_id_or_fingerprint=job_id,
            status=req.status,
            notes=req.notes,
        )
        if not updated_job:
            raise HTTPException(status_code=500, detail="Failed to update job status.")

        notion_synced = False
        notion = NotionClient(config.notion_api_key, config.notion_database_id)
        if notion.is_configured():
            try:
                if updated_job.notion_page_id:
                    success = await asyncio.to_thread(
                        notion.update_application_page,
                        page_id=updated_job.notion_page_id,
                        status=req.status,
                        notes=req.notes,
                    )
                    notion_synced = bool(success)
                elif req.status.lower() != "unapplied":
                    page_id = await asyncio.to_thread(
                        notion.create_application_page,
                        job=updated_job,
                        status=req.status,
                        notes=req.notes or f"Tracked via JobRadar Web Dashboard.",
                    )
                    if page_id:
                        repo.update_job_application_status(
                            job_id_or_fingerprint=job_id,
                            status=req.status,
                            notion_page_id=page_id,
                        )
                        updated_job.notion_page_id = page_id
                        notion_synced = True
            except Exception as e:
                logger.warning("Failed to sync status update to Notion for job %d: %s", job_id, e)

        return {
            "success": True,
            "notion_synced": notion_synced,
            "job": {
                "id": updated_job.id,
                "title": updated_job.title,
                "company": updated_job.company,
                "application_status": updated_job.application_status,
                "applied_at": updated_job.applied_at.isoformat() if updated_job.applied_at else None,
                "notion_page_id": updated_job.notion_page_id,
                "notion_synced": notion_synced,
            },
        }
    finally:
        repo.close()


@app.post("/api/notion/sync")
async def trigger_notion_sync():
    """Trigger on-demand two-way sync with Notion Job Applications tracker."""
    import asyncio
    from jobradar.config import load_config

    config = load_config()
    notion = NotionClient(config.notion_api_key, config.notion_database_id)
    if not notion.is_configured():
        return {
            "success": False,
            "configured": False,
            "message": "Notion API key or Database ID is not configured in .env",
            "summary": {"notion_rows_scanned": 0, "synced_jobs": 0, "backfilled_links": 0},
        }

    repo = get_repository(config.database_url)
    try:
        summary = await asyncio.to_thread(sync_notion_with_repository, notion, repo)
        return {"success": True, "configured": True, "summary": summary}
    finally:
        repo.close()


