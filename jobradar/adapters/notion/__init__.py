"""Notion integration adapter package for JobRadar."""

from jobradar.adapters.notion.client import NotionClient
from jobradar.adapters.notion.sync import sync_notion_with_repository

__all__ = ["NotionClient", "sync_notion_with_repository"]
