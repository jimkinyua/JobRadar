"""
AI Service layer for JobRadar.

Coordinates high-level AI capabilities:
1. Semantic Fit & Gap Analysis (Evaluates high-scoring Gold jobs against the candidate profile)
2. Self-Healing Unstructured Extraction (Extracts job entities when standard CSS selectors return 0 listings)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel

from jobradar.config import AppConfig
from jobradar.domain.models import AICopilotInsight, ExtractedJobItem, Job
from jobradar.services.ai_client import GeminiClient

logger = logging.getLogger(__name__)


class ExtractedJobsList(BaseModel):
    """Container for batch job extraction to enforce schema validation."""
    jobs: list[ExtractedJobItem] = []


def load_candidate_profile(profile_path: str | Path = "config/profile.yaml") -> dict[str, Any]:
    """Load the candidate profile from YAML configuration."""
    path = Path(profile_path)
    if not path.exists():
        logger.warning("Candidate profile not found at '%s'. Using empty profile.", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("candidate", {})
    except Exception as e:
        logger.error("Failed to parse candidate profile at '%s': %s", path, e)
        return {}


class AIService:
    """High-level AI service orchestrating semantic candidate evaluation and web extraction."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        client: Optional[GeminiClient] = None,
        profile_path: str | Path = "config/profile.yaml",
    ) -> None:
        from jobradar.config import load_config
        self.config = config or load_config()
        self.client = client or GeminiClient(
            api_key=self.config.gemini_api_key,
            model=self.config.gemini_model,
        )
        self.profile = load_candidate_profile(profile_path)

    def is_available(self) -> bool:
        """Check whether the AI service is configured and ready."""
        return self.client.is_configured()

    def evaluate_job_fit(self, job: Job) -> Optional[AICopilotInsight]:
        """
        Evaluate a job match against the candidate profile.
        Returns an AICopilotInsight with fit score, rationale, skill gaps, and custom pitch.
        """
        if not self.is_available():
            logger.debug("AIService is not configured. Skipping job fit evaluation.")
            return None

        system_instruction = (
            "You are an expert Technical Recruiter and Career Advisor. "
            "Analyze the candidate profile against the provided job vacancy. "
            "Produce an honest, grounded evaluation. Highlight real synergy in key strengths, "
            "explicitly identify any missing tools or qualifications in skill gaps, "
            "and craft a concise, compelling resume bullet point tailored to this position."
        )

        profile_summary = (
            f"Candidate: {self.profile.get('name', 'Applicant')}\n"
            f"Title: {self.profile.get('title', 'Software Engineer')}\n"
            f"Years of Experience: {self.profile.get('years_experience', 'N/A')}\n"
            f"Core Skills: {', '.join(self.profile.get('core_skills', []))}\n"
            f"Familiar Tools: {', '.join(self.profile.get('familiar_tools', []))}\n"
            f"Summary: {self.profile.get('experience_summary', '')}"
        )

        prompt = (
            f"=== CANDIDATE PROFILE ===\n{profile_summary}\n\n"
            f"=== JOB VACANCY ===\n"
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location}\n"
            f"URL: {job.url}\n"
            f"Description:\n{job.description[:4000]}\n\n"
            "Evaluate this opportunity and return the structured JSON assessment."
        )

        try:
            insight = self.client.generate_json(
                prompt=prompt,
                system_instruction=system_instruction,
                schema_cls=AICopilotInsight,
                temperature=0.2,
            )
            return insight
        except Exception as e:
            logger.error("Error during AI job fit evaluation for '%s': %s", job.title, e)
            return None

    def extract_jobs_from_unstructured_page(
        self,
        page_text: str,
        base_url: str,
    ) -> list[ExtractedJobItem]:
        """
        Self-healing extraction fallback: converts raw webpage text or HTML into
        structured ExtractedJobItem objects when CSS selectors fail.
        """
        if not self.is_available():
            logger.debug("AIService is not configured. Skipping fallback extraction.")
            return []

        system_instruction = (
            "You are a strict data extraction agent. "
            "Extract all active job listings from the provided webpage text. "
            "For each job, extract the title, the full application or detail URL "
            "(resolving relative paths against the provided base URL), "
            "the location if stated, and a 1-sentence summary. "
            "Do not invent or hallucinate listings. Return a JSON object with a 'jobs' array."
        )

        prompt = (
            f"Base URL: {base_url}\n\n"
            f"Webpage Content (truncated):\n{page_text[:10000]}\n\n"
            "Extract all active job vacancies into the 'jobs' array."
        )

        try:
            result = self.client.generate_json(
                prompt=prompt,
                system_instruction=system_instruction,
                schema_cls=ExtractedJobsList,
                temperature=0.1,
            )
            if result and isinstance(result, ExtractedJobsList):
                return result.jobs
            return []
        except Exception as e:
            logger.error("Error during AI unstructured job extraction for '%s': %s", base_url, e)
            return []
