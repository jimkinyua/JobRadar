"""Telegram adapters package."""
from jobradar.adapters.telegram.client import TelegramClient
from jobradar.adapters.telegram.formatter import (
    format_job_alert,
    format_health_alert,
    format_near_miss_digest,
    format_deadline_reminder,
    format_employer_spotted,
)

__all__ = [
    "TelegramClient",
    "format_job_alert",
    "format_health_alert",
    "format_near_miss_digest",
    "format_deadline_reminder",
    "format_employer_spotted",
]
