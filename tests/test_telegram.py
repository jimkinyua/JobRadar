"""Unit tests for Telegram client, HTML escaping, and command handler security."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from jobradar.adapters.telegram.client import TelegramClient
from jobradar.adapters.telegram.formatter import (
    format_job_alert,
    format_health_alert,
    format_near_miss_digest,
    format_deadline_reminder,
    format_employer_spotted,
)
from jobradar.adapters.storage.postgres_repo import PostgresRepository
from jobradar.domain.models import Job, ScoredJob, ScoreBreakdown, DiscoveredEmployer


def test_telegram_html_escaping():
    job = Job(
        title="Senior C# & .NET Lead <Core Engine>",
        company="Fintech 'Innovation' & Co.",
        url="https://example.com/jobs?id=1&ref=tg",
        location="Nairobi <Remote>",
        source="test",
    )
    breakdown = ScoreBreakdown(
        best_track_id="track_dotnet_azure",
        best_track_name="Enterprise .NET & Cloud",
        track_score=15.0,
        final_score=18.0,
        is_match=True,
        is_near_miss=False,
    )
    scored = ScoredJob(job=job, score_breakdown=breakdown)
    alert_html = format_job_alert(scored)

    # HTML tags must be properly escaped
    assert "&amp;" in alert_html
    assert "&lt;Core Engine&gt;" in alert_html
    assert "Fintech &#x27;Innovation&#x27; &amp; Co." in alert_html or "Fintech 'Innovation' &amp; Co." in alert_html
    assert "&lt;Remote&gt;" in alert_html


def test_telegram_send_message_success():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_session.post.return_value = mock_resp

    client = TelegramClient(bot_token="fake_token", chat_id="12345678", session=mock_session)
    sent = client.send_message("<b>Hello World</b>")

    assert sent is True
    mock_session.post.assert_called_once()
    args, kwargs = mock_session.post.call_args
    assert "fake_token" in args[0]
    assert kwargs["json"]["chat_id"] == "12345678"
    assert kwargs["json"]["parse_mode"] == "HTML"


def test_command_handler_authorized_execution(tmp_path: Path):
    mock_repo = MagicMock(spec=PostgresRepository)
    emp = DiscoveredEmployer(id=42, company="Watu", system="greenhouse", slug="watu")
    mock_repo.get_discovered_employers.return_value = [emp]

    mock_session = MagicMock()
    mock_session.get.return_value.status_code = 200
    mock_session.get.return_value.json.return_value = {
        "result": [
            {
                "update_id": 100,
                "message": {
                    "chat": {"id": "11223344"},
                    "from": {"id": "11223344"},
                    "text": "/add 42",
                },
            }
        ]
    }
    mock_session.post.return_value.status_code = 200

    temp_yaml = tmp_path / "employers.yaml"
    client = TelegramClient(bot_token="fake_token", chat_id="11223344", session=mock_session)
    actions = client.process_incoming_commands(mock_repo, temp_yaml)

    assert len(actions) == 1
    assert "Approved!" in actions[0]
    mock_repo.update_employer_status.assert_called_once_with(42, "approved")


def test_command_handler_security_rejects_unauthorized_chat(tmp_path: Path):
    mock_repo = MagicMock(spec=PostgresRepository)

    # An unauthorized sender (chat ID 99999999) tries to run a command
    mock_session = MagicMock()
    mock_session.get.return_value.status_code = 200
    mock_session.get.return_value.json.return_value = {
        "result": [
            {
                "update_id": 101,
                "message": {
                    "chat": {"id": "99999999"},
                    "from": {"id": "99999999"},
                    "text": "/add 42",
                },
            }
        ]
    }

    temp_yaml = tmp_path / "employers.yaml"
    # Authorized chat is 11223344
    client = TelegramClient(bot_token="fake_token", chat_id="11223344", session=mock_session)
    actions = client.process_incoming_commands(mock_repo, temp_yaml)

    # Must be completely ignored! No actions executed, no DB update
    assert len(actions) == 0
    mock_repo.update_employer_status.assert_not_called()


def test_command_handler_ignore_command():
    mock_repo = MagicMock(spec=PostgresRepository)
    emp = DiscoveredEmployer(id=77, company="Random Org", system="lever", slug="random")
    mock_repo.get_discovered_employers.return_value = [emp]

    mock_session = MagicMock()
    mock_session.get.return_value.status_code = 200
    mock_session.get.return_value.json.return_value = {
        "result": [
            {
                "update_id": 102,
                "message": {
                    "chat": {"id": "55555"},
                    "from": {"id": "55555"},
                    "text": "/ignore 77",
                },
            }
        ]
    }
    mock_session.post.return_value.status_code = 200

    client = TelegramClient(bot_token="fake_token", chat_id="55555", session=mock_session)
    actions = client.process_incoming_commands(mock_repo)

    assert len(actions) == 1
    assert "Ignored" in actions[0]
    mock_repo.update_employer_status.assert_called_once_with(77, "ignored")


def test_telegram_alert_with_ai_insight():
    from jobradar.domain.models import AICopilotInsight
    job = Job(
        title="AI Application Engineer",
        company="Co-operative Bank of Kenya",
        url="https://example.com/job/10",
        location="Nairobi",
        source="coop",
    )
    breakdown = ScoreBreakdown(
        best_track_id="track_ai_ml",
        best_track_name="AI & Machine Learning Engineering",
        track_score=15.0,
        final_score=18.0,
        is_match=True,
        is_near_miss=False,
    )
    insight = AICopilotInsight(
        semantic_fit_score=94,
        fit_rationale="High synergy with Python and data pipelines.",
        key_strengths=["Python", "FastAPI"],
        skill_gaps=["Qdrant vector database"],
        tailored_pitch="Engineered automated data pipelines in PostgreSQL.",
    )
    scored = ScoredJob(job=job, score_breakdown=breakdown, ai_insight=insight)
    alert_html = format_job_alert(scored)

    assert "94% Fit" in alert_html
    assert "High synergy with Python" in alert_html
    assert "Qdrant vector database" in alert_html
    assert "Engineered automated data pipelines in PostgreSQL." in alert_html

