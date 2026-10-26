"""Base adapter defining the contract for all source fetchers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
import requests
from jobradar.config import SourceConfig, CrawlerConfig
from jobradar.domain.models import Job, RawJob, SourceRun

logger = logging.getLogger(__name__)


class BaseSourceAdapter(ABC):
    """Abstract base adapter with built-in fault isolation and observability."""

    def __init__(self, source_config: SourceConfig, crawler_config: CrawlerConfig) -> None:
        self.source_config = source_config
        self.crawler_config = crawler_config
        self.source_id = source_config.id
        self.source_name = source_config.name

    def get_session(self) -> requests.Session:
        """Create a configured HTTP session with honest User-Agent."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.crawler_config.user_agent,
            "Accept": "application/json, application/xml, text/html, */*",
        })
        return session

    @abstractmethod
    def fetch_jobs(self, session: Optional[requests.Session] = None) -> list[tuple[RawJob, Job]]:
        """Fetch listings from the source and return Bronze RawJob paired with Silver Job."""
        pass

    def safe_fetch(self, session: Optional[requests.Session] = None) -> tuple[list[tuple[RawJob, Job]], SourceRun]:
        """
        Execute fetch with strict fault isolation.
        Catches any unexpected network/parsing error and records it in SourceRun without crashing the pipeline.
        """
        start_time = datetime.now(timezone.utc)
        sess = session or self.get_session()

        try:
            items = self.fetch_jobs(sess)
            run = SourceRun(
                source_id=self.source_id,
                run_timestamp=start_time,
                items_fetched=len(items),
                new_items=0,  # calculated during storage upsert
                matches_found=0,  # calculated during scoring
                error_message=None,
                status="success" if items else "partial",
            )
            return items, run
        except Exception as e:
            logger.error(f"Source '{self.source_id}' failed: {e}", exc_info=True)
            run = SourceRun(
                source_id=self.source_id,
                run_timestamp=start_time,
                items_fetched=0,
                new_items=0,
                matches_found=0,
                error_message=str(e),
                status="failed",
            )
            return [], run
