"""Domain entity models for JobRadar."""
from jobradar.domain.models import (
    RawJob,
    Job,
    TrackScore,
    ScoreBreakdown,
    ScoredJob,
    DiscoveredEmployer,
    SourceRun,
    generate_fingerprint,
    normalize_text,
)

__all__ = [
    "RawJob",
    "Job",
    "TrackScore",
    "ScoreBreakdown",
    "ScoredJob",
    "DiscoveredEmployer",
    "SourceRun",
    "generate_fingerprint",
    "normalize_text",
]
