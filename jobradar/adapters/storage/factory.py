"""Repository factory for JobRadar PostgreSQL storage."""

from __future__ import annotations

import os
from typing import Optional
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.adapters.storage.postgres_repo import PostgresRepository


def get_repository(database_url: Optional[str] = None) -> BaseStorageRepository:
    """Factory function returning the PostgreSQL repository instance."""
    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError(
            "DATABASE_URL environment variable is not set. "
            "Please configure your PostgreSQL connection string in the .env file."
        )
    return PostgresRepository(url)
