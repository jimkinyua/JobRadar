"""
Telegram bot client handling alert dispatching, health warnings, and two-way /add and /ignore commands.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import requests
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.adapters.telegram.formatter import (
    format_job_alert,
    format_health_alert,
    format_near_miss_digest,
    format_deadline_reminder,
    format_employer_spotted,
)
from jobradar.config import load_employers, save_employers
from jobradar.domain.models import ScoredJob, DiscoveredEmployer

logger = logging.getLogger(__name__)


class TelegramClient:
    """Client for Telegram Bot API operations."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.session = session or requests.Session()
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""

    def is_configured(self) -> bool:
        """Check if both token and chat_id are present."""
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send an HTML-formatted message to the authorized chat ID."""
        if not self.is_configured():
            logger.info("Telegram notification skipped: Bot token or Chat ID is not configured.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                return True
            else:
                logger.error("Failed to send Telegram message: HTTP %s - %s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.error("Exception while sending Telegram message: %s", e)
            return False

    def send_job_alert(self, scored_job: ScoredJob) -> bool:
        """Send a single job alert."""
        text = format_job_alert(scored_job)
        return self.send_message(text)

    def send_health_alert(self, unhealthy_sources: list[dict[str, Any]]) -> bool:
        """Send consolidated source health alert."""
        if not unhealthy_sources:
            return False
        text = format_health_alert(unhealthy_sources)
        return self.send_message(text)

    def send_near_miss_digest(self, near_misses: list[ScoredJob]) -> bool:
        """Send weekly Monday near-miss digest."""
        if not near_misses:
            return False
        text = format_near_miss_digest(near_misses)
        return self.send_message(text)

    def send_deadline_reminder(self, scored: ScoredJob) -> bool:
        """Send 3-day closing deadline reminder."""
        text = format_deadline_reminder(scored)
        return self.send_message(text)

    def send_employer_spotted(self, employer: DiscoveredEmployer, count: int) -> bool:
        """Alert user about a newly spotted employer ATS."""
        text = format_employer_spotted(employer, count)
        return self.send_message(text)

    def get_updates(self, offset: Optional[int] = None) -> list[dict[str, Any]]:
        """Fetch incoming bot updates from Telegram."""
        if not self.is_configured():
            return []

        url = f"{self.base_url}/getUpdates"
        params: dict[str, Any] = {"timeout": 2}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = self.session.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", [])
            return []
        except Exception as e:
            logger.error("Error polling Telegram updates: %s", e)
            return []

    def process_incoming_commands(
        self,
        storage_repo: BaseStorageRepository,
        employers_yaml_path: str | Path = "config/employers.yaml",
    ) -> list[str]:
        """
        Poll new messages and execute /add <id> and /ignore <id> commands.
        STRICT SECURITY: Rejects and ignores commands from any chat ID other than self.chat_id.
        """
        if not self.is_configured():
            logger.info("Telegram commands skipped: Bot credentials not configured.")
            return []

        updates = self.get_updates()
        if not updates:
            return []

        executed_actions: list[str] = []
        highest_update_id = 0

        for update in updates:
            update_id = update.get("update_id", 0)
            if update_id > highest_update_id:
                highest_update_id = update_id

            message = update.get("message") or update.get("channel_post")
            if not message:
                continue

            # Verify sender authorization
            sender_chat = message.get("chat", {})
            sender_id = str(sender_chat.get("id", "")).strip()

            if sender_id != self.chat_id:
                logger.warning(
                    "SECURITY: Rejected unauthorized Telegram message from chat ID '%s' (Authorized: '%s').",
                    sender_id,
                    self.chat_id,
                )
                continue

            text = (message.get("text") or "").strip()
            if not text.startswith("/"):
                continue

            parts = text.split()
            cmd = parts[0].lower()

            if cmd == "/add" and len(parts) >= 2:
                try:
                    emp_id = int(parts[1])
                    action_msg = self._handle_add_employer(emp_id, storage_repo, employers_yaml_path)
                    executed_actions.append(action_msg)
                    self.send_message(action_msg)
                except ValueError:
                    self.send_message("❌ Invalid format. Use: <code>/add &lt;id&gt;</code>")

            elif cmd == "/ignore" and len(parts) >= 2:
                try:
                    emp_id = int(parts[1])
                    action_msg = self._handle_ignore_employer(emp_id, storage_repo)
                    executed_actions.append(action_msg)
                    self.send_message(action_msg)
                except ValueError:
                    self.send_message("❌ Invalid format. Use: <code>/ignore &lt;id&gt;</code>")

            elif cmd == "/start":
                self.send_message(
                    "👋 <b>Job-Radar Bot Online</b>\nUse <code>/add &lt;id&gt;</code> or <code>/ignore &lt;id&gt;</code> to manage discovered employers."
                )

        # Acknowledge processed updates
        if highest_update_id > 0:
            self.get_updates(offset=highest_update_id + 1)

        return executed_actions

    def _handle_add_employer(
        self,
        employer_id: int,
        repo: BaseStorageRepository,
        employers_yaml_path: str | Path,
    ) -> str:
        """Approve employer in PostgreSQL and append to employers.yaml."""
        employers = repo.get_discovered_employers()
        target = next((e for e in employers if e.id == employer_id), None)

        if not target:
            return f"❌ Discovered employer with ID {employer_id} not found."

        # 1. Update database
        repo.update_employer_status(employer_id, "approved")

        # 2. Append to employers.yaml
        existing_yaml = load_employers(employers_yaml_path)
        if not any(e.get("identifier") == target.slug for e in existing_yaml):
            existing_yaml.append({
                "id": f"{target.system}_{target.slug}",
                "company": target.company,
                "system": target.system,
                "identifier": target.slug,
                "added_at": datetime.now(timezone.utc).isoformat(),
                "status": "approved",
            })
            save_employers(existing_yaml, employers_yaml_path)

        return f"✅ <b>Approved!</b> Added <b>{html.escape(target.company)}</b> ({target.system}) to watched employers registry."

    def _handle_ignore_employer(self, employer_id: int, repo: BaseStorageRepository) -> str:
        """Mark employer as ignored in PostgreSQL."""
        employers = repo.get_discovered_employers()
        target = next((e for e in employers if e.id == employer_id), None)

        if not target:
            return f"❌ Discovered employer with ID {employer_id} not found."

        repo.update_employer_status(employer_id, "ignored")
        return f"🚫 <b>Ignored</b> employer: <b>{html.escape(target.company)}</b>."
