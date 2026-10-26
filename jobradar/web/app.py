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
        pipeline = JobRadarPipeline()
        summary = pipeline.run(dry_run=False, force_digest=False)
        return {"status": "success", "summary": summary}
    except Exception as e:
        logger.exception("Manual pipeline run failed")
        raise HTTPException(status_code=500, detail=str(e))
