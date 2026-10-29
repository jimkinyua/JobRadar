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

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Send an HTML-formatted message to the authorized chat ID with optional inline buttons."""
        if not self.is_configured():
            logger.info("Telegram notification skipped: Bot token or Chat ID is not configured.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

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

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        """Acknowledge Telegram callback query to dismiss loading animation."""
        if not self.is_configured():
            return False
        url = f"{self.base_url}/answerCallbackQuery"
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            resp = self.session.post(url, json=payload, timeout=10.0)
            return resp.status_code == 200
        except Exception:
            return False

    def send_job_alert(self, scored_job: ScoredJob) -> bool:
        """Send a single job alert with interactive application tracking buttons."""
        text = format_job_alert(scored_job)
        job_id = scored_job.job.id or scored_job.job.fingerprint

        inline_keyboard = [
            [
                {"text": "✅ Mark Applied", "callback_data": f"app:applied:{job_id}"},
                {"text": "🚫 Not Interested", "callback_data": f"app:withdrawn:{job_id}"},
            ]
        ]
        if scored_job.job.url:
            inline_keyboard.append([{"text": "🌐 Open Job Link", "url": scored_job.job.url}])

        reply_markup = {"inline_keyboard": inline_keyboard}
        return self.send_message(text, reply_markup=reply_markup)

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

    def send_employer_spotted(self, employer: DiscoveredEmployer, count: int = 1, matching_jobs: Optional[int] = None) -> bool:
        """Alert user about a newly spotted employer ATS."""
        effective_count = matching_jobs if matching_jobs is not None else count
        text = format_employer_spotted(employer, effective_count)
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
        notion_client: Optional[Any] = None,
    ) -> list[str]:
        """
        Poll new messages and callback queries.
        Supports:
          - Inline buttons: Mark Applied and Not Interested (pushes to Notion)
          - Slash commands: /add <id>, /ignore <id>, /apply <id>, /status <id>, /sync
        STRICT SECURITY: Rejects interactions from unauthorized chat IDs.
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

            # 1. Handle Inline Keyboard Callbacks
            callback_query = update.get("callback_query")
            if callback_query:
                cb_sender = callback_query.get("from", {})
                cb_sender_id = str(cb_sender.get("id", "")).strip()
                cb_chat = callback_query.get("message", {}).get("chat", {})
                cb_chat_id = str(cb_chat.get("id", "")).strip()

                if cb_chat_id != self.chat_id and cb_sender_id != self.chat_id:
                    logger.warning("SECURITY: Rejected callback query from unauthorized ID '%s'", cb_sender_id)
                    continue

                cb_data = callback_query.get("data", "")
                cb_id = callback_query.get("id")
                if cb_data.startswith("app:"):
                    action_msg = self._handle_app_status_callback(cb_data, storage_repo, notion_client)
                    self.answer_callback_query(cb_id, text=action_msg[:100])
                    self.send_message(action_msg)
                    executed_actions.append(action_msg)
                continue

            # 2. Handle Text Messages and Commands
            message = update.get("message") or update.get("channel_post")
            if not message:
                continue

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

            elif cmd == "/apply" and len(parts) >= 2:
                target_id = parts[1].strip()
                action_msg = self._handle_apply_command(target_id, storage_repo, notion_client)
                executed_actions.append(action_msg)
                self.send_message(action_msg)

            elif cmd == "/sync":
                if notion_client and notion_client.is_configured():
                    from jobradar.adapters.notion.sync import sync_notion_with_repository
                    res = sync_notion_with_repository(notion_client, storage_repo)
                    msg = (
                        f"🔄 <b>Notion Sync Completed</b>\n"
                        f"• Notion rows scanned: {res['notion_rows_scanned']}\n"
                        f"• Local jobs updated: {res['synced_jobs']}\n"
                        f"• Links backfilled: {res['backfilled_links']}"
                    )
                else:
                    msg = "⚠️ Notion integration is not configured."
                self.send_message(msg)
                executed_actions.append(msg)

            elif cmd == "/start":
                self.send_message(
                    "👋 <b>Job-Radar Bot Online</b>\n"
                    "• Tap inline buttons on alerts to mark jobs as Applied or Withdrawn\n"
                    "• <code>/apply &lt;id&gt;</code> - Mark a job applied and sync to Notion\n"
                    "• <code>/sync</code> - Trigger immediate two-way Notion sync\n"
                    "• <code>/add &lt;id&gt;</code> - Approve discovered employer ATS"
                )

        # Acknowledge processed updates
        if highest_update_id > 0:
            self.get_updates(offset=highest_update_id + 1)

        return executed_actions


    def _handle_app_status_callback(
        self,
        callback_data: str,
        repo: BaseStorageRepository,
        notion_client: Optional[Any],
    ) -> str:
        """
        Handle inline callback query data e.g. 'app:applied:<id>' or 'app:withdrawn:<id>'.
        Updates local JobRadar application_status and synchronizes directly with Notion.
        """
        parts = callback_data.split(":")
        if len(parts) < 3:
            return "❌ Invalid callback payload."

        action = parts[1].lower()
        job_identifier = parts[2]
        status_label = "Applied" if action == "applied" else "Withdrawn"

        # Update local database
        updated_job = repo.update_job_application_status(
            job_id_or_fingerprint=job_identifier,
            status=status_label,
        )
        if not updated_job:
            return f"❌ Job with identifier '{job_identifier}' not found."

        notion_status_msg = ""
        if notion_client and notion_client.is_configured():
            try:
                if updated_job.notion_page_id:
                    notion_client.update_application_page(
                        page_id=updated_job.notion_page_id,
                        status=status_label,
                    )
                    notion_status_msg = " and updated in Notion"
                else:
                    page_id = notion_client.create_application_page(
                        job=updated_job,
                        status=status_label,
                        notes="Tracked via JobRadar Telegram Alert.",
                    )
                    if page_id:
                        repo.update_job_application_status(
                            job_id_or_fingerprint=updated_job.fingerprint,
                            status=status_label,
                            notion_page_id=page_id,
                        )
                        notion_status_msg = " and created in Notion"
            except Exception as e:
                logger.error("Failed to push status to Notion from Telegram callback: %s", e)
                notion_status_msg = " (Notion push pending sync)"

        return (
            f"✅ Marked <b>{html.escape(updated_job.title)}</b> at "
            f"<b>{html.escape(updated_job.company)}</b> as <b>{status_label}</b>{notion_status_msg}!"
        )

    def _handle_apply_command(
        self,
        target_id: str,
        repo: BaseStorageRepository,
        notion_client: Optional[Any],
    ) -> str:
        return self._handle_app_status_callback(f"app:applied:{target_id}", repo, notion_client)


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
