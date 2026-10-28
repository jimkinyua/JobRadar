"""
FastAPI application serving the JobRadar Web Dashboard and JSON API.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from jobradar.adapters.storage.factory import get_repository
from jobradar.services.pipeline import JobRadarPipeline

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
    limit: int = 150,
):
    """Retrieve ranked jobs with explainable scoring breakdowns."""
    repo = get_repository()
    try:
        jobs = repo.get_dashboard_jobs(
            track_id=track,
            min_score=min_score,
            source=source,
            search=search,
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


@app.get("/api/sources")
async def get_sources():
    """List available sources from configuration."""
    from jobradar.config import load_config
    config = load_config()
    sources_data = [
        {"id": s.id, "name": s.name, "type": s.type, "enabled": s.enabled}
        for s in config.sources
    ]
    return {"sources": sources_data}


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

