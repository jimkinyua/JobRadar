"""Storage adapters package - 100% PostgreSQL."""
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.adapters.storage.postgres_repo import PostgresRepository
from jobradar.adapters.storage.factory import get_repository

__all__ = ["BaseStorageRepository", "PostgresRepository", "get_repository"]
